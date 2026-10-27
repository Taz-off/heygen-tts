#!/usr/bin/env python3
"""HeyGen voice studio -> MP3 without spending video credits.

The audio preview in HeyGen is free on every plan; credits are only charged
for the avatar video render. This tool drives the voice studio, grabs the
generated audio from the network, and never clicks Generate / Render Scene.

Subcommands: doctor | login | voices | clone | tts
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP = "https://app.heygen.com"
VOICE_APP = APP + "/apps/creative-studio/voice"
VOICES_PAGE = APP + "/avatar/voices"
HOME = Path(os.environ.get("HEYGEN_TTS_HOME") or (Path.home() / ".config" / "heygen-tts"))
PROFILE = HOME / "profile"
DEBUG_DIR = HOME / "debug"
VOICES_FILE = HOME / "voices.json"
LOG_FILE = HOME / "last-run.log"
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac")
CHALLENGE_RE = re.compile(
    r"verify you are human|v[eé]rifiez que vous [eê]tes humain|just a moment|un instant",
    re.I,
)
GENERATE_RE = re.compile(r"^\s*(generate|g[eé]n[eé]rer|create speech|cr[eé]er)\b", re.I)
# UI labels: French is the verified locale, English is the fallback guess.
MINE_RE = re.compile(r"^(Mes voix|My voices)$", re.I)
LIBRARY_RE = re.compile(r"(Bibliothèque HeyGen|Voice Library|HeyGen Library)", re.I)
SEARCH_VOICE_RE = re.compile(r"(Rechercher des voix|Search voices)", re.I)
CREATE_VOICE_RE = re.compile(r"(Créez votre voix HeyGen|Create your HeyGen voice)", re.I)
UPLOAD_AUDIO_RE = re.compile(r"(Téléverser de l.audio|Upload audio)", re.I)
SELECT_VOICE_RE = re.compile(r"(Sélectionner une voix|Select voice)", re.I)
VOICE_CARD_JS = """() => {
    const cards = [...document.querySelectorAll('button[data-atlas-id="voice-card-play-btn"]')]
        .map(b => (b.getAttribute('aria-label') || '').replace(/^Play /, ''));
    const rows = [...document.querySelectorAll('[data-atlas-id="voice-row"] [title]')]
        .map(e => e.getAttribute('title'));
    return [...cards, ...rows].filter(Boolean);
}"""
# Default voices by language. `--voice` overrides; `--no-voice` keeps the studio's active voice.
DEFAULT_VOICES = {
    "fr": "Martin Dupont Aimable",
    "en": "Roderic - Authoritative & Refined",
}
FRENCH_RE = re.compile(
    r"[àâçéèêëîïôùûüÿœ]|\b(le|la|les|un|une|des|du|de|et|est|pour|avec|dans|que|qui|sur|pas|vous|nous|je|tu|il|elle|ce|cette|au|aux)\b",
    re.I,
)
ENGLISH_RE = re.compile(
    r"\b(the|and|is|are|to|of|in|for|with|that|this|you|we|it|on|as|be|at|by|from|or)\b",
    re.I,
)


def log(msg):
    HOME.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, file=sys.stderr, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def die(msg, code=5):
    log(f"ERROR: {msg}")
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    raise SystemExit(code)


# ---------------------------------------------------------------- dependencies
def ensure_deps():
    try:
        import playwright  # noqa: F401
    except ImportError:
        log("playwright missing -> installing with pip")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])


def launch(pw, headed, channel=None):
    kw = {
        "user_data_dir": str(PROFILE),
        "headless": not headed,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if channel:
        kw["channel"] = channel
    return pw.chromium.launch_persistent_context(**kw)


def open_browser(pw, headed):
    PROFILE.mkdir(parents=True, exist_ok=True)
    try:
        return launch(pw, headed, "chrome")
    except Exception as exc:
        log(f"system chrome unavailable ({type(exc).__name__}), using bundled chromium")
    try:
        return launch(pw, headed)
    except Exception:
        log("browser missing -> playwright install chromium")
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        return launch(pw, headed)


# ---------------------------------------------------------------- page helpers
def is_logged_in(page):
    page.goto(APP, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    return "auth.heygen.com" not in page.url and "/login" not in page.url


def has_challenge(page):
    try:
        if page.locator("iframe[src*='challenges.cloudflare.com']").count():
            return True
        body = page.locator("body").inner_text(timeout=2000)
        return bool(CHALLENGE_RE.search(body))
    except Exception:
        return False


def wait_for_human(page, minutes=5):
    log("anti-bot check: click the checkbox in the window, waiting...")
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        if not has_challenge(page):
            log("verification passed")
            return True
        page.wait_for_timeout(2000)
    return False


def dump_debug(page, tag):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        (DEBUG_DIR / f"{tag}-{stamp}.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(DEBUG_DIR / f"{tag}-{stamp}.png"), full_page=True)
        log(f"debug written to {DEBUG_DIR}")
    except Exception as exc:
        log(f"debug failed: {exc}")


def fill_text(page, text):
    for sel in ("textarea", "[contenteditable='true']", "div[role='textbox']"):
        loc = page.locator(sel).first
        try:
            if not loc.count():
                continue
            loc.click(timeout=5000)
            page.keyboard.press("ControlOrMeta+A")
            page.keyboard.press("Delete")
            page.keyboard.insert_text(text)
            log(f"text injected into {sel} ({len(text)} chars)")
            return sel
        except Exception:
            continue
    raise RuntimeError("text field not found")


def read_voice_cards(page):
    return list(dict.fromkeys(page.evaluate(VOICE_CARD_JS)))


def pick_voice(page, voice):
    """Open the studio voice picker, find the voice, select it."""
    if not voice:
        return
    page.locator("[data-pacific-component='VoiceComposerBox'] div[role=button]").first.click(timeout=10000)
    menu = page.get_by_role("menu")
    menu.wait_for(state="visible", timeout=15000)
    menu.get_by_text(MINE_RE).first.click(timeout=8000)
    page.wait_for_timeout(2500)

    if not any(voice.lower() in name.lower() for name in read_voice_cards(page)):
        page.get_by_text(LIBRARY_RE).first.click(timeout=8000)
        page.wait_for_timeout(1500)
        page.get_by_placeholder(SEARCH_VOICE_RE).fill(voice)
        page.wait_for_timeout(2500)

    names = read_voice_cards(page)
    match = next((name for name in names if voice.lower() in name.lower()), None)
    if not match:
        raise RuntimeError(f"voice '{voice}' not found ({', '.join(names[:5]) or 'empty list'})")
    page.locator(f'div[title="{match}"]').first.click(timeout=8000)
    page.wait_for_timeout(1200)
    try:
        page.get_by_role("button", name=SELECT_VOICE_RE).first.click(timeout=3000)
    except Exception:
        pass  # depending on the build, clicking the row applies the voice directly
    page.wait_for_timeout(1500)
    active = page.locator("[data-pacific-component='VoiceComposerBox'] div[role=button]").first.get_attribute(
        "aria-label"
    )
    log(f"voice selected: {match} -> active: {active}")
    return active


def click_generate(page, button):
    pattern = re.compile(re.escape(button), re.I) if button else GENERATE_RE
    composer = page.locator("[data-pacific-component='VoiceComposerBox']")
    loc = composer.get_by_role("button", name=pattern) if composer.count() else page.get_by_role("button", name=pattern)
    if not loc.count():
        loc = page.get_by_role("button", name=pattern)
    if not loc.count():
        loc = page.locator("button", has_text=pattern)
    if not loc.count():
        raise RuntimeError("generate button not found")
    loc.first.click(timeout=10000)
    log("generation started")


# ---------------------------------------------------------------- audio capture
def _audio_urls(obj):
    if isinstance(obj, str):
        if obj.split("?")[0].lower().endswith(AUDIO_EXT):
            yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from _audio_urls(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _audio_urls(value)


class AudioCatcher:
    def __init__(self):
        self.items = []  # (ts, size, url, body|None)
        self.streams = []
        self.since = 0.0

    def attach(self, page):
        page.on("response", self._on_response)

    def mark(self):
        """Drop anything loaded before the click: voice-list preview samples."""
        self.since = time.time()
        self.items.clear()
        self.streams.clear()

    def _on_response(self, response):
        try:
            ctype = (response.headers or {}).get("content-type", "")
            url = response.url
            ts = time.time()
            if "text_to_speech.stream" in url or "ndjson" in ctype:
                self.streams.append(response)
                log(f"TTS stream detected: {url[:160]}")
                return
            if "audio/" in ctype or url.split("?")[0].lower().endswith(AUDIO_EXT):
                body = response.body()
                if len(body) > 2000:
                    self.items.append((ts, len(body), url, body))
                    log(f"audio captured: {len(body)} bytes ({url[:160]})")
                    return
            if "json" in ctype:
                found = list(_audio_urls(response.json()))
                self.items.extend((ts, 0, url, None) for url in found)
                if found and ts >= self.since:
                    log(f"{len(found)} audio url(s) in a json response")
        except Exception:
            pass


def _ndjson_audio(body):
    """text_to_speech.stream -> (full mp3, fallback url)."""
    chunks, url = [], None
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("audio_url"):
            url = obj["audio_url"]
        data = obj.get("audio_bytes")
        if data:
            try:
                chunks.append((int(obj.get("sequence_number") or 0), base64.b64decode(data)))
            except Exception:
                continue
    if not chunks:
        return None, url
    chunks.sort()
    return b"".join(chunk for _, chunk in chunks), url


def save_audio(page, catcher, min_seconds=0.0):
    """First audio captured after the click, long enough for the requested text."""
    for response in catcher.streams:
        try:
            body = response.body()  # blocks until the stream ends
        except Exception:
            continue
        data, url = _ndjson_audio(body)
        if b"Daily rate limit exceeded" in body:
            die("HeyGen daily rate limit exceeded (code 400140): retry tomorrow or use another account", 4)
        if not data and not url:
            log(f"stream body: {body[:300]!r}")
        sources = [(data, "raw.mp3")] if data and len(data) > 2000 else []
        if url:
            sources.append((None, url))
        for payload, source in sources:
            if payload is None:
                try:
                    got = page.request.get(source)
                    if not got.ok:
                        continue
                    payload = got.body()
                except Exception:
                    continue
            if len(payload) < 2000:
                continue
            raw = HOME / ("raw" + (Path(source.split("?")[0]).suffix if source.startswith("http") else ".mp3"))
            raw.write_bytes(payload)
            seconds = duration_of(raw)
            if min_seconds and (seconds or 0) < min_seconds:
                log(f"stream skipped ({seconds}s, need {min_seconds:.0f}s)")
                continue
            return raw

    candidates = [(url, body) for ts, _, url, body in catcher.items if ts >= catcher.since]
    for src in page.eval_on_selector_all(
        "audio", "els => els.map(e => e.currentSrc || e.src).filter(Boolean)"
    ):
        if src.startswith("blob:"):
            log("blob audio: not supported")
            continue
        candidates.append((src, None))
    for url, body in sorted(candidates, key=lambda item: len(item[1] or b""), reverse=True):
        if body is None:
            try:
                response = page.request.get(url)
                if not response.ok:
                    continue
                body = response.body()
            except Exception:
                continue
        if len(body) < 2000:
            continue
        raw = HOME / ("raw" + (Path(url.split("?")[0]).suffix or ".mp3"))
        raw.write_bytes(body)
        seconds = duration_of(raw)
        if min_seconds and (seconds or 0) < min_seconds:
            log(f"clip skipped ({seconds}s, need {min_seconds:.0f}s)")
            continue
        return raw
    return None


# ---------------------------------------------------------------- audio post
def to_mp3(raw, out):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        die(
            "ffmpeg not found: winget install Gyan.FFmpeg | brew install ffmpeg | sudo apt install ffmpeg",
            5,
        )
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(raw), "-vn", "-ac", "1", "-b:a", "192k", str(out)],
        check=True,
    )
    return True


def duration_of(path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
    )
    try:
        return round(float(result.stdout.strip()), 2)
    except ValueError:
        return None


def mean_volume(path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)
    return float(match.group(1)) if match else None


def concat_audio(parts, out):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        die("ffmpeg is required to concatenate chunks")
    listing = out.with_suffix(".concat.txt")
    listing.write_text(
        "".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8"
    )
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)],
        check=True,
    )
    listing.unlink(missing_ok=True)


def chunk_text(text, limit):
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    chunks, buffer = [], ""
    for sentence in sentences:
        while len(sentence) > limit:
            head, sentence = sentence[:limit], sentence[limit:]
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.append(head)
        if len(buffer) + len(sentence) + 1 <= limit:
            buffer = f"{buffer} {sentence}".strip()
        else:
            if buffer:
                chunks.append(buffer)
            buffer = sentence
    if buffer:
        chunks.append(buffer)
    return chunks


def detect_lang(text):
    """French when French markers win or tie; the UI and the user are French-first."""
    fr = len(FRENCH_RE.findall(text))
    en = len(ENGLISH_RE.findall(text))
    return "fr" if fr >= en else "en"


# ---------------------------------------------------------------- commands
def cmd_doctor(args):
    report = {
        "python": sys.version.split()[0],
        "playwright": False,
        "browser": None,
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "profile": PROFILE.exists(),
        "home": str(HOME),
    }
    try:
        import playwright  # noqa: F401

        report["playwright"] = True
    except ImportError:
        pass
    if report["playwright"]:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                report["browser"] = browser.version
                browser.close()
        except Exception as exc:
            report["browser"] = f"missing ({type(exc).__name__})"
    print(json.dumps(report, indent=2, ensure_ascii=False))
    ok = report["playwright"] and report["browser"] and not str(report["browser"]).startswith("missing")
    return 0 if ok else 2


def cmd_login(args):
    ensure_deps()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        context = open_browser(pw, headed=True)
        page = context.new_page()
        page.goto(APP, wait_until="domcontentloaded")
        log("log in in the window. Waiting up to 10 minutes.")
        deadline = time.time() + 600
        while time.time() < deadline:
            if "auth.heygen.com" not in page.url and "/login" not in page.url:
                page.wait_for_timeout(3000)
                if "auth.heygen.com" not in page.url:
                    log("session saved")
                    print(json.dumps({"ok": True, "profile": str(PROFILE)}))
                    context.close()
                    return 0
            page.wait_for_timeout(2000)
        context.close()
        die("login timed out", 2)


def cmd_voices(args):
    ensure_deps()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        context = open_browser(pw, headed=args.headed)
        page = context.new_page()
        if not is_logged_in(page):
            context.close()
            die("not logged in: run `heygen_tts.py login` first", 2)
        page.goto(VOICES_PAGE, wait_until="domcontentloaded")
        page.wait_for_timeout(7000)
        if has_challenge(page) and not args.headed:
            context.close()
            log("anti-bot detected -> relaunching headed")
            context = open_browser(pw, headed=True)
            page = context.new_page()
            page.goto(VOICES_PAGE, wait_until="domcontentloaded")
            if not wait_for_human(page):
                context.close()
                die("anti-bot verification not passed", 3)
        mine, library = [], []
        try:
            page.get_by_text(MINE_RE).first.click(timeout=8000)
            page.wait_for_timeout(2500)
            mine = read_voice_cards(page)
            page.get_by_text(LIBRARY_RE).first.click(timeout=8000)
            page.wait_for_timeout(3000)
            library = read_voice_cards(page)
        except Exception as exc:
            dump_debug(page, "voices")
            context.close()
            die(f"voice list unreadable: {exc}", 4)
        context.close()

    VOICES_FILE.write_text(
        json.dumps({"mine": mine, "library": library, "defaults": DEFAULT_VOICES}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "mine": mine,
                "library": library[: args.limit],
                "library_total": len(library),
                "defaults": DEFAULT_VOICES,
                "file": str(VOICES_FILE),
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_clone(args):
    """Upload the sample; naming and consent happen in the window."""
    audio = Path(args.audio).resolve()
    if not audio.exists():
        die(f"sample not found: {audio}")
    ensure_deps()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        context = open_browser(pw, headed=True)
        page = context.new_page()
        if not is_logged_in(page):
            context.close()
            die("not logged in: run `heygen_tts.py login` first", 2)
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        if has_challenge(page) and not wait_for_human(page):
            context.close()
            die("anti-bot verification not passed", 3)

        try:
            page.locator("button:visible", has_text=CREATE_VOICE_RE).first.click(timeout=15000)
            page.wait_for_timeout(4000)
            page.get_by_text(UPLOAD_AUDIO_RE).first.click(timeout=10000)
            page.wait_for_timeout(3000)
            accept = page.locator("input[type=file]").first.get_attribute("accept")
            if args.dry_run:
                print(json.dumps({"ok": True, "dry_run": True, "file_input": accept}, ensure_ascii=False))
                context.close()
                return 0
            page.locator("input[type=file]").first.set_input_files(str(audio))
        except Exception as exc:
            dump_debug(page, "clone")
            context.close()
            die(f"unexpected clone wizard: {exc}", 4)

        log(f"sample uploaded ({audio.name}). Finish in the window: name, consent, then close it.")
        deadline = time.time() + args.wait
        try:
            while time.time() < deadline and not page.is_closed():
                page.wait_for_timeout(2000)
        except Exception:
            pass
        print(
            json.dumps(
                {
                    "ok": True,
                    "uploaded": str(audio),
                    "note": "run `voices` once training finishes to confirm the clone",
                },
                ensure_ascii=False,
            )
        )
        return 0


def generate_once(text, out, args):
    from playwright.sync_api import sync_playwright

    catcher = AudioCatcher()
    with sync_playwright() as pw:
        context = open_browser(pw, headed=args.headed)
        page = context.new_page()
        catcher.attach(page)

        if not args.no_auth and not is_logged_in(page):
            context.close()
            die("not logged in: run `heygen_tts.py login` first", 2)

        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        if has_challenge(page):
            if not args.headed:
                context.close()
                log("anti-bot detected -> relaunching headed")
                context = open_browser(pw, headed=True)
                page = context.new_page()
                catcher.attach(page)
                page.goto(args.url, wait_until="domcontentloaded")
            if not wait_for_human(page):
                dump_debug(page, "challenge")
                context.close()
                die("anti-bot verification not passed", 3)

        try:
            fill_text(page, text)
            pick_voice(page, args.voice)
            catcher.mark()  # anything arriving now comes from the generation
            click_generate(page, args.button)
        except Exception as exc:
            dump_debug(page, "generate")
            context.close()
            die(f"unexpected UI: {exc}", 4)

        expected = len(text) / 15.0
        min_seconds = max(1.0, expected * 0.4)
        deadline = time.time() + args.timeout
        raw = None
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            raw = save_audio(page, catcher, min_seconds)
            if raw:
                break
        if not raw:
            dump_debug(page, "no-audio")
            context.close()
            die(f"no audio captured in {args.timeout}s (rerun with --debug)", 4)

        if args.debug:
            dump_debug(page, "success")
        context.close()

    to_mp3(raw, out)
    return out


def cmd_tts(args):
    text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else args.text
    if not text or not text.strip():
        die("empty text")
    lang = args.lang if args.lang != "auto" else detect_lang(text)
    if not args.voice and not args.no_voice:
        args.voice = DEFAULT_VOICES[lang]
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    ensure_deps()

    chunks = chunk_text(text, args.chunk_chars) if args.chunk else [text]
    if len(chunks) == 1:
        generate_once(text, out, args)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            parts = []
            for index, chunk in enumerate(chunks, 1):
                log(f"chunk {index}/{len(chunks)} ({len(chunk)} chars)")
                part = Path(tmp) / f"part-{index:03d}.mp3"
                generate_once(chunk, part, args)
                parts.append(part)
            concat_audio(parts, out)

    db = mean_volume(out)
    duration = duration_of(out)
    expected = round(len(text) / 15.0, 1)
    too_short = duration is not None and duration < expected * 0.4
    result = {
        "ok": not too_short,
        "path": str(out),
        "duration": duration,
        "expected": expected,
        "bytes": out.stat().st_size,
        "mean_db": db,
        "silent": db is not None and db < -45,
        "chunks": len(chunks),
        "voice": args.voice,
        "lang": lang,
        "credits": 0,
    }
    print(json.dumps(result, ensure_ascii=False))
    if too_short:
        log(f"audio too short: {duration}s for {len(text)} chars (expected ~{expected}s)")
        return 4
    return 0


def main():
    parser = argparse.ArgumentParser(description="HeyGen TTS without video credits")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check python, playwright, browser, ffmpeg")
    sub.add_parser("login", help="one-time login, persistent profile")
    p_voices = sub.add_parser("voices", help="list My voices + the HeyGen library")
    p_voices.add_argument("--headed", action="store_true")
    p_voices.add_argument("--limit", type=int, default=40, help="how many library voices to print")

    p_clone = sub.add_parser("clone", help="upload a sample to clone your voice")
    p_clone.add_argument("audio")
    p_clone.add_argument("--url", default=VOICES_PAGE)
    p_clone.add_argument("--wait", type=int, default=900, help="seconds before the window closes")
    p_clone.add_argument("--dry-run", action="store_true", help="check the wizard without uploading")

    p_tts = sub.add_parser("tts", help="text -> mp3")
    p_tts.add_argument("--text")
    p_tts.add_argument("--text-file")
    p_tts.add_argument("--voice", default=None)
    p_tts.add_argument("--lang", choices=["auto", "fr", "en"], default="auto")
    p_tts.add_argument("--no-voice", action="store_true", help="keep the studio's active voice")
    p_tts.add_argument("--out", required=True)
    p_tts.add_argument("--url", default=VOICE_APP)
    p_tts.add_argument("--button", default=None)
    p_tts.add_argument("--timeout", type=int, default=300)
    p_tts.add_argument("--chunk", action="store_true", help="split long text into chunks")
    p_tts.add_argument("--chunk-chars", type=int, default=850)
    p_tts.add_argument("--headed", action="store_true")
    p_tts.add_argument("--debug", action="store_true")
    p_tts.add_argument("--no-auth", action="store_true", help="local testing only")

    args = parser.parse_args()
    if args.command == "tts" and not (args.text or args.text_file):
        parser.error("tts requires --text or --text-file")
    return {
        "doctor": cmd_doctor,
        "login": cmd_login,
        "voices": cmd_voices,
        "clone": cmd_clone,
        "tts": cmd_tts,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

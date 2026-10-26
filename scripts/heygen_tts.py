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
GENERATE_RE = re.compile(r"generate|g[eé]n[eé]rer|create speech|cr[eé]er", re.I)
VOICE_CARD_JS = """() => {
    const cards = [...document.querySelectorAll('button[data-atlas-id="voice-card-play-btn"]')]
        .map(b => (b.getAttribute('aria-label') || '').replace(/^Play /, ''));
    const rows = [...document.querySelectorAll('[data-atlas-id="voice-row"] [title]')]
        .map(e => e.getAttribute('title'));
    return [...cards, ...rows].filter(Boolean);
}"""


def log(msg):
    HOME.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, file=sys.stderr, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def die(msg, code=5):
    log(f"ERREUR: {msg}")
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    raise SystemExit(code)


# ---------------------------------------------------------------- dependencies
def ensure_deps():
    try:
        import playwright  # noqa: F401
    except ImportError:
        log("playwright absent -> installation (pip)")
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
        log(f"chrome systeme indisponible ({type(exc).__name__}), chromium embarque")
    try:
        return launch(pw, headed)
    except Exception:
        log("navigateur absent -> playwright install chromium")
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
    log("verification anti-bot : clique la case dans la fenetre, j'attends…")
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        if not has_challenge(page):
            log("verification passee")
            return True
        page.wait_for_timeout(2000)
    return False


def dump_debug(page, tag):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    try:
        (DEBUG_DIR / f"{tag}-{stamp}.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(DEBUG_DIR / f"{tag}-{stamp}.png"), full_page=True)
        log(f"debug ecrit dans {DEBUG_DIR}")
    except Exception as exc:
        log(f"debug impossible: {exc}")


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
            log(f"texte injecte dans {sel} ({len(text)} caracteres)")
            return sel
        except Exception:
            continue
    raise RuntimeError("champ de texte introuvable")


def read_voice_cards(page):
    return list(dict.fromkeys(page.evaluate(VOICE_CARD_JS)))


def pick_voice(page, voice):
    """Ouvre le selecteur du studio, cherche la voix, la selectionne."""
    if not voice:
        return
    page.locator("[data-pacific-component='VoiceComposerBox'] div[role=button]").first.click(timeout=10000)
    menu = page.get_by_role("menu")
    menu.wait_for(state="visible", timeout=15000)
    menu.get_by_text("Mes voix", exact=True).click(timeout=8000)
    page.wait_for_timeout(2500)

    if not any(voice.lower() in name.lower() for name in read_voice_cards(page)):
        page.get_by_text("Bibliothèque HeyGen", exact=False).first.click(timeout=8000)
        page.wait_for_timeout(1500)
        page.get_by_placeholder("Rechercher des voix...").fill(voice)
        page.wait_for_timeout(2500)

    names = read_voice_cards(page)
    match = next((name for name in names if voice.lower() in name.lower()), None)
    if not match:
        raise RuntimeError(f"voix '{voice}' introuvable ({', '.join(names[:5]) or 'liste vide'})")
    page.locator(f'div[title="{match}"]').first.click(timeout=8000)
    page.wait_for_timeout(1200)
    try:
        page.get_by_role("button", name="Sélectionner une voix").first.click(timeout=3000)
    except Exception:
        pass  # selon la version, la ligne applique la voix directement
    page.wait_for_timeout(1500)
    active = page.locator("[data-pacific-component='VoiceComposerBox'] div[role=button]").first.get_attribute(
        "aria-label"
    )
    log(f"voix selectionnee: {match} -> active: {active}")
    return active


def click_generate(page, button):
    pattern = re.compile(re.escape(button), re.I) if button else GENERATE_RE
    loc = page.get_by_role("button", name=pattern)
    if not loc.count():
        loc = page.locator("button", has_text=pattern)
    if not loc.count():
        raise RuntimeError("bouton de generation introuvable")
    loc.first.click(timeout=10000)
    log("generation lancee")


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
        """Ignore ce qui a ete charge avant le clic : echantillons de la liste des voix."""
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
                log("flux TTS detecte")
                return
            if "audio/" in ctype or url.split("?")[0].lower().endswith(AUDIO_EXT):
                body = response.body()
                if len(body) > 2000:
                    self.items.append((ts, len(body), url, body))
                    log(f"audio capture: {len(body)} octets")
                    return
            if "json" in ctype:
                found = list(_audio_urls(response.json()))
                self.items.extend((ts, 0, url, None) for url in found)
                if found and ts >= self.since:
                    log(f"{len(found)} url(s) audio dans une reponse json")
        except Exception:
            pass


def _ndjson_audio(body):
    """Flux text_to_speech.stream -> (mp3 complet, url de secours)."""
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
    """Premier audio capture apres le clic et assez long pour le texte demande."""
    for response in catcher.streams:
        try:
            body = response.body()  # bloque jusqu'a la fin du flux
        except Exception:
            continue
        data, url = _ndjson_audio(body)
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
                log(f"flux ignore ({seconds}s, il en faut {min_seconds:.0f}s)")
                continue
            return raw

    candidates = [(url, body) for ts, _, url, body in catcher.items if ts >= catcher.since]
    for src in page.eval_on_selector_all(
        "audio", "els => els.map(e => e.currentSrc || e.src).filter(Boolean)"
    ):
        if src.startswith("blob:"):
            log("audio en blob: non supporte en v1")
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
            log(f"extrait ignore ({seconds}s, il en faut {min_seconds:.0f}s)")
            continue
        return raw
    return None


# ---------------------------------------------------------------- audio post
def to_mp3(raw, out):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        die(
            "ffmpeg introuvable : winget install Gyan.FFmpeg | brew install ffmpeg | sudo apt install ffmpeg",
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
        die("ffmpeg requis pour concatener les tranches")
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
            report["browser"] = f"absent ({type(exc).__name__})"
    print(json.dumps(report, indent=2, ensure_ascii=False))
    ok = report["playwright"] and report["browser"] and not str(report["browser"]).startswith("absent")
    return 0 if ok else 2


def cmd_login(args):
    ensure_deps()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        context = open_browser(pw, headed=True)
        page = context.new_page()
        page.goto(APP, wait_until="domcontentloaded")
        log("connecte-toi dans la fenetre. J'attends jusqu'a 10 minutes.")
        deadline = time.time() + 600
        while time.time() < deadline:
            if "auth.heygen.com" not in page.url and "/login" not in page.url:
                page.wait_for_timeout(3000)
                if "auth.heygen.com" not in page.url:
                    log("session enregistree")
                    print(json.dumps({"ok": True, "profile": str(PROFILE)}))
                    context.close()
                    return 0
            page.wait_for_timeout(2000)
        context.close()
        die("delai de connexion depasse", 2)


def cmd_voices(args):
    ensure_deps()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        context = open_browser(pw, headed=args.headed)
        page = context.new_page()
        if not is_logged_in(page):
            context.close()
            die("non connecte : lance d'abord `heygen_tts.py login`", 2)
        page.goto(VOICES_PAGE, wait_until="domcontentloaded")
        page.wait_for_timeout(7000)
        if has_challenge(page) and not args.headed:
            context.close()
            log("anti-bot detecte -> relance visible")
            context = open_browser(pw, headed=True)
            page = context.new_page()
            page.goto(VOICES_PAGE, wait_until="domcontentloaded")
            if not wait_for_human(page):
                context.close()
                die("verification anti-bot non passee", 3)
        mine, library = [], []
        try:
            page.get_by_text("Mes voix", exact=True).first.click(timeout=8000)
            page.wait_for_timeout(2500)
            mine = read_voice_cards(page)
            page.get_by_text("Bibliothèque HeyGen", exact=False).first.click(timeout=8000)
            page.wait_for_timeout(3000)
            library = read_voice_cards(page)
        except Exception as exc:
            dump_debug(page, "voices")
            context.close()
            die(f"liste des voix illisible: {exc}", 4)
        context.close()

    VOICES_FILE.write_text(
        json.dumps({"mine": mine, "library": library}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": True,
                "mine": mine,
                "library": library[: args.limit],
                "library_total": len(library),
                "file": str(VOICES_FILE),
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_clone(args):
    """Televerse l'echantillon; nom et consentement se font dans la fenetre."""
    audio = Path(args.audio).resolve()
    if not audio.exists():
        die(f"echantillon introuvable: {audio}")
    ensure_deps()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        context = open_browser(pw, headed=True)
        page = context.new_page()
        if not is_logged_in(page):
            context.close()
            die("non connecte : lance d'abord `heygen_tts.py login`", 2)
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)
        if has_challenge(page) and not wait_for_human(page):
            context.close()
            die("verification anti-bot non passee", 3)

        try:
            page.locator("button:visible", has_text="Créez votre voix HeyGen").first.click(timeout=15000)
            page.wait_for_timeout(4000)
            page.get_by_text(re.compile(r"Téléverser de l.audio")).first.click(timeout=10000)
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
            die(f"wizard de clonage inattendu: {exc}", 4)

        log(f"echantillon envoye ({audio.name}). Termine dans la fenetre : nom, consentement, puis ferme-la.")
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
                    "note": "lance `voices` une fois l'entrainement termine pour verifier le clone",
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
            die("non connecte : lance d'abord `heygen_tts.py login`", 2)

        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        if has_challenge(page):
            if not args.headed:
                context.close()
                log("anti-bot detecte -> relance en mode visible")
                context = open_browser(pw, headed=True)
                page = context.new_page()
                catcher.attach(page)
                page.goto(args.url, wait_until="domcontentloaded")
            if not wait_for_human(page):
                dump_debug(page, "challenge")
                context.close()
                die("verification anti-bot non passee", 3)

        try:
            fill_text(page, text)
            pick_voice(page, args.voice)
            catcher.mark()  # tout ce qui arrive maintenant vient de la generation
            click_generate(page, args.button)
        except Exception as exc:
            dump_debug(page, "generate")
            context.close()
            die(f"interface inattendue: {exc}", 4)

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
            die(f"aucun audio capture en {args.timeout}s (relance avec --debug)", 4)

        if args.debug:
            dump_debug(page, "success")
        context.close()

    to_mp3(raw, out)
    return out


def cmd_tts(args):
    text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else args.text
    if not text or not text.strip():
        die("texte vide")
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
                log(f"tranche {index}/{len(chunks)} ({len(chunk)} caracteres)")
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
        "credits": 0,
    }
    print(json.dumps(result, ensure_ascii=False))
    if too_short:
        log(f"audio trop court: {duration}s pour {len(text)} caracteres (attendu ~{expected}s)")
        return 4
    return 0


def main():
    parser = argparse.ArgumentParser(description="HeyGen TTS sans credits video")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="verifie python, playwright, navigateur, ffmpeg")
    sub.add_parser("login", help="connexion unique, profil persistant")
    p_voices = sub.add_parser("voices", help="liste Mes voix + la bibliotheque HeyGen")
    p_voices.add_argument("--headed", action="store_true")
    p_voices.add_argument("--limit", type=int, default=40, help="nb de voix bibliotheque affichees")

    p_clone = sub.add_parser("clone", help="televerse un echantillon pour cloner ta voix")
    p_clone.add_argument("audio")
    p_clone.add_argument("--url", default=VOICES_PAGE)
    p_clone.add_argument("--wait", type=int, default=900, help="secondes avant fermeture auto")
    p_clone.add_argument("--dry-run", action="store_true", help="verifie le wizard sans envoyer le fichier")

    p_tts = sub.add_parser("tts", help="texte -> mp3")
    p_tts.add_argument("--text")
    p_tts.add_argument("--text-file")
    p_tts.add_argument("--voice", default=None)
    p_tts.add_argument("--out", required=True)
    p_tts.add_argument("--url", default=VOICE_APP)
    p_tts.add_argument("--button", default=None)
    p_tts.add_argument("--timeout", type=int, default=300)
    p_tts.add_argument("--chunk", action="store_true", help="decoupe si l'apercu est limite")
    p_tts.add_argument("--chunk-chars", type=int, default=850)
    p_tts.add_argument("--headed", action="store_true")
    p_tts.add_argument("--debug", action="store_true")
    p_tts.add_argument("--no-auth", action="store_true", help="test local uniquement")

    args = parser.parse_args()
    if args.command == "tts" and not (args.text or args.text_file):
        parser.error("tts demande --text ou --text-file")
    return {
        "doctor": cmd_doctor,
        "login": cmd_login,
        "voices": cmd_voices,
        "clone": cmd_clone,
        "tts": cmd_tts,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

---
name: heygen-tts
description: Use when the user asks for a voiceover, narration, text-to-speech, "read this text", dubbing a script, or wants a cloned voice without paying per character. Also use when ElevenLabs credits are exhausted, when a text must be read aloud in a specific voice, or when the user asks for "free ElevenLabs". Drives the HeyGen voice studio in the background and never spends video credits.
---

# HeyGen TTS — cloned voice, 0 credits

## Principle

HeyGen bills credits for the **avatar video render** (Avatar IV: 20 credits/minute), not for speech synthesis. The audio preview is free on every plan. This skill drives the voice studio, captures the generated audio straight from the network, and **never clicks** Generate or Render Scene.

Result: a clean MP3, no screen recording, no quality loss, no credit spent.

## How the audio is captured (verified 2026-10-26)

The studio does not expose an MP3: it **streams NDJSON** from `api2.heygen.com/v2/online/creative_studio/text_to_speech.stream`. Each line carries an MP3 fragment in base64 (`audio_bytes`, `sequence_number`, `duration`); the last one carries the full file URL. The script reads that stream, reassembles the fragments in order and checks the duration.

It also ignores anything loaded **before** the click (voice-list preview samples) and rejects audio too short for the requested text (`expected` = length / 15 s, threshold 40%). That is what prevents delivering a 2-second beep instead of the narration.

## Scope

**Does:** one-time login, voice switching (HeyGen library and clones), sample upload for cloning, text to MP3, automatic chunking, quality checks.

**Does not:** create the HeyGen account, finish the clone for the user (name, consent and training happen in the window), bypass a paywall or captcha, call the HeyGen API (paid), run a local TTS engine.

## First install — checklist

1. `python scripts/heygen_tts.py doctor` → must show `playwright: true` and a browser version. If Playwright is missing, the script installs it; do not do it by hand.
2. `python scripts/heygen_tts.py login` → visible browser, the user logs in. The persistent profile is kept, no login afterwards.
3. `python scripts/heygen_tts.py clone sample.mp3` → opens the window, picks "Upload audio" and sends the sample (10 s minimum, MP3/WAV/MP4/WebM). **The user finishes in the window**: name, consent, training. The clone then appears in "My voices" and **is never redone**. Check with `voices` → `mine`.
4. `python scripts/heygen_tts.py tts --text "hello" --out test.mp3 --debug` → first real run. `--debug` is recommended: it writes a screenshot and the HTML to `debug/` if the UI changes.

## Commands

| Command | Effect |
|---|---|
| `doctor` | Checks Python, Playwright, browser, ffmpeg |
| `login` | One-time login, persistent profile |
| `voices` | Lists `mine` (clones) + `library` (HeyGen library) + `defaults` |
| `clone AUDIO` | Uploads a sample; name + consent in the window |
| `clone AUDIO --dry-run` | Checks the wizard without uploading |
| `tts --text "..." --out audio.mp3` | Text → MP3 with the default voice for the text language |
| `tts --text-file script.txt --out audio.mp3` | Same from a file |
| `tts ... --voice NAME` | Force a specific voice |
| `tts ... --chunk` | Splits into ~850-character chunks and concatenates |

Options: `--headed` (visible browser), `--debug` (HTML + screenshot), `--timeout 300`, `--url` / `--button` (if the UI changes), `--chunk-chars 850`, `--limit 40` (voices), `--wait 900` (clone), `--lang fr|en` (default voice), `--no-voice` (keep the studio's active voice).

## Default voices (2026-10-27)

| Language | Voice |
|---|---|
| French | Martin Dupont Aimable |
| English | Roderic - Authoritative & Refined |

The language is detected from the text (French wins ties). `--lang fr` / `--lang en` forces it, `--voice NAME` overrides the voice, and `--no-voice` keeps whatever voice is active in the studio.

## Switching voices (verified 2026-10-27)

`voices` returns `mine` (cloned voices), `library` (the HeyGen voices visible on the account) and `defaults` (the per-language defaults). To use one:

```
tts --text-file script.txt --voice "Annie" --out audio.mp3
```

The search is partial: "Annie" finds "Annie - Lifelike". The script opens the studio picker, searches the library, clicks the row and **verifies the active voice** in the studio bar. If the name does not exist, it fails with the first results instead of generating with the default voice.

For your own voice: `clone sample.mp3`, then `--voice "Clone name"` like any other voice.

## Daily procedure

1. Make sure the text exists and is not empty. Prefer `--text-file` to avoid quoting problems.
2. Run `tts` in the **background** (`background=true`): a generation takes 30 s to several minutes.
3. Read the last output line: JSON `{"ok": true, "path": ..., "duration": ..., "mean_db": ...}`.
4. Check **before delivering**:
   - `ok` is `true`
   - `silent` is `false` (otherwise the file is mute, do not deliver it)
   - `duration` matches the text (~15 characters per second)
   - `bytes` > 20,000
5. Report the path, the duration and `credits: 0`. Nothing else.

## Guardrails — non-negotiable

- **Never generate a video**: in the video editor, "Generate" / "Render Scene" costs 20 credits/minute. The "Generate" button of the **voice studio** produces the free audio preview — that is the only one the script clicks.
- **Never click "Render Scene"** unless the user explicitly asks.
- **Never save the project** to the HeyGen account.
- **Never try to bypass a paywall, a captcha or an account block.** If a wall appears: stop, report.
- One generation at a time: the Chromium profile is locked.

## Anti-bot

In headless mode, if a check appears, the script automatically relaunches the browser **visible** and waits for the user to tick the box (5 minutes max). That is intended: invisible when it passes, visible when a human is needed. Do not short-circuit that wait.

## Failures

| Symptom | Reaction |
|---|---|
| `not logged in` (code 2) | Run `login` |
| `anti-bot verification not passed` (code 3) | Rerun with `--headed`, let the user tick the box |
| `unexpected UI` (code 4) | Rerun with `--debug`, show the screenshot and HTML |
| `no audio captured` (code 4) | Same; try `--url` with the AI Studio editor |
| `silent: true` | Do not deliver; rerun with `--headed --debug` |
| `audio too short` | The script caught a preview sample; rerun, or `--chunk` if the text is very long |
| `Daily rate limit exceeded` (code 400140) | HeyGen's daily TTS limit is reached; retry after the daily reset or use the official API |
| Preview capped at 1 minute | Rerun with `--chunk` |
| Voice not found | `voices` for the exact names; the search is partial ("Annie" is enough) |
| `unexpected clone wizard` | `clone ... --dry-run` to isolate, then `--debug`; the UI changed |
| Clone missing from `mine` | Training is not finished, or consent was not confirmed in the window |

## Verifying the skill itself

`python scripts/selftest.py` spins up a fake local HeyGen and proves the network capture, the MP3 conversion, the silence detection and the chunk + concat path. Run it after any change to the script.

## Verified for real (2026-10-26 / 2026-10-27)

- Studio `creative_studio/voice`, 643-character text → **35.79 s, 860 KB, -17.2 dB, `silent: false`**, duration identical to the one announced by the stream.
- Voice switching: `--voice "Annie"` → "Little Annie" applied, 129 characters → **6.82 s, 165 KB, -17.7 dB**.
- `voices` → 29 voices in `library`, `mine` empty (no clone on that account).
- `clone ... --dry-run` → wizard reached, file input detected (MP3/WAV/MP4/WebM).
- The text field is a `contenteditable`, not a `textarea`.
- Default voices: French → "Martin Dupont Aimable", English → "Roderic - Authoritative & Refined" (both found through the library search).
- 2026-10-27: voice selection verified for both defaults; the account then hit `400140 Daily rate limit exceeded`, so the audio generation test must be rerun after the daily reset.

## Known limits

- Language detection is a heuristic (accents + common words); use `--lang fr|en` for short or mixed text.
- The HeyGen UI can change: on failure, rerun with `--debug` and look at `debug/`.
- Selectors are verified against the **French** UI; English labels are a best guess. Any other language needs `--debug` plus a selector fix.
- Cloning stops after the sample upload: name, consent and training are neither automated nor verified beyond that point.
- The UI uses typographic apostrophes ("Téléverser de l’audio"): selectors must use a regex, never a literal string.
- The studio modal and the `/avatar/voices` page do not use the same list component (`voice-row` vs `voice-card-play-btn`); `voices` and `pick_voice` handle both.
- The maximum free preview duration is unknown. A 643-character text passes (35.8 s); beyond that, use `--chunk`.
- The button showed "8 free minutes left": a quota exists. It is unknown whether it is consumed by the synthesis or by the video render — watch it.
- Official download is reserved for paid plans; this skill captures the preview. ToS / account-closure risk to state once, without moralizing.
- The HeyGen free plan has **no credits**: a credit counter on screen means a paid account.
- `credits: 0` is a design assertion (no billed button clicked), not a reading of the account balance.

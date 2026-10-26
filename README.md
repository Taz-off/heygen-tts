# heygen-tts

**Free, cloned voiceovers with zero video credits.** Drives the HeyGen voice studio with Playwright, captures the audio stream and writes an MP3. No screen recording, no quality loss, no credit spent.

Works with any agent that can run a shell command: Claude Code, Codex, Gemini CLI, OpenCode, Cursor, Windsurf, Copilot.

---

## Why it is free

HeyGen bills credits for the **avatar video render** — Avatar IV, 20 credits per minute — not for speech synthesis. The audio preview of the voice studio is free on every plan.

This project automates that preview: it types the text, clicks "Generate", grabs the audio from the network and converts it to MP3. **It never clicks Generate or Render Scene** in the video editor.

## What you get

| | |
|---|---|
| Cost | 0 video credits |
| Format | MP3 192 kbit/s, mono, 44.1 kHz |
| Voices | HeyGen library + your clones |
| Measured | 643 characters → 35.79 s, 860 KB, -17.2 dB |

## Requirements

- Python 3.9+
- Chrome installed — otherwise Playwright downloads Chromium
- `ffmpeg` and `ffprobe` on the `PATH`

Playwright installs itself on first run if it is missing.

## Install

### Claude Code

```bash
git clone https://github.com/Taz-off/heygen-tts.git ~/.claude/skills/heygen-tts
```

### Codex, Gemini CLI, OpenCode and other agents

These read the `~/.agents/skills/` directory:

```bash
git clone https://github.com/Taz-off/heygen-tts.git ~/.agents/skills/heygen-tts
```

Windows:

```powershell
git clone https://github.com/Taz-off/heygen-tts.git "$env:USERPROFILE\.agents\skills\heygen-tts"
```

### Cursor, Windsurf, Copilot

No skills directory: add this block to your `AGENTS.md` (or `.cursor/rules`).

```markdown
## Voiceover

For any voiceover, narration or TTS request, read `<path>/heygen-tts/SKILL.md`
then run:

python <path>/heygen-tts/scripts/heygen_tts.py tts --text-file <text.txt> --out <output.mp3>
```

### Without an agent

```bash
python scripts/heygen_tts.py --help
```

## First run

```bash
python scripts/heygen_tts.py doctor
python scripts/heygen_tts.py login
python scripts/heygen_tts.py clone my-voice.mp3
```

1. `doctor` checks Python, Playwright, the browser and ffmpeg.
2. `login` opens a window: log in to HeyGen by hand. The persistent profile is kept, you never do it again.
3. `clone` uploads a sample (10 s minimum, MP3/WAV/MP4/WebM) and opens the HeyGen wizard. You finish by hand: name, consent, training. Once.

## Usage

| Command | Effect |
|---|---|
| `doctor` | Checks the environment |
| `login` | One-time login, persistent profile |
| `voices` | Lists `mine` (clones) + `library` (HeyGen library) |
| `clone AUDIO` | Uploads a sample for cloning |
| `clone AUDIO --dry-run` | Checks the wizard without uploading |
| `tts --text "..." --out a.mp3` | Text → MP3 |
| `tts --text-file script.txt --out a.mp3` | From a file |
| `tts ... --voice "Annie"` | With a specific voice |
| `tts ... --chunk` | Splits into ~850-character chunks |

Options: `--headed` (visible browser), `--debug` (screenshot + HTML), `--timeout 300`, `--url`, `--button`, `--chunk-chars`.

### Example

```bash
python scripts/heygen_tts.py tts --text-file script.txt --voice "Annie" --out narration.mp3
```

Voice search is partial: "Annie" finds "Annie - Lifelike". If the name does not exist, the script fails with the list of available voices instead of falling back to the default one.

## Output

The last line is JSON:

```json
{"ok": true, "path": "narration.mp3", "duration": 35.79, "expected": 42.9, "bytes": 860203, "mean_db": -17.2, "silent": false, "chunks": 1, "voice": "Annie", "credits": 0}
```

| Field | Meaning |
|---|---|
| `ok` | Generation succeeded |
| `silent` | `true` = mute file, do not deliver |
| `mean_db` | Mean volume (silence threshold: -45 dB) |
| `duration` / `expected` | Actual vs estimated duration (15 characters/s) |
| `credits` | Design assertion: no billed button was clicked |

### Exit codes

| Code | Meaning |
|---|---|
| 2 | Not logged in → run `login` |
| 3 | Anti-bot check not passed |
| 4 | Unexpected UI or no audio captured |
| 5 | Generic error |

## How it works

The studio does not expose an MP3: it streams **NDJSON** from `api2.heygen.com/v2/online/creative_studio/text_to_speech.stream`. Each line carries an MP3 fragment in base64 (`audio_bytes`, `sequence_number`, `duration`); the last one carries the full file URL.

The script reassembles the fragments in order, ignores anything loaded **before** the click (voice-list preview samples) and rejects audio too short for the requested text. That is what prevents delivering a 2-second beep instead of the narration.

Details and agent procedure: [SKILL.md](SKILL.md).

## Limits and risks

- **ToS** — official download is reserved for paid plans; this project captures the preview. Use at your own risk.
- **Quota** — the button shows "X free minutes left". It is unknown whether it is consumed by the synthesis or by the video render.
- **Moving UI** — selectors can break. `--debug` writes a screenshot and the HTML to `~/.config/heygen-tts/debug/`.
- **UI language** — selectors are verified against the French UI; English labels are a best guess.
- **Free plan** — no HeyGen credits at all. A credit counter on screen means a paid account.
- **One generation at a time** — the Chromium profile is locked.
- **Cloning** — the script stops after the sample upload; the rest happens in the window.

## Self-test

```bash
python scripts/selftest.py
```

Spins up a fake local HeyGen (page + real audio) and checks the network capture, the MP3 conversion, the silence detection and the chunk + concat path — no account, no network.

## License

MIT — see [LICENSE](LICENSE).

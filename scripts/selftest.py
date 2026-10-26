#!/usr/bin/env python3
"""Self-test: fake HeyGen page -> audio interception -> mp3.

Runs entirely offline against a local HTTP server. Proves the network
capture, the download, the ffmpeg step and the chunk+concat path.
"""
import http.server
import io
import json
import math
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLI = HERE / "heygen_tts.py"


def make_wav(seconds=3, rate=16000):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(rate * seconds)
        )
        handle.writeframes(frames)
    return buffer.getvalue()


WAV = make_wav()
PAGE = b"""<!doctype html><meta charset=utf-8>
<textarea id="t"></textarea><button id="g">Generate</button><audio id="a"></audio>
<script>
document.getElementById('g').onclick = async () => {
  const r = await fetch('/audio.wav');
  document.getElementById('a').src = URL.createObjectURL(await r.blob());
};
</script>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/audio.wav":
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(WAV)))
            self.end_headers()
            self.wfile.write(WAV)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE)

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_case(port, name, text, extra, checks):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out = tmp_path / f"{name}.mp3"
        env = dict(os.environ, HEYGEN_TTS_HOME=str(tmp_path / "home"))
        proc = subprocess.run(
            [
                sys.executable, str(CLI), "tts",
                "--text", text,
                "--out", str(out),
                "--url", f"http://127.0.0.1:{port}",
                "--no-auth",
                "--timeout", "60",
                *extra,
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        if proc.returncode != 0:
            print(f"FAIL {name}: exit {proc.returncode}")
            print(proc.stderr)
            print(proc.stdout)
            return False
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        ok = True
        for label, passed in checks(out, result).items():
            print(("OK   " if passed else "FAIL ") + f"{name}: {label}")
            ok = ok and passed
        return ok


def main():
    port = free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    results = [
        run_case(
            port, "simple", "bonjour ceci est un test",
            [],
            lambda out, r: {
                "file exists": out.exists(),
                "size > 10ko": out.exists() and out.stat().st_size > 10000,
                "duration ~3s": r.get("duration") is not None and 2.5 <= r["duration"] <= 3.5,
                "audible": r.get("silent") is False,
                "1 chunk": r.get("chunks") == 1,
            },
        ),
        run_case(
            port, "chunked", "Premiere phrase du script. Deuxieme phrase du script.",
            ["--chunk", "--chunk-chars", "40"],
            lambda out, r: {
                "file exists": out.exists(),
                "duration ~6s": r.get("duration") is not None and 5.5 <= r["duration"] <= 6.5,
                "2 chunks": r.get("chunks") == 2,
                "audible": r.get("silent") is False,
            },
        ),
    ]
    server.shutdown()
    print("RESULT:", "PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

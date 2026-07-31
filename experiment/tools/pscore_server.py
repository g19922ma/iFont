"""知覚楽譜エディタのローカルサーバ。

ブラウザでカーブを描く → 「合成する」→ pscore_demo.py で音声+文字を合成 → その場で動画再生。
実行:  <venv>/bin/python experiment/tools/pscore_server.py   (VOICEVOX 起動下)
→ http://localhost:8765 を開く
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8765
WORK = os.environ.get("PSCORE_WORK") or os.path.join(tempfile.gettempdir(), "pscore_server")
os.makedirs(WORK, exist_ok=True)
PYTHON = sys.executable


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            body = open(os.path.join(HERE, "pscore_editor.html"), "rb").read()
            self._send(200, body, "text/html; charset=utf-8")
        elif self.path.split("?")[0] == "/video":
            mp4 = os.path.join(WORK, "latest.mp4")
            if os.path.exists(mp4):
                self._send(200, open(mp4, "rb").read(), "video/mp4")
            else:
                self._send(404, b"not yet")
        else:
            self._send(404, b"not found")

    def do_POST(self):
        if self.path != "/synth":
            self._send(404, b"not found")
            return
        n = int(self.headers.get("Content-Length", 0))
        score = self.rfile.read(n)
        score_path = os.path.join(WORK, "score.json")
        with open(score_path, "wb") as f:
            f.write(score)
        out = os.path.join(WORK, "latest.mp4")
        env = dict(os.environ, PSCORE_WORK=os.path.join(WORK, "render"))
        r = subprocess.run([PYTHON, os.path.join(HERE, "pscore_demo.py"), score_path, out],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            self._send(500, (r.stderr[-800:] or "synthesis failed").encode())
            return
        self._send(200, json.dumps({"url": "/video"}).encode(), "application/json")

    def log_message(self, fmt, *args):
        print(self.address_string(), fmt % args)


if __name__ == "__main__":
    print(f"知覚楽譜サーバ: http://localhost:{PORT}  (作業領域 {WORK})")
    http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

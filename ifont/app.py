#!/usr/bin/env python3
# =========================================================================
# iFont のアプリ画面（ローカルで動かすブラウザ画面）
#
#   python3 -m ifont.app          → http://localhost:8765 を開く
#
#   中身は ifont.encode をそのまま呼ぶので、生成のふるまいはコマンドライン版と同じ。
#   外部ライブラリは使わない（標準ライブラリだけ）。
# =========================================================================
import http.server
import json
import subprocess
import os
import socketserver
import tempfile
import traceback
import urllib.parse
import uuid
import webbrowser

from ifont import encode

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("IFONT_PORT", "8765"))
OUT_DIR = tempfile.mkdtemp(prefix="ifont_app_")
MADE = {}          # id → 書き出した mp4 のパス
POSTER = {}        # id → その動画の代表コマ（png）


def build(form):
    """画面の入力からコマンドライン引数を組み立てて、動画を1本つくる。"""
    text = (form.get("text") or "").strip()
    if not text:
        raise ValueError("文字列を入れてください。")
    out = os.path.join(OUT_DIR, uuid.uuid4().hex + ".mp4")
    argv = [text, "--family", form.get("family", "blur"), "--out", out,
            "--slot-ms", form.get("slot_ms", "350")]
    if form.get("mode") == "text":
        if form.get("scope") == "first":
            argv.append("--first-only")
    else:
        audio = (form.get("audio") or "").strip()
        onsets = (form.get("onsets") or "").strip()
        curve = (form.get("curve") or "").strip()
        kimariji = (form.get("kimariji") or "").strip()
        if not audio or not onsets:
            raise ValueError("音声ファイルと各文字の開始時刻は両方とも必要です。")
        for p, name in ((audio, "音声ファイル"), (curve, "時間変化のファイル")):
            if p and not os.path.exists(p):
                raise ValueError(f"{name}が見つかりません: {p}")
        argv += ["--audio", audio, "--onsets", onsets]
        if curve:
            argv += ["--curve", curve]
        if kimariji:
            argv += ["--kimariji", kimariji]
    encode.main(argv)
    vid = uuid.uuid4().hex
    MADE[vid] = out
    # 代表コマを1枚抜いておく（再生前に中身が見えるように）
    png = out[:-4] + ".png"
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out,
                        "-vf", "thumbnail", "-frames:v", "1", png],
                       check=True, capture_output=True)
        POSTER[vid] = png
    except Exception:
        pass
    shown = "ifont " + " ".join(
        (f'"{a}"' if " " in a or a == text else a) for a in argv if a != out and a != "--out")
    return vid, shown


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):        # 画面を汚さない
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "app.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif path.startswith("/poster/"):
            p = POSTER.get(path.rsplit("/", 1)[1])
            if not p or not os.path.exists(p):
                self._send(404, b'{"error":"not found"}')
                return
            with open(p, "rb") as f:
                self._send(200, f.read(), "image/png")
        elif path.startswith("/video/"):
            p = MADE.get(path.rsplit("/", 1)[1])
            if not p or not os.path.exists(p):
                self._send(404, b'{"error":"not found"}')
                return
            with open(p, "rb") as f:
                self._send(200, f.read(), "video/mp4")
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/generate":
            self._send(404, b'{"error":"not found"}')
            return
        n = int(self.headers.get("Content-Length", "0"))
        form = {k: v[0] for k, v in
                urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8")).items()}
        try:
            vid, shown = build(form)
            self._send(200, json.dumps(
                {"video": f"/video/{vid}", "poster": f"/poster/{vid}", "command": shown},
                ensure_ascii=False).encode("utf-8"))
        except SystemExit as e:                # encode 側のエラー終了
            self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))
        except Exception as e:
            traceback.print_exc()
            self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"))


def main():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as srv:
        url = f"http://localhost:{PORT}"
        print(f"iFont: {url}  （書き出し先 {OUT_DIR}）")
        if os.environ.get("IFONT_NO_BROWSER") != "1":
            webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n終了しました。")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# =========================================================================
# ifont: MCP サーバ（stdio）
#
#   エンコーダーを AI エージェントの道具として公開する。依存ライブラリ無しの
#   最小実装（JSON-RPC 2.0 / MCP 2024-11-05）。
#
#   登録例（claude mcp add）:
#     claude mcp add ifont -- python3 -m ifont.mcp_server
#
#   道具:
#     ifont_encode … かなの文字列から、音と同期した転写アニメの mp4 を書き出す
# =========================================================================
import json
import os
import sys
import tempfile

TOOLS = [{
    "name": "ifont_encode",
    "description": ("かなの文字列から、音声（較正実験と同じ切り出し音）と、"
                    "その識別の進み方に対応した文字アニメーションが同期した "
                    "mp4 を書き出す。かるたモードでは決まり字だけを"
                    "与えた理解度カーブに対応させる。"),
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "かなの文字列"},
            "family": {"type": "string",
                       "enum": ["fade", "reveal", "blur", "wipe"],
                       "default": "blur", "description": "表示方式"},
            "out_path": {"type": "string",
                         "description": "書き出し先（省略時は一時ファイル）"},
            "slot_ms": {"type": "number",
                        "description": "1字の持ち時間ms（0=クリップ連結。自然な読みは350前後）"},
            "kimariji": {"type": "string",
                         "description": "かるたモード: 決まり字"},
            "curve_csv": {"type": "string",
                          "description": "かるたモード: 理解度カーブCSVのパス"},
        },
        "required": ["text"],
    },
}]


def encode(args):
    # ⚠ stdout は JSON-RPC の通信路。エンコーダーの print が混ざると
    #   クライアント側の JSON 解析が壊れるので、実行中は stderr へ逃がす。
    import contextlib
    from .encode import main as encode_main
    out = args.get("out_path") or tempfile.mktemp(suffix=".mp4", prefix="ifont_")
    argv = [args["text"], "--family", args.get("family", "blur"), "--out", out]
    if args.get("slot_ms"):
        argv += ["--slot-ms", str(args["slot_ms"])]
    if args.get("kimariji"):
        argv += ["--kimariji", args["kimariji"]]
    if args.get("curve_csv"):
        argv += ["--curve", args["curve_csv"]]
    with contextlib.redirect_stdout(sys.stderr):
        encode_main(argv)
    return out


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        method = req.get("method", "")
        if method == "initialize":
            res = {"protocolVersion": "2024-11-05",
                   "capabilities": {"tools": {}},
                   "serverInfo": {"name": "ifont", "version": "0.1.0"}}
        elif method == "tools/list":
            res = {"tools": TOOLS}
        elif method == "tools/call":
            p = req.get("params", {})
            try:
                out = encode(p.get("arguments", {}))
                res = {"content": [{"type": "text",
                                    "text": f"書き出した: {out}"}]}
            except Exception as e:  # noqa: BLE001
                res = {"content": [{"type": "text", "text": f"失敗: {e}"}],
                       "isError": True}
        elif rid is None:
            continue                       # notification は応答しない
        else:
            res = None
        if rid is not None:
            msg = {"jsonrpc": "2.0", "id": rid}
            if res is not None:
                msg["result"] = res
            else:
                msg["error"] = {"code": -32601, "message": f"unknown: {method}"}
            sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

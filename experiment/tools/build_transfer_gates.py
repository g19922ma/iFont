#!/usr/bin/env python3
"""
転写検証実験の「打ち切り済み音声」を作る
=======================================
計画書: project/実験計画書_転写検証.md の 3.4(刺激)・9章1(実装の差分)

この実験の聴覚課題は、音声を「音の実体が始まる点(acoustic onset)から t ミリ秒」で
打ち切って聞かせる。打ち切りはブラウザではなく**事前に作った WAV** で行う。
理由は2つ。
  1. 時間の位置そのものが独立変数なので、端末や再生系のゆらぎを刺激に持ち込みたくない。
  2. 打ち切り端の処理(5ミリ秒のフェードアウト)を全字・全時点で機械的に同一にできる。

作るもの
--------
  experiment/transfer_stimuli/<ファイル名>.wav   … かな × 打ち切り時刻 の刺激
  experiment/transfer_audio_manifest.json        … 索引(実験ページが読む)

打ち切りの規則(計画書 3.4-5)
---------------------------
  ・0ms = acoustic onset。t ms の刺激は onset から t ms ぶんの波形。
  ・終端は**t で終わる 5 ミリ秒の余弦フェードアウト**（ランプ区間 [t-5ms, t]）。
    t より後ろの音は1サンプルも含まない。
  ・先頭にはフェードをかけない(音の立ち上がりを守るため)。
  ・音源の全長が t に足りないときは、その字の最大長で打ち切り、manifest に
    truncated=true と実際の長さを書く(短すぎる時点は A2 で外す判断材料にする)。

使い方
------
  # 本番(録音した自然音声の WAV と、目視確認済みの onset 表を使う)
  python3 experiment/tools/build_transfer_gates.py \
      --src recordings/take_selected --onsets recordings/onsets.json

  # 動作確認(既存の合成音プールで通す。onset はこのスクリプトが自動検出する)
  python3 experiment/tools/build_transfer_gates.py \
      --src audio_base_Kyoko --onsets auto --out-dir /tmp/transfer_stimuli_test \
      --manifest /tmp/transfer_audio_manifest_test.json --limit 6

入力
----
  --src      <かな>.wav が並んだディレクトリ(16bit PCM。ステレオは平均してモノラルにする)
  --onsets   かな → onset(ミリ秒) の JSON。次のどちらの形でもよい。
               {"あ": 50, ...}   /   {"あ": {"acoustic_onset_ms": 50}, ...}
             "auto" を渡すと自動検出する(検出結果は --onsets-out に書き出すので、
             計画書 Q9 のとおり波形とスペクトログラムで全数を目視確認してから本番に使う)。
  --config   打ち切り時刻の表(字ごと)を読む設定ファイル。既定は experiment/transfer_config.js。
             node が使える環境なら、実験ページと同じ表を直接読む(表を二重に持たないため)。
             node が無い環境では --gates で JSON を渡す。
  --salt     ファイル名を伏せたいとき。sha256(salt|かな|t) の先頭20桁をファイル名にする。
             (実験ページは manifest でかな→ファイルを引くので、伏せても動く。)
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(HERE)
REPO = os.path.dirname(EXP)

FADE_OUT_MS_DEFAULT = 5.0
# 自動検出のしきい値(experiment/tools/build_onsets.py と同じ考え方)。
DETECT_FRAME_MS = 5.0
DETECT_DBFS = -58.0
DETECT_HOLD_MS = 15.0


# ---- 設定ファイルの読み出し ------------------------------------------------
def load_config(path):
    """transfer_config.js を node 経由で読む(実験ページと同じ数値を使うため)。"""
    js = ("global.window={};require(%s);"
          "process.stdout.write(JSON.stringify(window.TRANSFER_CONFIG));" % json.dumps(path))
    try:
        out = subprocess.run(["node", "-e", js], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        msg = getattr(e, "stderr", b"")
        raise SystemExit("transfer_config.js を読めませんでした(node が要る)。--gates で表を渡してください。\n"
                         + (msg.decode("utf-8", "replace") if msg else str(e)))
    return json.loads(out.stdout.decode("utf-8"))


def gates_for(table, ch):
    if ch in table:
        return list(table[ch])
    return list(table.get("_default", []))


# ---- WAV の読み書き --------------------------------------------------------
def read_wav(path):
    with wave.open(path, "rb") as w:
        n_ch, width, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    elif width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    else:
        raise SystemExit(f"{path}: {width*8}bit の WAV には未対応")
    if n_ch > 1:
        x = x.reshape(-1, n_ch).mean(axis=1)
    return x, sr


def write_wav(path, x, sr):
    y = np.clip(x, -1.0, 1.0)
    data = (y * 32767.0).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data)


# ---- onset の自動検出 ------------------------------------------------------
def detect_onset_ms(x, sr):
    """5ms フレームの実効値が -58dBFS を 15ms 以上続けて超えた最初の点。

    破裂音の閉鎖区間(ほぼ無音)は飛ばし、鼻音・はじき音のような弱い立ち上がりは拾う。
    本番の刺激では、この値を初期値として全数を目視確認する(計画書 Q9)。
    """
    fr = max(1, int(round(sr * DETECT_FRAME_MS / 1000.0)))
    hold = max(1, int(round(DETECT_HOLD_MS / DETECT_FRAME_MS)))
    n_fr = len(x) // fr
    if n_fr == 0:
        return 0.0
    frames = x[:n_fr * fr].reshape(n_fr, fr)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-20)
    over = 20 * np.log10(rms) > DETECT_DBFS
    run = 0
    for i, ok in enumerate(over):
        run = run + 1 if ok else 0
        if run >= hold:
            return (i - hold + 1) * DETECT_FRAME_MS
    return 0.0


# ---- 打ち切り --------------------------------------------------------------
def gate(x, sr, onset_ms, gate_ms, fade_ms):
    """onset から gate_ms ぶんを切り出し、終端 fade_ms を余弦で 1→0 に落とす。

    gate_ms=None は「打ち切りなし」(onset から音源の終わりまで)。
    戻り値: (波形, 実際の長さms, 足りなかったか)
    """
    start = max(0, int(round(onset_ms / 1000.0 * sr)))
    avail = len(x) - start
    if avail <= 0:
        return np.zeros(1), 0.0, True
    want = avail if gate_ms is None else int(round(gate_ms / 1000.0 * sr))
    n = min(want, avail)
    truncated = (gate_ms is not None) and (want > avail)
    y = x[start:start + n].copy()
    f = min(int(round(sr * fade_ms / 1000.0)), n)
    if f > 0:
        # 区間の先頭で 1、終端で 0 になる余弦の窓(ランプ区間は [t-fade, t])。
        i = np.arange(1, f + 1)
        y[n - f:] *= 0.5 * (1.0 + np.cos(math.pi * i / f))
    return y, n / sr * 1000.0, truncated


def out_name(ch, gate_ms, salt):
    tag = "full" if gate_ms is None else f"g{int(round(gate_ms)):04d}"
    if salt:
        h = hashlib.sha256(f"{salt}|{ch}|{tag}".encode("utf-8")).hexdigest()[:20]
        return h + ".wav"
    return f"{ch}_{tag}.wav"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="<かな>.wav が並んだディレクトリ")
    ap.add_argument("--onsets", default="auto",
                    help='かな→onset(ms) の JSON。"auto" で自動検出')
    ap.add_argument("--onsets-out", default=os.path.join(EXP, "transfer_onsets.json"),
                    help="自動検出した onset の書き出し先(目視確認に使う)")
    ap.add_argument("--config", default=os.path.join(EXP, "transfer_config.js"))
    ap.add_argument("--gates", default=None,
                    help='打ち切り時刻の表 JSON。{"_default":[20,...],"た":[...]} 形式(config より優先)')
    ap.add_argument("--out-dir", default=os.path.join(EXP, "transfer_stimuli"))
    ap.add_argument("--manifest", default=os.path.join(EXP, "transfer_audio_manifest.json"))
    ap.add_argument("--fade-ms", type=float, default=None,
                    help=f"終端フェードの長さms(既定は config の audio.fade_out_ms / {FADE_OUT_MS_DEFAULT})")
    ap.add_argument("--chars", default=None, help="対象のかなをカンマなしで並べた文字列(既定: 設定の全かな)")
    ap.add_argument("--limit", type=int, default=0, help="先頭 N 字だけ処理する(動作確認用)")
    ap.add_argument("--salt", default="", help="ファイル名を伏せるときの合言葉")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = None
    if args.gates:
        with open(args.gates, encoding="utf-8") as f:
            gate_table = json.load(f)
        fade_ms = args.fade_ms if args.fade_ms is not None else FADE_OUT_MS_DEFAULT
        chars = list(args.chars) if args.chars else sorted(k for k in gate_table if k != "_default")
    else:
        cfg = load_config(args.config)
        gate_table = cfg["audio"]["gates_ms"]
        fade_ms = args.fade_ms if args.fade_ms is not None else cfg["audio"].get("fade_out_ms", FADE_OUT_MS_DEFAULT)
        if args.chars:
            chars = list(args.chars)
        else:
            # 設定のかな表にある字すべて(ターゲット8字＋まぎれ字)。
            chars = [c for row in cfg["answer_grid"] for c in row if c]

    # 音源のある字だけに絞る。
    chars = [c for c in chars if os.path.exists(os.path.join(args.src, c + ".wav"))]
    if args.limit:
        chars = chars[:args.limit]
    if not chars:
        raise SystemExit(f"{args.src} に処理できる <かな>.wav がありません")

    # onset の表。
    detected = {}
    if args.onsets == "auto":
        onsets = {}
    else:
        with open(args.onsets, encoding="utf-8") as f:
            raw = json.load(f)
        onsets = {}
        for k, v in raw.items():
            if k.startswith("_"):
                continue          # "_note" のような覚え書きの鍵は読み飛ばす
            onsets[k] = float(v) if isinstance(v, (int, float)) else float(v.get("acoustic_onset_ms", 0.0))

    if not args.dry_run:
        os.makedirs(args.out_dir, exist_ok=True)

    items = {}
    n_files = 0
    print(f"音源: {args.src}  対象 {len(chars)} 字  終端フェード {fade_ms} ms")
    for ch in chars:
        x, sr = read_wav(os.path.join(args.src, ch + ".wav"))
        if ch in onsets:
            onset_ms, how = onsets[ch], "given"
        else:
            onset_ms, how = detect_onset_ms(x, sr), "auto"
            detected[ch] = round(onset_ms, 1)
        avail_ms = len(x) / sr * 1000.0 - onset_ms
        gates = gates_for(gate_table, ch) + [None]      # None = 打ち切りなし(全長)
        line = []
        for g in gates:
            y, dur_ms, trunc = gate(x, sr, onset_ms, g, fade_ms)
            name = out_name(ch, g, args.salt)
            if not args.dry_run:
                write_wav(os.path.join(args.out_dir, name), y, sr)
            key = f"{ch}|{'full' if g is None else int(round(g))}"
            items[key] = {
                "file": name, "char": ch,
                "gate_ms": None if g is None else int(round(g)),
                "dur_ms": round(dur_ms, 2), "onset_ms": round(onset_ms, 1),
                "onset_source": how, "sr": sr, "truncated": bool(trunc),
            }
            n_files += 1
            line.append(("full" if g is None else str(int(g))) + ("!" if trunc else ""))
        print(f"  {ch}  onset={onset_ms:6.1f}ms({how})  有効長={avail_ms:6.1f}ms  時点: " + " ".join(line))

    manifest = {
        "modality": "transfer_audio",
        "source_dir": os.path.relpath(args.src, REPO),
        "fade_out_ms": fade_ms,
        "onset_zero": "acoustic onset を 0ms とする(計画書 3.4-4)",
        "config_version": (cfg or {}).get("config_version", ""),
        "salted": bool(args.salt),
        "count": n_files,
        "items": items,
    }
    if not args.dry_run:
        with open(args.manifest, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        if detected:
            with open(args.onsets_out, "w", encoding="utf-8") as f:
                json.dump({k: {"acoustic_onset_ms": v, "source": "auto"} for k, v in detected.items()},
                          f, ensure_ascii=False, indent=1)
        # 検算: 書き出した WAV の長さが manifest の値と合っているか全数見る。
        bad = 0
        for key, it in items.items():
            y, sr2 = read_wav(os.path.join(args.out_dir, it["file"]))
            got = len(y) / sr2 * 1000.0
            if abs(got - it["dur_ms"]) > 0.05:
                print(f"  ! 長さ不一致 {key}: 期待 {it['dur_ms']} / 実際 {got:.2f}")
                bad += 1
        print(f"検算: {len(items)} 本中 {bad} 本が不一致")
        print(f"書き出し: {args.out_dir} に {n_files} 本 / 索引 {args.manifest}")
        if detected:
            print(f"自動検出した onset: {args.onsets_out}（本番では全数を目視確認すること）")
    else:
        print(f"(dry-run) {n_files} 本を作る予定")
    return 0


if __name__ == "__main__":
    sys.exit(main())

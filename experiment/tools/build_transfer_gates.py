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

頭の切り揃え(--lead-ms、既定 50 ミリ秒)
--------------------------------------
  出力WAVは onset ちょうどではなく **onset の lead ミリ秒手前**から始める。
  ねらいは2つ。
    1. 全字で「音が鳴り出す前の静けさ」の長さを揃える。録音の切り出しは前後に
       50 ミリ秒の余白を付けてあるが、「に」のように頭に息継ぎを巻き込んだ字は
       余白が 316 ミリ秒もある(project/録音QC_20260820.md §10-2)。ここで切り揃えると
       その余分が落ちる。
    2. 波形の途中(振幅がゼロでない点)から鳴らすと「プツッ」という不要な音が出る。
       手前に静かな区間を置けばそれが起きない。
  lead ぶんは onset より前なので **刺激の中身(t ミリ秒)には数えない**。
  つまりファイルの全長は lead + t ミリ秒になる。manifest には両方書く
  (lead_ms / gate_ms / dur_ms)。lead は全字・全時点で同じなので、時点どうしの
  比較にも聴覚と視覚の比較にも影響しない。

使い方
------
  # 本番(録音の採用テイクと、話者本人が全数確認した onset 表を使う)
  python3 experiment/tools/build_transfer_gates.py \
      --src recordings_raw/adopted --onsets recordings_raw/adopted_onsets.json

  # 動作確認(既存の合成音プールで通す。onset はこのスクリプトが自動検出する)
  python3 experiment/tools/build_transfer_gates.py \
      --src audio_base_Kyoko --onsets auto --out-dir /tmp/transfer_stimuli_test \
      --manifest /tmp/transfer_audio_manifest_test.json --limit 6

入力
----
  --src      音源のディレクトリ(16bit PCM の WAV。ステレオは平均してモノラルにする)。
             ファイル名は <かな>.wav。onset 表が採用テイク形式(下記)なら、その表に
             書かれたファイル名(例 adopted/00_あ.wav)を使うので通し番号付きでもよい。
  --onsets   かな → onset(ミリ秒) の表。次のどれでもよい。
             (a) 採用テイク形式 … {"meta": {...}, "adopted": [{"kana","file","onset_ms"}, ...]}
                 recordings_raw/adopted_onsets.json がこれ。音源のファイル名も一緒に持つ。
             (b) {"あ": 50, ...}
             (c) {"あ": {"acoustic_onset_ms": 50}, ...}
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
LEAD_MS_DEFAULT = 50.0      # onset の手前に残す静かな区間(--lead-ms の説明を参照)
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


# ---- onset 表の読み出し ----------------------------------------------------
def _resolve_src(rel, ch, src_dir, base_dir):
    """onset 表に書かれた音源のパスを、実際に開ける場所へ解決する。"""
    for cand in ([os.path.join(src_dir, rel),
                  os.path.join(base_dir, rel),
                  os.path.join(src_dir, os.path.basename(rel))] if rel else []) + \
                [os.path.join(src_dir, ch + ".wav")]:
        if os.path.exists(cand):
            return cand
    return os.path.join(src_dir, ch + ".wav")     # 無いことは呼び出し側が弾く


def load_onsets(path, src_dir):
    """onset の表を読む。戻り値 (かな→onset ms, かな→音源パス, 表の meta)。

    採用テイク形式(recordings_raw/adopted_onsets.json)は音源のファイル名も持っているので、
    通し番号付きのファイル名(00_あ.wav)でもそのまま使える。
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    base_dir = os.path.dirname(os.path.abspath(path))
    if isinstance(raw, dict) and isinstance(raw.get("adopted"), list):
        onsets, files = {}, {}
        for it in raw["adopted"]:
            ch = it["kana"]
            onsets[ch] = float(it["onset_ms"])
            files[ch] = _resolve_src(it.get("file", ""), ch, src_dir, base_dir)
        return onsets, files, dict(raw.get("meta", {}))
    onsets = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue              # "_note" のような覚え書きの鍵は読み飛ばす
        onsets[k] = float(v) if isinstance(v, (int, float)) else float(v.get("acoustic_onset_ms", 0.0))
    return onsets, {}, {}


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
def gate(x, sr, onset_ms, gate_ms, fade_ms, lead_ms=0.0):
    """onset の lead_ms 手前から onset+gate_ms までを切り出す。

    終端 fade_ms は余弦で 1→0 に落とす。フェードのランプ区間は onset を 0ms として
    [gate_ms-fade_ms, gate_ms]。gate_ms=None は「打ち切りなし」(onset から音源の終わりまで)。
    lead_ms ぶんの前置きは onset より前なので刺激の長さには数えない。
    音源の余白が lead_ms に足りなければ、あるだけ付ける(実際の値を返す)。

    戻り値: (波形, ファイル全長ms, onsetから後ろの長さms, 実際の前置きms, 足りなかったか)
    """
    onset = max(0, int(round(onset_ms / 1000.0 * sr)))
    lead = min(max(0, int(round(lead_ms / 1000.0 * sr))), onset)
    avail = len(x) - onset
    if avail <= 0:
        return np.zeros(1), 0.0, 0.0, 0.0, True
    want = avail if gate_ms is None else int(round(gate_ms / 1000.0 * sr))
    n = min(want, avail)
    truncated = (gate_ms is not None) and (want > avail)
    y = x[onset - lead:onset + n].copy()
    f = min(int(round(sr * fade_ms / 1000.0)), n)
    if f > 0:
        # 区間の先頭で 1、終端で 0 になる余弦の窓。
        i = np.arange(1, f + 1)
        y[len(y) - f:] *= 0.5 * (1.0 + np.cos(math.pi * i / f))
    return y, len(y) / sr * 1000.0, n / sr * 1000.0, lead / sr * 1000.0, truncated


def out_name(ch, gate_ms, salt):
    tag = "full" if gate_ms is None else f"g{int(round(gate_ms)):04d}"
    if salt:
        h = hashlib.sha256(f"{salt}|{ch}|{tag}".encode("utf-8")).hexdigest()[:20]
        return h + ".wav"
    return f"{ch}_{tag}.wav"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True,
                    help="音源のディレクトリ(<かな>.wav。onset 表が採用テイク形式ならそこに書かれたファイル名を使う)")
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
    ap.add_argument("--lead-ms", type=float, default=LEAD_MS_DEFAULT,
                    help=f"onset の手前に残す静かな区間ms(既定 {LEAD_MS_DEFAULT}。0 で onset ちょうどから)")
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

    # onset の表(音源のファイル名も一緒に持つ形式がある)。
    detected = {}
    onsets, src_files, onset_meta = {}, {}, {}
    if args.onsets != "auto":
        onsets, src_files, onset_meta = load_onsets(args.onsets, args.src)

    def src_path(ch):
        return src_files.get(ch) or os.path.join(args.src, ch + ".wav")

    # 音源のある字だけに絞る。
    missing = [c for c in chars if not os.path.exists(src_path(c))]
    chars = [c for c in chars if os.path.exists(src_path(c))]
    if args.limit:
        chars = chars[:args.limit]
    if not chars:
        raise SystemExit(f"{args.src} に処理できる音源がありません")
    if missing:
        print(f"! 音源が無いので飛ばす {len(missing)} 字: " + " ".join(missing))

    if not args.dry_run:
        os.makedirs(args.out_dir, exist_ok=True)

    items = {}
    leads = []
    n_files = 0
    print(f"音源: {args.src}  対象 {len(chars)} 字  終端フェード {fade_ms} ms  前置き {args.lead_ms} ms")
    for ch in chars:
        x, sr = read_wav(src_path(ch))
        if ch in onsets:
            onset_ms, how = onsets[ch], "given"
        else:
            onset_ms, how = detect_onset_ms(x, sr), "auto"
            detected[ch] = round(onset_ms, 1)
        avail_ms = len(x) / sr * 1000.0 - onset_ms
        gates = gates_for(gate_table, ch) + [None]      # None = 打ち切りなし(全長)
        line = []
        lead_used = args.lead_ms
        for g in gates:
            y, dur_ms, after_ms, lead_got, trunc = gate(x, sr, onset_ms, g, fade_ms, args.lead_ms)
            lead_used = lead_got
            name = out_name(ch, g, args.salt)
            if not args.dry_run:
                write_wav(os.path.join(args.out_dir, name), y, sr)
            key = f"{ch}|{'full' if g is None else int(round(g))}"
            items[key] = {
                "file": name, "char": ch,
                "gate_ms": None if g is None else int(round(g)),
                "after_onset_ms": round(after_ms, 2),   # onset から後ろの実際の長さ
                "lead_ms": round(lead_got, 2),          # onset より前に付けた静かな区間
                "dur_ms": round(dur_ms, 2),             # ファイル全長 = lead + after
                "onset_ms": round(onset_ms, 1),         # 元の音源の中での onset の位置
                "onset_source": how, "sr": sr, "truncated": bool(trunc),
            }
            n_files += 1
            line.append(("full" if g is None else str(int(g))) + ("!" if trunc else ""))
        # 録音の余白が --lead-ms に足りない字は、あるだけ付ける(その値を表示する)。
        note = "" if lead_used + 0.05 >= args.lead_ms else f"  前置き={lead_used:.0f}ms(余白がこれだけしかない)"
        leads.append(lead_used)
        print(f"  {ch}  onset={onset_ms:6.1f}ms({how})  有効長={avail_ms:6.1f}ms  時点: "
              + " ".join(line) + note)

    manifest = {
        "modality": "transfer_audio",
        "source_dir": os.path.relpath(args.src, REPO),
        "onsets_from": ("auto" if args.onsets == "auto" else os.path.relpath(args.onsets, REPO)),
        "onsets_meta": onset_meta,
        "fade_out_ms": fade_ms,
        "lead_ms": args.lead_ms,
        "lead_ms_actual_range": [round(min(leads), 2), round(max(leads), 2)] if leads else [],
        "onset_zero": "acoustic onset を 0ms とする(計画書 3.4-4)。"
                      "各ファイルは onset の lead_ms 手前から始まるので、"
                      "刺激の長さ(gate_ms)はファイル全長(dur_ms)から lead_ms を引いた値にあたる",
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

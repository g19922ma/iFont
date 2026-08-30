#!/usr/bin/env python3
# =========================================================================
# 見え心地（群C）用の進み方の表をひとつにまとめる
#
#   入力: project/data_calib2_live/warp_exp_c/transfer_warp_c{1,2,3,4}_*.json
#         4条件がそれぞれ別ファイルになっている。中身の構造はどれも同じで、
#         tables[方式][字]["proposed"] にその条件の進み方が入っている。
#
#   出力: experiment/transfer_warp_comfort.json
#         tables[方式][字][条件] の形にまとめる。条件キーは4つ＋等速の対照。
#
#   なぜまとめるか: 描画側の warpSeries(family, ch, condition) が
#   tables[方式][字][条件] を引く作りになっているので、ここに4条件を並べておけば
#   描画のコードを触らずに条件を切り替えられる。
#
#   ⚠ 本番の transfer_warp.json（群B用）とは別ファイルである。上書きしない。
# =========================================================================
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT, "project", "data_calib2_live", "warp_exp_c")
OUT = os.path.join(ROOT, "experiment", "transfer_warp_comfort.json")

# 条件キー → (元ファイル, 通し番号, 表示名)
CONDS = [
    ("c1_acc_shape",  "transfer_warp_c1_acc_shape.json",  "①", "正答率揃え（形まで）"),
    ("c2_info_shape", "transfer_warp_c2_info_shape.json", "②", "情報量揃え（形まで）"),
    ("c3_acc_mid",    "transfer_warp_c3_acc_mid.json",    "③", "半分・正答率"),
    ("c4_info_mid",   "transfer_warp_c4_info_mid.json",   "④", "半分・情報量"),
]
LINEAR_KEY = "linear"          # 等速の対照（元ファイルの baseline1）
SRC_SERIES = "proposed"        # 各ファイルからこの系列を取る

# 4ファイルで一致していなければならない項目。ずれていたら止める。
MUST_MATCH = ["frame_ms", "duration_ms", "base_anim_ms"]


def main():
    loaded = []
    for key, fname, no, label in CONDS:
        path = os.path.join(SRC_DIR, fname)
        if not os.path.exists(path):
            sys.exit("入力が無い: " + path)
        with open(path, encoding="utf-8") as f:
            loaded.append((key, no, label, json.load(f)))

    head = loaded[0][3]
    for key, no, label, d in loaded[1:]:
        for k in MUST_MATCH:
            if d.get(k) != head.get(k):
                sys.exit("%s が条件でずれている: %s=%s / %s=%s"
                         % (k, loaded[0][0], head.get(k), key, d.get(k)))

    families = sorted(head["tables"].keys())
    chars = sorted(head["tables"][families[0]].keys())
    for key, no, label, d in loaded:
        if sorted(d["tables"].keys()) != families:
            sys.exit("方式の一覧が条件でずれている: " + key)
        for fam in families:
            if sorted(d["tables"][fam].keys()) != chars:
                sys.exit("字の一覧がずれている: %s / %s" % (key, fam))

    # ---- 本体をまとめる ----------------------------------------------------
    tables = {}
    n_len = set()
    for fam in families:
        tables[fam] = {}
        for ch in chars:
            cell = {}
            for key, no, label, d in loaded:
                series = d["tables"][fam][ch][SRC_SERIES]
                cell[key] = series
                n_len.add(len(series))
            # ---- 中点だけ合わせる条件は、等速のまま100%まで走らせる（2026-08-30）----
            # ③④の定義は「開始をずらし、その方式本来の等速で進める」。開始を t0 遅らせた
            # ぶん、完成は t0+300ms ＝ 300msの窓のわずかに外に出る。元の表は窓で
            # 切れているため 90.9〜99.6% で尻切れになっていた（作表の都合であって
            # 手法の出力ではない）。等速の1コマぶんの傾き（100% ÷ 300ms）で
            # 完成まで延ばす。追加は1〜2コマ（7〜27ms）。
            for key in ("c3_acc_mid", "c4_info_mid"):
                ser = cell[key]
                if ser[-1] < 0.999:
                    step = 100.0 * head["frame_ms"] / head["base_anim_ms"] / 100.0
                    ext = list(ser)
                    while ext[-1] < 0.999:
                        ext.append(min(1.0, ext[-1] + step))
                    cell[key] = ext
            # 等速の対照は4ファイルで同一のはずなので先頭から取り、一致を確かめる
            lin = head["tables"][fam][ch]["baseline1"]
            for key, no, label, d in loaded[1:]:
                if d["tables"][fam][ch]["baseline1"] != lin:
                    sys.exit("等速の対照が条件でずれている: %s %s %s" % (key, fam, ch))
            cell[LINEAR_KEY] = lin
            n_len.add(len(lin))
            tables[fam][ch] = cell

    # ③④を完成まで延ばすので、長さは揃わなくてよい（19〜21コマ）。
    if min(n_len) < 19 or max(n_len) > 25:
        sys.exit("系列の長さが想定外: " + str(sorted(n_len)))

    out = {
        "generated_by": "experiment/tools/merge_warp_comfort.py",
        "source_files": [f for _, f, _, _ in CONDS],
        "estimator": head.get("estimator"),
        "frame_ms": head["frame_ms"],
        "duration_ms": head["duration_ms"],
        "base_anim_ms": head["base_anim_ms"],
        "n_frames": max(n_len),
        "linear_key": LINEAR_KEY,
        # 条件の見出し。分析と画面の表示で使う。
        "conditions": [
            {"key": key, "no": no, "label": label,
             "target": d.get("target"), "align": d.get("align")}
            for key, no, label, d in loaded
        ],
        # 一気に出す表示の切り替え時刻は条件ごとに違う。
        # ①③は「が」の中点が決まらないので入っていない（正答率2.9%のため）。
        "step_mid_ms_by_condition": {
            key: d.get("step_mid_ms", {}) for key, no, label, d in loaded
        },
        "meta": head.get("meta"),
        "tables": tables,
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    # ---- 目で見て確かめるための出力 ----------------------------------------
    print("書き出し: %s (%.0f KB)" % (OUT, os.path.getsize(OUT) / 1024))
    print("方式 %d / 字 %d / 条件 %d（＋等速） / 1本 %d コマ"
          % (len(families), len(chars), len(CONDS), out["n_frames"]))
    print()
    for key, no, label, d in loaded:
        miss = [c for c in chars if c not in (d.get("step_mid_ms") or {})]
        print("  %s %-14s %s%s" % (no, key, label,
              ("  ※一気に出す表示の時刻が無い字: " + "".join(miss)) if miss else ""))
    print()
    print("見はじめた瞬間の進み具合（blur・5字ぶん、%表示）")
    seq = [c for c in ["あ", "か", "し", "ま", "ら"] if c in chars]
    print("       " + "".join("%7s" % c for c in seq))
    for key, no, label, d in loaded:
        row = [tables["blur"][c][key][0] * 100 for c in seq]
        print("  %s   " % no + "".join("%6.1f%%" % v for v in row))
    row = [tables["blur"][c][LINEAR_KEY][0] * 100 for c in seq]
    print("  等速 " + "".join("%6.1f%%" % v for v in row))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
uniform200 の正解表を experiment/answer_key_merged.json に統合する
==================================================================
点検モード(pilot_soa_audio.html?pool=uniform200&check=1)は、かなを押したときに
どの mp3 を鳴らすかを answer_key_merged.json から引く。候補プールぶんの
「ファイルのハッシュ → かな」の対応をここに足さないと、ページはこのプールを鳴らせない。

既存の候補プール(cand108・slot133 など)と同じ形にそろえる:
  "audio1char|<hash>": { ..., "speaker": 108, "pool": "uniform200" }

同じ pool のキーが既にあれば入れ替える(作り直したときに古い対応が残らないように)。

実行:
  python3 experiment/candidate_pools/uniform200/merge_answer_key.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.dirname(os.path.dirname(HERE))

POOL = "uniform200"
SPEAKER = 108

merged_path = os.path.join(EXP, "answer_key_merged.json")
merged = json.load(open(merged_path))
pool_key = json.load(open(os.path.join(HERE, "answer_key_1char.json")))

removed = [k for k, v in merged.items() if isinstance(v, dict) and v.get("pool") == POOL]
for k in removed:
    del merged[k]

for k, v in pool_key.items():
    v = dict(v)
    v["speaker"] = SPEAKER
    v["pool"] = POOL
    merged[k] = v

json.dump(merged, open(merged_path, "w"), ensure_ascii=False, indent=1)
print(f"{POOL}: 古い対応 {len(removed)} 件を消し、{len(pool_key)} 件を統合した "
      f"(全体 {len(merged)} 件) -> {merged_path}", file=sys.stderr)

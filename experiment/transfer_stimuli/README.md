# transfer_stimuli/ — 転写検証実験の聴覚刺激（打ち切り済みWAV）

**このディレクトリはまだ空**（本番の音源が未収録のため）。中身は
`experiment/tools/build_transfer_gates.py` が作る。手で置いたり編集したりしない。

## 置かれるもの

```
experiment/
├── transfer_stimuli/
│   ├── あ_g0020.wav      ← 「あ」を音の実体の開始から 20ms で打ち切ったもの
│   ├── あ_g0040.wav
│   ├── …                  （字 × 打ち切り時刻の数だけ）
│   └── あ_full.wav        ← 打ち切りなし（練習・確認問題・音量確認に使う）
└── transfer_audio_manifest.json   ← 索引。実験ページはこれを見てファイルを引く
```

`--salt` を付けて作ると、ファイル名は `sha256(合言葉|かな|時点)` の先頭20桁になる
（URLからは中身が分からなくなる。索引は実験ページが読むので動作は変わらない）。

## 作り方

```bash
# 本番: 録音した自然音声（<かな>.wav）と、目視確認した onset の表を渡す
python3 experiment/tools/build_transfer_gates.py \
    --src <録音の採用テイクのディレクトリ> --onsets <onsetの表.json>

# 動作確認: 既存の合成音で通す（onset は自動検出）
python3 experiment/tools/build_transfer_gates.py \
    --src audio_base_Kyoko --onsets auto \
    --out-dir /tmp/transfer_stimuli_test --manifest /tmp/transfer_audio_manifest_test.json
```

打ち切り時刻の表（字ごと）は `experiment/transfer_config.js` の `audio.gates_ms` にある。
スクリプトは node 経由でその設定を直接読むので、表を2か所に書かなくてよい。

## 音源に求めること（計画書 3.4）

1. 日本語を母語とする話者1名が、かなを1字ずつ単独で自然に発話。全68かな。
2. テイクの選び方は録音前に固定（読み間違い・雑音・音割れを除き、長さが真ん中の回）。
3. 音量合わせは1音まるごとに一定の倍率を掛けるだけ（中身の強弱の配分は変えない）。
4. **音の実体が始まる点（acoustic onset）を測って記録し、実験の 0ms とする。**
   自動検出（短い窓の実効値が背景雑音を十分超えた最初の点）を初期値に、全数を目視確認する。
5. 打ち切りは、t で終わる 5ms の余弦フェードアウト（t より後ろの音は一切含まない）。
6. 配信は WAV のまま（音の頭の立ち上がりを守るため圧縮しない）。

## onset の表（`--onsets` に渡す JSON）の形

`transfer_onsets.sample.json` を参照。次のどちらの形でもよい。

```json
{ "あ": 50, "か": 42 }
{ "あ": {"acoustic_onset_ms": 50}, "か": {"acoustic_onset_ms": 42} }
```

`--onsets auto` で走らせると、自動検出した値を `experiment/transfer_onsets.json` に
書き出す。**本番ではこれを目視確認して直したものを `--onsets` で渡し直す。**
時間の位置そのものがこの実験の独立変数なので、5ms のずれも無視できない（計画書 Q9）。

## 本番刺激が揃うまでの代用

索引 `transfer_audio_manifest.json` が無いとき、実験ページは
`experiment/audio_base/<かな>.mp3`（既存の合成音）を、同じ規則（onset 起点・終端5msフェード）で
ブラウザ側で切って鳴らす**代用モード**で動く。画面下に「音声は代用モード」と出る。
**データ取得には使わない**（研究者の動作確認専用）。

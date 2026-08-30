# ifont — 音と表示が同期した動画のエンコーダー

かなの文字列を入れると、音声（較正実験と同じ切り出し音・COEIROINK「あみたろ」）と、
その音声の識別の進み方に対応した文字アニメーションが同期した mp4 を書き出す。

転写は絶対値：各時刻の表示が、音声がその時点で伝えている識別率と同じ値になる進み具合を
`s(t) = V^-1(A(t))` で計算する。音声が最後まで識別されない字は、文字も完成しない。

## 使い方

```bash
# 全文字を転写（ドラマの字幕のように、全部が重要なとき）
python3 -m ifont.encode "まさかここであうとは" --family blur --slot-ms 350 --out drama.mp4

# いろはかるた: 1音目だけ転写し、残りは読まれた時刻に一括表示
python3 -m ifont.encode "いぬもあるけばぼうにあたる" --first-only --slot-ms 350 --out iroha.mp4

# 競技かるた: 実際の読み上げ音声に同期。決まり字だけ実測カーブで転写し、残りは一括表示
# （カーブはその音声に対する実測なので、合成クリップは使わない）
python3 -m ifont.encode "ちはやふる" --kimariji ちは --curve kimariji_chiha.csv \
    --audio yomi.wav --onsets "140,940,1740,2540,3340" --out karuta.mp4
```

方式は `--family fade|reveal|blur|wipe`。`--slot-ms` は1字の持ち時間（クリップより
長い分は無音。0=隙間なく連結で機械的に速い。自然な読みは350前後、競技かるたは700〜1000）。
入力はひらがな・カタカナ64字（を・ぢ・づ・ゔは音声クリップが無い）。空白・句読点は無音の1拍。
漢字は読み（ひらがな）に開いてから流す（pykakasi）。読みに開けない字だけ、字を挙げて断る。カーブCSVは `time_ms,value`（value は
その時刻までに識別できている割合 0..1。Kikiwake の選手別実測などから作る）。

## MCP サーバ

```bash
claude mcp add ifont -- python3 -m ifont.mcp_server
```

道具 `ifont_encode`（text / family / kimariji / curve_csv / out_path）が生える。

## 較正曲線の3階層

| tier | 出どころ | 品質 |
|---|---|---|
| measured | 重点測定8字（聴覚90名・視覚325名の袋詰め単調回帰） | 実測 |
| provisional | 紛れ字（聴覚59字・視覚63字。1点あたり約7試行） | 暫定 |
| fallback | どちらも無い字（同方式の暫定曲線の平均） | 代用 |

生成時に各字の tier を表示する。描画は実験ページ（experiment/transfer.js）と同じ計算
（点が増えるの画素順は同一乱数を移植。ぼかしは blur(N px)=標準偏差 N を実測確認済み）。

必要なもの: Python3 + numpy + Pillow、ffmpeg、リポジトリ内の
`experiment/base/`（字形PNG）と `experiment/transfer_stimuli_amitaro/`（音声）。

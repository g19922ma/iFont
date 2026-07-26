# VoiSona 知声によるかるた読み試作（2026-07-26）

披講用音声を歌声合成で作る検証。VOICEVOX で4段の処方が必要だった伸ばし・余韻・
句頭スライドが、歌声合成では素の出力に備わることを確認した。

## ファイル
- `chihayaburu_chisa.musicxml` — 知声用楽譜。tempo60（音価=秒）、木本実読み「ちは」の
  実測タイミング、句頭B3・他E4、歌詞は読み仮名。VoiSona にインポートして WAV+lab を書き出す
- `chisa_full_moras.json` — 韻律完全転写版のモーラ境界（字幕同期用）

## フロー（半自動。VoiSona は CLI/API なしの GUI 専用）
1. 楽譜(MusicXML)を生成 →ユーザーが VoiSona で WAV + .lab を書き出し（唯一の手作業）
2. .lab の音素境界からモーラ onset を取得し、render_frames_gated で字幕同期動画を生成
3. さらに「韻律完全転写」: 木本実読みの F0 輪郭・音量エンベロープ・モーラ長/休止長を
   モーラ対応のタイムワープで知声 WAV に PSOLA(DurationTier+PitchTier)転写
   （声=知声、節回し=木本。実装はセッション記録と WORKLOG 2026-07-26 を参照）

## 注意
- 音声(.wav)と .lab は知声の利用規約に配慮して git に入れない（ローカル: ~/Desktop/ifont_listen/）
- 公開時はクレジット「VoiSona:知声」が必要
- 木本実読みの参照元は Kikiwake リポジトリ（**読み取り専用**・変更禁止）

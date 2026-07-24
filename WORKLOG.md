# WORKLOG

> セッションをまたぐ作業状態の記録。プロジェクトの全履歴は `project/project_log_260723.md`、
> セットアップと全体像は `project/handover_260723.md` を参照。

## 2026-07-24 品質処方の連続合成への移植（CLI本体）

### 現在の状態
- **完了**: 単音・2文字プールで確立した品質処方を `ifont_tool` の設計提示モードへ移植した。
  7/21懐疑レビューで「最重要の残課題」(C3=REFUTED)と判定されていたもの。
  - `ifont_tool/ifont/quality.py` **新設**: 強制有声化(母音小文字化)・F0適合(実測→減衰0.55倍の
    逆補正→再合成、最大4回・最良反復採用)・音量ならし(モーラ節点±8dB・2dB不感帯・60ms平滑)。
    出典は `experiment/tools/build_karuta_samples.py`（karuta_5316/ooyama で検証済みの処方）
  - `audio.py` の `synth_voicevox_designed` に組み込み（既定ON、`quality=False`で旧挙動）
  - `cli.py` に `--raw-voice`（処方を切る）と `[quality]` 経過ログ表示を追加
  - `experiment/sample_assets/waka_ifont.mp4` を品質処方ONで再生成（quiz_ifont は自然韻律
    モードなので対象外・未変更）
- **検証結果**（waka=百人一首17番ちはやぶる、31モーラ全実測、scratchpadの
  measure_waka_before/after.py）:
  - 「みずくくる」の く(モーラ26): -47.1dBFS・有声0フレーム → **-23.7dBFS・有声13/20**（無声化根治）
  - F0最大偏差: +60セント(ず) → 30セント（許容内）
  - モーラ音量範囲: 26.9dB → **4.2dB**（mp4のAAC経由でも同値を確認）
  - `--raw-voice`（旧経路）の後方互換もOK
- **未コミット**: 上記すべて（ユーザーの試聴確認待ち）

### 次にやること
1. ユーザーが waka_ifont.mp4（新）を試聴して確認 → OKなら commit+push
2. 残りの連続合成課題: `build_karuta_samples.py` を `quality.py` を使う形に共通化するか検討
   （現状は同等処方の独立実装が残っている。動作は正常なので急ぎではない）
3. Kikiwake実読み（sounds_Inaba/kimoto、**読み取り専用**）との韻律突き合わせ検証は未着手

### 技術的な決定と理由
- 処方は `synth_voicevox_designed` 内（audio.py）に組み込み、CLI/MCP両方が自動で恩恵を
  受ける形にした。自然韻律モード(`--natural`)は「VOICEVOXの自然な読みのまま」が意図なので
  処方を適用しない
- parselmouth無し環境ではF0適合のみスキップ（強制有声化・音量ならしは純numpy/標準lib）。
  numpyも無ければ素の合成にフォールバック（依存を増やさない）
- 減衰付き逆補正(damp=0.55)はVOICEVOXのF0応答が非線形（等倍補正だと発振）のため。
  build_karuta_samples.py の実証値をそのまま採用

### 環境（このMac）
- Python venv: `~/ifont_env`（numpy・parselmouth・Pillow入り、ifont は editable install済み）
- VOICEVOX ENGINE 0.25.2: `~/ifont_env/voicevox_engine/run` で起動（ポート50021、
  東北きりたん=speaker 108）。導入記録は同ディレクトリの INSTALL_NOTES.md
- before/after計測スクリプトと音声はセッションscratchpad（一時領域）にあり。恒久化するなら
  experiment/tools/ へ移す

### ハマりポイント
- waka_ifont.mp4 の生成条件は ifont_tool/README.md の実声かるた読み例そのもの
  （1280x720・ラベルなし）。再生成時はこのコマンドを使う
- 「みずくくる」の無声化はVOICEVOXクエリの母音大文字化（無声化マーク）が原因。
  母音を小文字に置換すると強制有声化できる

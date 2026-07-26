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

## 2026-07-25 実読み(木本)の伸ばしに合わせたかるた読み + 伸ばし・余韻の処方追加

### やったこと
- Kikiwake の木本実読み「ちは 上/下」(読み取り専用)から伸ばし方を実測:
  MFA(mfa_v3/onset_extracted_v3.json、歌17)+自前の音響分析(スロット別RMS・F0)。
  結果: るー0.85s・ずー0.75s+休止0.45s・上句末わー0.95s / にー0.90s+休止0.45s・
  最終わー(余韻)2.9s。基調モーラは0.17-0.32s
- これを --durations/--pause-after に翻訳して合成したところ、**新しい欠陥**が発覚:
  VOICEVOX は0.5秒超の持続母音を保てない(かすれ→無声化)。特に「ワ」のE4持続は
  114Hzのボーカルフライに落ちる(B3なら健全。実測で確認)
- **処方を quality.py / audio.py に追加**(コミット対象):
  1. 0.55s超のモーラは「本体0.35s+ー継続(各0.5s以下)」に自動分割。ーは読みテキストに
     挿入して audio_query に解釈させる(手製モーラ辞書はエンジンが無視する。ハマった)
  2. 伸ばし部分は安全音高(260Hz以下)で合成し、PSOLA で設計音高へ載せ替え
     (quality.psola_contour。build_karuta_samples.py の余韻処理の一般化)
  3. ー継続部は F0適合の採点・補正から除外(無声判定でworst=999にロックするため)、
     音量ならしの節点からも除外(余韻の自然減衰を壊さないため)
  4. 最終モーラの余韻: -25セント下降 + -12dB減衰
- 検証(waka_kimoto_style): 全伸ばしが有声(最終わー 266/270fr)・E4±2c・
  余韻 -22.7→-37.9dB の滑らかな減衰
- 再現コマンドは scratchpad の実行履歴と下記パラメータ:
  durations "0.22,0.24,0.19,0.26,0.85,0.17,0.19,0.20,0.28,0.16,0.32,0.75,0.27,0.27,0.27,0.12,0.95,0.19,0.19,0.22,0.23,0.25,0.20,0.90,0.23,0.25,0.20,0.20,0.30,0.28,2.90"
  pause-after "11:0.45,16:0.90,23:0.45" (pitch は等速版と同じ B3@0,5,17)
- kimoto流サンプルは exploratory 扱いで sample_assets には入れていない(等速版は
  論文の運用速度デモとして別の意図があるため。差し替えはユーザー/PI判断)

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

## 2026-07-25(続) 木本比較の追い込み: 張り・スライド・余韻形

- ユーザー比較の指摘のうち「テンポ2倍」は比較対象の取り違え(kimoto_kami=上の句のみ6.5s vs
  合成=全体14.7s)。句ごとに揃えると上6.2s/6.2s・下7.5s/7.4sで一致済み
- 実測で確定した真の差: (1)木本は伸ばし中も音量を張り末尾で抜く(合成は即減衰8dB)、
  (2)伸ばし中F0を+25cじわ上げ(合成はフラット)、(3)句頭はスライド上昇(合成は階段)
- 処方v2: quality.shape_region(hold=張り+末尾リリース / yoin=4割保持→対数減衰)、
  elongationsをdict化(points=F0輪郭・env=エンベロープ指定)、句頭B3→E4は次モーラ6割
  時点到達のPSOLAスライドに。適用順を fit→gain→PSOLA→shape に変更
- v2実測: 冒頭266→295→325Hzスライド・るー328→333のじわ上げ・余韻-24,-25,-26,-32,-38
- 未解決(構造的): 子音の立ち上がりの鋭さ(VOT処方の連続版・未着手)、マイクロプロソディ
  (自然なゆらぎ)の欠如。披講の伸ばしは歌に近く、歌声合成(NEUTRINO/Sinsy、
  プロジェクトログ2026-06に選択肢(i)として記載あり)の方が土俵として適する可能性

## 2026-07-26 歌声合成(VoiSona/知声)の試作 — 伸ばし問題の構造的解決の検証

- ユーザー要望で VoiSona 標準シンガー「知声(Chis-A)」を試行。VoiSona は CLI/API の
  ない GUI 専用のため、(1)こちらで MusicXML 生成(project/voisona/chihayaburu_chisa.musicxml、
  tempo60で音価=秒、木本実測タイミング・B3/E4・読み仮名歌詞) → (2)ユーザーが VoiSona で
  WAV 書き出し(+.lab 音素ラベル) → (3)以降は自動、の半自動フロー
- 実測結果(0_chihayaburu_chisa.wav、Desktop/ifont_listen・ローカルのみ):
  - 31モーラ全一致・内容約14.1s(設計14.05s とほぼ一致。末尾に無音パディングで全長30s)
  - E4モーラは±10c内、句頭B3も設計通り。フレーズ頭は低めから上がる自然なポルタメンタが
    勝手に付く(木本の「からくれ」214→341Hz のスライドと同型)
  - 伸ばし: るー0.8s・最終わー2.97s とも音量-21〜-24dBで張ったまま持続、F0±0c。
    **VOICEVOXで4段の処方(ー分割・安全音高・PSOLA・shape)が必要だった性質が素で出る**
- .lab の音素境界からモーラonsetを取り、render_frames_gated で字幕同期した
  waka_chisa.mp4 を生成(scratchpad と Desktop/ifont_listen)
- 音声・labは知声の利用規約(クレジット「VoiSona:知声」等)配慮で git には入れない
- 含意: 披講用の製品音声は歌声合成が土俵として適切。完全自動化が要るなら
  NEUTRINO/Sinsy(CLI あり)が候補。実験刺激・等速提示は VOICEVOX 凍結インベントリのまま

## 2026-07-26(続) 知声への木本韻律の完全転写

- 「もっと木本に近づけられるか(タイミングなど)」→ 韻律転写を実装。木本実読みの
  (1)F0輪郭 (2)音量エンベロープの形 (3)モーラ長・休止長 をモーラ対応のタイムワープで
  知声WAVへ PSOLA 転写(parselmouth Manipulation: DurationTier+PitchTier+ゲイン)
- 結果: モーラ長誤差 中央値0ms・最大74ms(木本の「が」70msにレート下限0.6が当たる箇所のみ)、
  伸ばしF0 341→346Hz のじわ上げ・余韻の減衰カーブも木本の実測形そのまま
- 成果物: waka_chisa_kimoto.mp4 / chisa_kimoto_full.wav (Desktop/ifont_listen)、
  境界 project/voisona/chisa_full_moras.json、手順 project/voisona/README.md
- 残る差: 声質(知声そのもの)と子音の質(転写は母音・韻律のみで分節音は知声のまま)

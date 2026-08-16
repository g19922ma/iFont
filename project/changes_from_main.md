# 先生の実装(main)から変えたものリスト

> 栗原先生への提出用。丸山ブランチ(maruyama/font-exploration)が先生の main に対して
> 「先生のファイルに手を入れたもの」と「新しく足したもの」の一覧。
> 変更のたびにこのファイルへ追記する。公開確認用URL: https://g19922ma.github.io/iFont/
> (最終更新: 2026-08-16)

## A. 先生のファイルに手を入れたもの（レビュー必須）

### experiment/prod_common.js（本番共通配管）
1. **Firestore 二重書き込み** — GAS は同時実行30本の上限があり混雑時に取りこぼす恐れが
   あるため、Firestore にも並行保存（`FIREBASE` 定数、未設定なら何もしない）。
   手順書: docs/FIREBASE_SETUP.md。解析は Firestore を正、GAS を照合用とする想定。
2. **再生機器の申告と無線ブロック** — 同意画面にスピーカー／有線／無線の3択を追加。
   無線(Bluetooth)は音の頭が欠けるため選択中は開始不可。選択は全回答レコードに
   `audio_device` として記録（層別解析用）。聴覚課題のみ表示。
3. **途中再開（同じブラウザ）** — 進行状況を localStorage に保存し、タブ誤閉じ・
   クラッシュ時に同じブラウザで開き直せば続きから再開できる。`PROD.loadState/saveState/
   clearState`。保存期限60分（Yahoo側の制限時間と同値にする前提・発注時に要同期）。
   参加者ID・完了コードも引き継ぎ、完了後は完了コードの再表示のみ。
   再開回数 `resume_count`・中断合計秒 `resume_gap_s` を全送信レコードに付与。
   同意画面に「進行状況の記録はお使いのブラウザ内にのみ保存され、外部には送信されません」を
   1行追記（再開つきページのみ。frac課題ページの同意画面は不変）。

### experiment/pilot_soa_audio.js / pilot_soa_visual2.js（乙課題・聴覚/視覚）
4. **回答の確認画面** — かな表クリックで即確定だったのを、「選択済み表示 → 1つ目を直す／
   2つ目を直す／これで決定」に変更。記録・送信は「これで決定」時のみ。
   記録される列の構成は不変。刺激・タイミング・練習の流れも不変。
5. **端末環境と所要時間の送信** — 完了レコードに env（ua/dpr/screen/touch/refresh_hz）と
   duration_s を載せる（GAS 新版の列挙に対応）。
6. **途中再開の組み込み（本番モードのみ）** — 1問確定ごとに途中状態（出題順・回答済み・
   何問目か）を保存。再開時は保存済みの出題順をそのまま続行（順番は作り直さない）。
   練習と本番前確認はとばし、教示画面に再開の案内を表示。研究者モード(?prodなし)は不変。

### gas/code.gs（保存サーバ）
7. **列の追加** — trials/soa_trials/soa_sessions に `audio_device`。
   soa_trials に `resume_count`、soa_sessions に `resume_count`/`resume_gap_s`。
   いずれも先生の258行版の構造・記法（blank()）に合わせて追記。
   ※シートのヘッダは新規作成時のみ書かれるため、**デプロイ済みシートがある場合は
   列を手で足すか、シートを作り直す必要がある**。

### docs/prereg_interference.md（事前登録ドラフト）
8. 機器ポリシーの文言を「スピーカー・有線OK／無線不可・3択申告・機器別の層別解析」に差し替え。

## B. 新しく足したもの（先生のファイルは触っていない）

- **docs/FIREBASE_SETUP.md** — Firestore 設定10分手順（create-onlyルール込み）
- **docs/launch_readiness.md** — 発注前チェックリスト（Stage1/2の全ゲート）
- **experiment/tools/kana_segment_pilot.html + build_kana_segment_pilot.py** —
  か行5択セグメント実験の環境（子音/母音の倍率×打ち切りゲート）
- **experiment/tools/rsvp_proto.html** — RSVP 7方式の試し場（先生の「残存」要因の原型）
- **experiment/tools/pscore_demo.py / pscore_editor.html / pscore_server.py** —
  Perceptual Score デモ（手描きカーブ→音声+iFont合成）
- **ifont_tool/ifont/quality.py + audio.py/cli.py の拡張** — 品質処方（強制有声化・
  F0適合・音量ならし・伸ばし対応）。`--raw-voice` で旧挙動。先生の `--slot-ms` 系とは共存
- **project/** — スケジュール、概念整理メモ、VoiSona試作、本リスト

## C. 未設定のまま先生の判断待ちのもの

- prod_common.js の `SUBMIT_URL`（GASデプロイURL）と `FIREBASE`（projectId/apiKey）は空
  → 空のままでも画面は動くが送信はされない。発注前に要設定
- GAS 新列のデプロイ（A-7の注意）
- 再開の保存期限60分と Yahoo 制限時間の同期（発注画面で設定するときに合わせる）

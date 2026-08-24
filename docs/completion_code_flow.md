# iFont 実験 — 完了コード照合フロー 手順書

> **この文書は転写検証実験（2026-08〜）に対応する。旧版（〜2026-06-06）は
> 別実験（乙課題・frac課題／Yahoo!クラウドソーシングの旧掲載・`experiment/experiment.js`・
> `gas/code.gs` 基準）の内容だった。完了コードの桁数・問題数・保存先・回答UIなど
> ほぼすべての数値が転写検証実験とは異なるため、全面的に書き直した。**
>
> - 対象実験: 転写検証実験（`experiment/transfer_calib.html` / `transfer_test.html` = 群 acal・aprime・b、
>   `experiment/transfer_comfort.html` = 群 C）
> - 実装根拠: `experiment/prod_common.js`（完了コード生成・同意画面・完了画面の共通部品）、
>   `experiment/transfer.js`・`experiment/transfer_comfort.js`（群ごとの記録・完走レコード）、
>   `experiment/transfer_firestore.js`（Firestore 保存先）、`gas_transfer/code.gs`（GAS 側の切り戻し先）
> - 関連: [informed_consent.md](./informed_consent.md)、`project/掲載前チェックリスト.md` の J 節（完走レコードと承認の判定）
> - 最終更新: 2026-08-22

---

## 1. 全体フロー（エンドツーエンド）

```text
[参加者ブラウザ / prod_common.js]
  (1) ページ読み込み時に 12桁ランダム完了コードを生成
       └ 文字種: A-Z + 2-9(紛らわしい I, L, O, 0, 1 を除外・30種)。群による接頭辞は無い
  (2) 各設問の回答ごとに Firestore(主)/GAS(切り戻し用)へ送信
       送信内容: participant_id, worker_id, completion_code, stimulus_id,
                 target_char, response_char, correct, rt_ms, phase, group, ...
  (3) 最後の設問に答えたあと、「完走レコード」(record_kind="session")を1行送る
  (4) 完走レコードの送信を待ってから、完了画面に完了コードを表示
       （群C はさらに、直前に送る「本記録」(record_kind="final")の送信成功も待つ。
        本記録が送れない場合は完了コードの前に再送画面を挟む。§2-(3) 参照）
        │
        ▼
[参加者]
  (5) 完了コードをコピーし、Yahoo!クラウドソーシングの回答欄に貼付・提出
        │
        ▼
[Firestore(主) / スプレッドシート(GAS・切り戻し時)]
  (6) コレクション transfer_trials に 1設問=1行、transfer_wellbeing に
      見え心地の回答・完走レコードなどを記録
        │
        ▼
[研究側 = あなた]
  (7) 回答欄の完了コードで transfer_wellbeing の record_kind="session" 行を検索 → 一致確認
  (8) n_trials・send_failures 等を見て完走を確認(§4)
  (9) Yahoo!管理画面で 承認 / 否認
```

**ポイント:** 完了コードは参加者の手元(完了画面)と、研究側の保存先(各行の `completion_code` 列)の
**両方に同じ値が存在**します。承認の判定は「全部の行を集計する」のではなく、
**`record_kind="session"` の完走レコード1行だけ**で行います(§4)。これが従来手順との最大の違いです。

---

## 2. 各段階の詳細

### (1) 生成 — `experiment/prod_common.js:44-47`

```js
const CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
let completionCode = Array.from({ length: 12 },
  () => CODE_CHARS[Math.floor(Math.random() * CODE_CHARS.length)]).join("");
```

- ページ読み込み時にブラウザ側で **12文字のランダム完了コード** を生成(旧版は16文字)。
- 文字種は30種(`ABCDEFGHJKMNPQRSTUVWXYZ23456789`)。読み間違いやすい I・L・O・0・1 を除外する方針は旧版と同じ。
- **群(acal/aprime/b/C)による接頭辞は付かない。** コードだけを見て集団は判別できない
  （集団は `phase`/`group` 列など、コードとは別の列に記録される）。
- 同時に `worker_id` を URL クエリ(`?worker_id=` / `?wid=` / `?worker=`)から取得。無い場合は
  `anon-xxxxxxxx` を自動採番(`prod_common.js:42-43`)。
- 同じブラウザで再開した場合(`loadState`, `prod_common.js:61-78`)は、保存済みの
  `completion_code` を引き継ぐ(再開のたびにコードが変わらないようにするため)。

### (2) 表示 — 完了画面 `experiment/prod_common.js:236-245`(`completionHTML`)

- 完走時に最後の画面で完了コードを大きく表示し、コピー用ボタンを添える。
- 参加者IDと所要時間(秒)も併記。
- **研究者モード(URLに `?prod=1` が無い)では完了コードを表示しない。**
  送信自体が行われないため、コードを出しても照合できず非承認の原因になるからである
  (`transfer.js:1468-1470` のコメント参照)。
- 途中離脱すると完了画面に到達せず、コードは案内されない。

### (3) 記録の送信 — `experiment/transfer.js` / `experiment/transfer_comfort.js`

保存先は **Firestore が主、GAS(`gas_transfer/code.gs`)は切り戻し用**(`experiment/transfer_config.js` の
`backend.roster` / `backend.logging`。既定は両方 `"firestore"`、`fallback: true` で主が失敗したときだけ
もう一方を試す)。切り戻す場合はこの2行を `"gas"` に変えるだけでよい設計になっている
(`transfer_config.js:117-119` のコメント)。

> **【要確認】** `gas_transfer/code.gs` はリポジトリ内では `transfer_trials` / `transfer_wellbeing` /
> `transfer_roster` の書き込みに対応済みだが、**実際にデプロイされている Apps Script の版が
> このファイルと一致しているか**は、`transfer_config.js` の `roster.status_url` / `logging.submit_url`
> の `/exec` URL を直接確認しないと分からない。切り戻しを使う前に一度動作確認すること。

送られるレコードには3種類ある(群 acal・aprime・b と、群Cで扱いが少し異なる)。

**acal・aprime・b(識別課題そのものの群)**

| 種類 | `kind` | 保存先コレクション/シート | 内容 |
|---|---|---|---|
| 1設問1行 | (無し) | `transfer_trials` | 毎設問。`target_char`・`response_char`・`correct`・`rt_ms` など(`transfer.js:1104-1125` `makeRecord`) |
| 完走レコード | `transfer_wellbeing` | `transfer_wellbeing`(`record_kind="session"`) | 最後の設問のあと1行だけ(`transfer.js:422-435` `sessionRecord`)。送信は待つが、**失敗しても完了コードは出す**(`transfer.js:1452-1466` `showResults`)。1設問1行の記録に同じ完了コードが入っているため、照合の手がかりが完全には失われない |

**群C(見え心地評価。`experiment/transfer_comfort.js`)**

| 種類 | `record_kind` | 内容 |
|---|---|---|
| 途中の保険(1本ごと) | `clip`(12行/人) | 7件法の回答のたび。分析には使わない保険用(`transfer_comfort.js:329-345` `sendClipRecord`) |
| 本記録 | `final`(1人1行) | 実際の評価データ(`transfer_comfort.js:1000-1014`)。**送信成功を待ってから完了コードを出す**。失敗時は3段構え: ①作り直して再送 → ②それでも駄目なら「送れませんでした・再送する」画面 → ③手動再送も駄目なら、完了コードは出したうえで「このコードと時刻を控えて問い合わせて」と案内する(`transfer_comfort.js:996-1025` `submitAndFinish`) |
| 完走レコード | `session`(1人1行) | `final` の送信成功後に送る(`transfer_comfort.js:1038-1042` `finishUp`)。こちらは他の群と同様、失敗しても完了コードは出す |

いずれも `completion_code` / `participant_id` / `worker_id` / `ts` は共通の組み立て関数
(`transfer.js:322-334` `serverBody`)が自動で付与するので、**個別のレコードで付け忘れることは無い**。

### (4) 貼付 — 参加者

- 参加者が完了コードをコピーし、Yahoo!クラウドソーシングの回答欄に貼り付けて提出。

---

## 3. 保存先の実体

### Firestore(主)

プロジェクト `ifont-transfer`(`experiment/transfer_config.js` の `firestore.project_id` を参照。
接続設定・ルールの詳細は `docs/FIRESTORE_TRANSFER_MIGRATION.md`)。コレクションは4つ
(`experiment/transfer_firestore.js:24-29`)。

| コレクション | 内容 | 1参加者あたりの行数 |
|---|---|---|
| `transfer_trials` | 1設問1行の回答(acal・aprime・b) | 68〜108行(§5) |
| `transfer_wellbeing` | 群Bの見え心地評価(旧方式に戻した場合のみ)・群Cの評価・**全群共通の完走レコード** | 群による(§2-(3)参照) |
| `transfer_roster` | 名簿。1参加者1件。ドキュメントIDは `"<フェーズ>_<参加者ID>"` | 1 |
| `transfer_counters` | 集団ごとの通し番号の採番のみ | — |

どのコレクションに入るかは `kind`/`modality` 列で自動的に振り分けられる
(`transfer_firestore.js:325-329` `collectionFor`。`kind==="transfer_wellbeing"` またはその `modality` なら
`transfer_wellbeing` へ、それ以外は `transfer_trials` へ)。

認証は行わない(参加者にログインさせると同意より前に個人を識別することになるため)。
書き込み範囲は Firestore のセキュリティルールで絞ってあり、「作れるだけ・回答は読めない・消せない」設計
(`transfer_firestore.js` 冒頭コメント参照)。

### GAS(`gas_transfer/code.gs`。切り戻し用)

- スプレッドシートの `transfer_trials` / `transfer_wellbeing` / `transfer_roster` の3シートに、
  Firestore と同じ内容を追記する(`gas_transfer/code.gs:345`, `:468-515`, `:517-539` 付近)。
- `transfer_wellbeing` シートは `record_kind` 列で3種類(`""/"final"`・`clip`・`session`)を見分ける設計に
  なっている(`gas_transfer/code.gs:520-527` のコメント)。
- 旧実験(乙課題・frac課題)の `trials` / `soa_trials` / `soa_sessions` シートの処理も同じファイルに残っている
  (これらは転写検証実験とは無関係)。

---

## 4. 承認の判定手順(実務ステップ)

> `project/掲載前チェックリスト.md` の J 節（完走レコードと承認の判定）に対応する。

### Step 1. 完走レコードで判定する(1問1行の記録から推測しない)

- 承認の判定は **`transfer_wellbeing` コレクションの `record_kind="session"` の行だけ**で行う。
- **1設問1行の記録(`transfer_trials`)の行数から「完走したか」を推測してはいけない。**
  通信が悪くて一部の設問が届かなかっただけの人まで、未完走として否認してしまう恐れがあるため。

### Step 2. 完了コードで検索

1. Yahoo!管理画面で参加者が提出した完了コードを1件取得。
2. `transfer_wellbeing` コレクションで `completion_code` が一致し、かつ `record_kind="session"` の行を検索。
3. 判定:
   - **一致あり** → Step 3(内容確認)へ。
   - **一致なし** → 群C以外はここで否認候補(完了コード不一致・未完走の疑い)。
     ただし群Cは、完了コードが出たのに本記録(`record_kind="final"`)の送信が
     最後まで失敗しているケースがありうる(§2-(3)の③)。参加者から「コードは出たが
     送れなかったと言われた」という問い合わせが来た場合は、**申告されたコードと時刻**で
     `clip` レコードや `transfer_roster` を照合して個別に確認する。

### Step 3. 内容の確認

`record_kind="session"` の行には以下が入っている(`transfer.js:422-435`, `transfer_comfort.js:348-361`)。

| 列 | 意味 |
|---|---|
| `phase` / `group` | どのフェーズ・どの集団か(acal/aprime/b/comfort など) |
| `n_trials` | 答えた設問数(練習を除く) |
| `duration_s` | 同意画面から完了コードまでの所要秒 |
| `send_failures` | 最後まで送れなかった1設問1行の記録の件数(0なら取りこぼし無し) |
| `send_retries` | 作り直して送れた件数(サーバの調子を後から見るための参考値) |

- **`send_failures` が0でない人を数え、掲載後に必ず確認する。** 多いようなら通信基盤側の問題であり、
  **本人の落ち度ではないため報酬は支払う**(`project/掲載前チェックリスト.md` J-2)。
- `n_trials` が想定の問題数(§5)から大きく外れている場合は、途中で条件が変わった・
  出題の組み立てに問題があった等の可能性があるため個別に確認する。
- **【要確認】** キャッチ設問(`is_catch` 列。全部見せ/全部聞かせの確認問題)の正答率や
  回答時間による品質フィルタ(閾値)は、旧版の80%・300〜8000msのような**転写検証実験専用の
  確定値としては見つからなかった**。否認判定にこうした基準を使うかどうかは、
  掲載前に研究代表者と確定すること。

### Step 4. 承認/否認(Yahoo!管理画面)

- 完走レコードが一致し、明らかな異常が無い → **承認**。
- 一致しない、かつ§2の個別確認でも特定できない → **否認候補**。
- 処理結果(承認/否認・理由・日時)を管理シートなどに記録しておくと監査・再発防止に役立つ。

---

## 5. 問題数・所要時間・報酬(現行値)

| 集団 | 課題 | 1人あたりの問題数 | 内訳 |
|---|---|---|---|
| acal(較正・聴覚) | かなの聞き取り | **108問** | ターゲット64＋まぎれ字32＋確認問題12 |
| aprime(較正・視覚) | かなの見分け | **68問** | ターゲット40(4方式×1字×5水準×2速度)＋まぎれ字20＋確認問題8 |
| b(検証・視覚) | かなの見分け | **94問** | ターゲット56＋まぎれ字28＋確認問題10 |
| C(見え心地評価) | 4方式×3通り＋ステップ表示(1字)の視聴＋評価 | **13本** | `experiment/transfer_comfort_config.js` の families / presentations_by_family |

(`node experiment/tools/check_transfer_stimuli.js` で検算可。2026-08-22時点の出力で上記を確認済み)

- 回答UIは五十音表(かな表)からの選択。ターゲット・まぎれ字を合わせた **68択**(旧版の「4つの候補」ではない)。
- 回答時間の制限は無い(旧版の「5秒以内」という記述は誤り)。
- 所要時間はWORKLOGの実測・下見に基づく目安として、較正フェーズ(acal/aprime)約10〜12分、
  群C約7分(`WORKLOG.md` 1313行台・1875行台、`project/実験計画書_転写検証.md:502`)。
  **【要確認】** 計画書上は「未確定」の記述も残っており(`project/実験計画書_転写検証.md:709`)、
  掲載前に最終値を確定すること。
- 報酬は目安として200円(較正・検証フェーズ)、群C 120円(`WORKLOG.md` 1875行台、
  `project/掲載前チェックリスト.md:16`)。**【要確認】** こちらも計画書上は「未確定・要ユーザー判断」
  (`project/実験計画書_転写検証.md:708-709`)であり、旧版の「360円・PayPayポイント」の記述はこの実験には
  当てはまらない。支払い方式(PayPayポイント等)も含めて掲載前に確定すること。

---

## 6. なりすまし・二重応募・コード使い回しへの対策メモ

- **コードとデータの突合を必須化** — 提出コードが `transfer_wellbeing` の `record_kind="session"` 行として
  存在し、かつ対応する `transfer_trials` の行(または群Cの `final`/`clip` 行)を伴うことを確認する。
- **コードは1人1回のみ有効** — 同じ完了コードが複数の応募で提出された場合、2件目以降は否認候補。
- **名簿(`transfer_roster`)で重複参加を防ぐ** — 較正フェーズと検証フェーズは互いに独立の集団として
  扱われ、名簿に既に載っている参加者IDが再度来た場合は「以前の関連実験に参加済み」として
  お断り画面を出す(`transfer.js:1725-1752` `blockedScreen`)。この場合は完了コード自体が出ないため、
  そもそも報酬照合の対象にならない(お断り画面には「以前ご参加いただいた分の報酬には影響しません」と明記)。
- **コード生成はサーバ管理ではなくクライアント生成** — 現実装はブラウザ側生成のため、理論上は参加者が
  偽コードを作れる。ただし偽コードは保存先のレコードと一致しないため、突合で排除できる。
- **【要確認】** 再応募不可設定(プラットフォーム側の「同一作業者の再応募制限」)を有効化しているかどうかの
  最新の確認記録は見当たらなかった。

---

## 7. 不一致時の対応・付録

不一致時の問い合わせ文面テンプレは旧版(§6・§6-1〜6-3)から流用できるが、
「16桁」は「12桁」に、「200問」は集団ごとの問題数(§5)に書き換えて使うこと。
**転写検証実験専用の確定文面は現時点では無いため、掲載前に作成すること【要確認】。**

*本手順の品質フィルタ閾値・報酬額・所要時間の最終値・GASデプロイ版の一致確認は、
公開前に研究代表者と確定してください。*

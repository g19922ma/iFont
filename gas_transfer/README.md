# gas_transfer/ — 転写検証実験のサーバ側（Google Apps Script）

転写検証実験（`experiment/transfer_calib.html` / `transfer_test.html`）の記録と、
参加者の集団の振り分けを受け持つ Apps Script プロジェクト。`clasp` で出し入れする。

**既存の実験（乙課題・frac課題）のサーバとは別物**。既存のものは `gas/code.gs` のままで、
このディレクトリは触らない。

## 中身

| ファイル | 何か |
|---|---|
| `code.gs` | 本体。`gas/code.gs` に `gas/transfer_patch.md` の3差分を当てたもの |
| `appsscript.json` | 実行環境の設定。タイムゾーンは Asia/Tokyo、ウェブアプリは「全員（匿名を含む）」がアクセスでき、実行者はデプロイした本人 |
| `.clasp.json` | どのスクリプトプロジェクトに繋がっているか（`scriptId`）と、紐づく スプレッドシート（`parentId`）。**秘密の値ではない** |

`code.gs` が `gas/code.gs` に何を足したかは、次のコマンドで一目で分かる。

```bash
diff gas/code.gs gas_transfer/code.gs
```

足したものは4つ。

1. **保存先シートIDの定数化** — スクリプトプロパティではなく `SPREADSHEET_ID` に直書き。
   clasp から一発で入れ直せるようにするため（このスクリプトは転写検証専用のシートに
   紐づいているので、シートIDが1つに決まる）。
2. **`handleTransferTrial`** — 1問1行を `transfer_trials` シートへ。採点はブラウザが
   申告した `target_char` で行う（刺激をブラウザ側で合成する課題では正解表を持てないため。
   視覚1文字課題と同じ契約）。
3. **`handleTransferWellbeing`** — 見え心地の評価を `transfer_wellbeing` シートへ1参加者1行。
4. **`doGet` の差し替え** — 集団の振り分け（`transfer_status`）と、疎通確認用の
   `transfer_health` / `transfer_purge_test`。

## いまの繋ぎ先（下見用）

| 何 | 値 |
|---|---|
| スプレッドシート | `1gsJ6_Rucv5uoKsgrs_m-Y41sxh5B0qcPKWyHkxveKMs` |
| デプロイID | `AKfycbw1bnn7H3HCYuD3fDUIi1djGcnea0cVqnA15XiN5ipgwlrsCNkQx4q16-bdN0wbGQRP` |
| `/exec` URL | `https://script.google.com/macros/s/AKfycbw1bnn7H3HCYuD3fDUIi1djGcnea0cVqnA15XiN5ipgwlrsCNkQx4q16-bdN0wbGQRP/exec` |

**本番では、下見の記録と混ぜないために新しいスプレッドシートで作り直す**
（手順は `project/掲載前チェックリスト.md` の G-1）。

## 直したときの入れ直し方

```bash
cd gas_transfer
clasp push -f
clasp deploy -i AKfycbw1bnn7H3HCYuD3fDUIi1djGcnea0cVqnA15XiN5ipgwlrsCNkQx4q16-bdN0wbGQRP -d "説明"
```

- デプロイIDを変えなければ `/exec` URL は変わらない。
- **`clasp push` だけでは公開版に反映されない**（`@HEAD` が変わるだけ）。必ず `clasp deploy`
  までやる。直したつもりで古い版が動き続ける事故が起きやすい。
- 文法だけ手元で見たいときは `cp code.gs /tmp/c.js && node --check /tmp/c.js`。

## 最初に1回だけ必要な「利用許可」

clasp で作ったスクリプトは、持ち主が一度も許可を与えていないので、そのままでは
スプレッドシートを読み書きできない。`/exec` を開くと `Authorization needed` が出て
HTTP 403 になる。**ブラウザで `/exec` を開き、「REVIEW PERMISSIONS」→ アカウント選択 →
（未確認アプリの警告が出たら「詳細」→「移動」）→「許可」** を1回押せば通る。
デプロイを作り直したときも、もう一度必要になることがある。

## 疎通確認の窓口

| URL | 返すもの |
|---|---|
| `<exec>` | `{"status":"ok","message":"iFont experiment endpoint"}` |
| `<exec>?action=transfer_status&phase=calib&participant_id=xxx` | その人の集団と連番。前のフェーズに出ていれば `blocked` |
| `<exec>?action=transfer_health` | 3枚のシートの行数と、そのうち試し打ちの行数 |
| `<exec>?action=transfer_purge_test` | 試し打ちの行だけ消す |

試し打ちの目印は**参加者IDの頭が `curltest-`**。この接頭辞の行は `is_test` 列に `true` が
立ち、`transfer_purge_test` で消せる。消せるのはこの接頭辞の行だけなので、本物の参加者の
データには手が届かない（クラウドソーシングの作業者IDがこの形になることはない）。

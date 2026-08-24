# Firebase Hosting 移行手順

実験ページの配り先を、GitHub Pages（`https://g19922ma.github.io/iFont/experiment/...`）から
Firebase Hosting（`https://kana-task.web.app/...`）へ移すための手順書。

**この文書を書いた時点では、まだデプロイしていない。**
「ん」の問題が片づいてから、下の「3. デプロイする」を実行する。

---

## 0. なぜ移すのか

いまの配り先の URL には、GitHub のアカウント名（`g19922ma`）とリポジトリ名（`iFont`）が
そのまま入っている。参加者が URL を見てリポジトリをたどると、

- 旧課題の正解表（`experiment/answer_key_merged.json`）
- 実験計画書・掲載文・解析（`project/` の中身）
- 論文の草稿（`paper/`）

まで読めてしまう。参加者が答えを先に見られるだけでなく、
「何を測られているか」を知ったうえで課題に臨むことになり、データの質が落ちる。

Firebase Hosting に移すと、URL は `https://kana-task.web.app/listen` のようになり、
**研究名もアカウント名も出ない**。さらに、公開するのは実験に必要な 642 ファイルだけで、
リポジトリの他の部分はそもそもサーバに載らない。

---

## 1. URL 一覧（移行後に参加者へ渡すもの）

サイト名は **`kana-task`**。「iFont」という研究名を URL から消すために選んだ
（2026-08-24 に丸山が決定。Firebase 上で作成済み）。

| 掲載 | 集団 | 新しい URL | 中身のファイル |
|---|---|---|---|
| 較正・聞き取り（250円） | 群Acal | `https://kana-task.web.app/listen?prod=1&wid=<作業者ID>` | `transfer_calib_audio.html` |
| 較正・見え方（130円） | 群A′ | `https://kana-task.web.app/look?prod=1&wid=<作業者ID>` | `transfer_calib_visual.html` |
| 検証 | 群B | `https://kana-task.web.app/read?prod=1&wid=<作業者ID>` | `transfer_test.html` |
| 見え心地のアンケート | 群C | `https://kana-task.web.app/survey?prod=1&wid=<作業者ID>` | `transfer_comfort.html` |
| （掲載しない・研究者の確認用） | 振り分け版 | `https://kana-task.web.app/check?prod=1&wid=uitest-...` | `transfer_calib.html` |

短い名前（`/listen` など）は `firebase.json` の `rewrites` で本当のファイル名に読み替えている。
**ファイル名そのままの URL も動く**（`https://kana-task.web.app/transfer_calib_audio.html`）。
掲載に貼るのは短いほうでよいが、貼り間違えると別の集団の課題を出すことになるので、
掲載前に下の「4. 掲載前の確認」で中身を必ず照合すること。

> ⚠ `/look`（群A′・視覚の較正）と `/read`（群B・視覚の検証）は**どちらも見る課題**で紛らわしい。
> 貼るときは表の行をそのままコピーし、目視で1回照合する。

サイトの入口（`https://kana-task.web.app/`）は **わざと 404 にしてある**。
一覧ページを置くと、そこから他の課題へたどれてしまうためである。

---

## 2. 公開されるもの・されないもの

### 仕組み

`experiment/` を丸ごと公開すると、公開してよいのは 7.7MB なのにフォルダ全体は
**167MB** あり、その中に正解表・解析スクリプト・採用しなかった音源が混ざっている。
Firebase の設定（`firebase.json`）には**除外リストしか書けない**ので、
書き漏らし1行で正解表が公開されてしまう。

そこで、**要るものだけを別のフォルダにコピーして、そこを公開する**方式にした。

```
experiment/  ──[ build_hosting.sh が必要なものだけコピー ]──▶  hosting_dist/  ──[ firebase deploy ]──▶  kana-task.web.app
（167MB・非公開）                                              （7.7MB・これだけ公開）
```

- コピーするスクリプト: `experiment/tools/build_hosting.sh`
- コピー先: `hosting_dist/`（リポジトリ直下。`.gitignore` 済み。中身は全部コピーなので git に入れない）
- `firebase.json` の `"public": "hosting_dist"` がこのフォルダを指している

> ⚠ **`.gitignore` は Firebase には効かない。** git に入れていない手元だけのファイル
> （話者候補の合成音など）も、公開フォルダに置いてあればアップロードされる。
> この点でも「必要なものだけコピー」のほうが安全である。

### 公開されるもの（642ファイル・7.7MB）

| もの | 中身 |
|---|---|
| `transfer_calib_audio.html` `transfer_calib_visual.html` `transfer_test.html` `transfer_comfort.html` | 参加者が開く4つの入口 |
| `transfer_calib.html` | 研究者の確認用（掲載しない） |
| `transfer.css` | 見た目 |
| `prod_common.js` `transfer_config.js` `transfer_firestore.js` `transfer.js` `transfer_comfort_config.js` `transfer_comfort.js` | 動かすための JavaScript |
| `transfer_audio_manifest_amitaro.json` | 音声刺激の索引 |
| `transfer_stimuli_amitaro/`（544ファイル・6.9MB） | 打ち切り済みの音声 |
| `base/`（84ファイル・340KB） | かなの完成形の画像 |
| `robots.txt` | 検索エンジンに全ページを載せないよう指示（ビルド時に作り直す） |
| `transfer_warp.json` | **まだ無い。** 転写（提案手法）の進み方の表 |

音源のフォルダ名と索引ファイル名は、スクリプトが `transfer_config.js` の
`stimuli_dir` / `manifest_url` の値を読んで決める。
**話者を切り替えたときにスクリプトを直す必要はない**（設定を直せば追随する）。

### 公開されないもの（意図的に外したもの）

| 外したもの | なぜ |
|---|---|
| `experiment/answer_key_merged.json`（1.3MB） | **旧課題の正解表**。git に入っているので、リポジトリが見えると読めてしまっていた |
| `experiment/tools/`（65ファイル） | 解析スクリプト・下見のデータ・検定力の計算 |
| `experiment/transfer_stimuli/` `transfer_stimuli_kanon/`（21MB） | 採用しなかった音源（丸山の肉声・花音） |
| `experiment/transfer_audio_manifest.json` `..._kanon.json` `transfer_onsets_*.json` `transfer_warp_demo.json` | 同上の索引・試作 |
| `experiment/PRODUCTION.md` | 配信の手引き。旧サイトの URL が書いてある |
| 旧実験の一式（`pilot_*.html/js` `audio*.html/js` `visual*.html/js` `index.html` `ifont_sample.html` `ptuning*` `morph_*`） | 転写検証実験では使わない |
| 旧実験の刺激（`stimuli/` `audio_stimuli/` `audio1char_stimuli/` `audio2char_stimuli/` `audio_base/` `candidate_pools/` `sample_assets/` `ptuning/`） | 同上 |
| `project/` `paper/` `docs/` `recordings_raw/` `gas_transfer/` `gas/` `fonts/` ほかリポジトリ直下の全て | そもそも `hosting_dist/` にコピーしない＝サーバに載らない |

エミュレータで実際に確認済み（2026-08-24）:
`answer_key_merged.json` / `tools/` / `PRODUCTION.md` / `pilot.html` / `index.html` /
`transfer_stimuli_kanon/` / `transfer_audio_manifest.json` / サイトの入口 `/` は
**すべて 404** を返す。

---

## 3. デプロイする

### 3-1. 準備（毎回やる）

```bash
cd /Users/maruyama/Documents/GitHub/iFont

# 1. 最新を取り込む(他の人の変更を混ぜてしまわないため)
git pull --rebase

# 2. 掲載前フラグが false であることを手元で確認
grep -n "^  pre_launch:" experiment/transfer_config.js
#    → pre_launch: false,  でなければ掲載用のデプロイをしない

# 3. 公開するファイルを集め直す
bash experiment/tools/build_hosting.sh
```

スクリプトは最後に「ファイル数・大きさ・直下のファイル一覧」を出す。
**正解表や `.py` `.md` が混ざっていたらその場で止まる**ようにしてある
（名前で見張っているだけの簡単な検査だが、事故はたいていこの形で起きる）。

### 3-2. 手元で見てから上げる（推奨）

```bash
firebase emulators:start --only hosting
# → http://127.0.0.1:5000 などで開いて、4つの入口が正しく出るか見る
# 終わるときは Ctrl-C
```

### 3-3. 上げる

```bash
firebase deploy --only hosting:kana-task
```

> ⚠ **`--only hosting:kana-task` を必ず付ける。**
> 付けずに `firebase deploy` だけ打つと、Firestore のセキュリティルールも一緒に
> 配り直される。ふだんは同じ内容なので実害は出ないが、ルールを触っている途中だと
> 書きかけのルールが本番に載る。

`--project` は省いてよい（`.firebaserc` に `ifont-transfer` を既定として書いた）。
明示したいときは `--project ifont-transfer` を足す。

---

## 4. 掲載前の確認（デプロイのあと・掲載申請の前）

```bash
B=https://kana-task.web.app

# (1) 4つの入口が開くか、そして「どの集団のページか」が合っているか
for p in listen look read survey; do
  echo "--- /$p ---"
  curl -s "$B/$p" | grep -oE "<title>[^<]*</title>|TRANSFER_PAGE = \{[^}]*\}"
done
```

出るべきもの:

| URL | title | 集団の指定 |
|---|---|---|
| `/listen` | ひらがなの聞き取りの課題 | `phase: "calib", force_group: "acal"` |
| `/look` | ひらがなの見え方の課題 | `phase: "calib", force_group: "aprime"` |
| `/read` | ひらがなの聞き取り・見え方の課題 | `phase: "test"` |
| `/survey` | 文字の見え心地についてのアンケート | （指定なし。群Cは1集団だけ） |

```bash
# (2) 配信中のファイルで掲載前フラグが false か(手元ではなく実物を見る)
curl -s $B/transfer_config.js | grep -n "pre_launch"
#   → pre_launch: false,  でなければ掲載しない

# (3) 設定の版が想定どおりか
curl -s $B/transfer_config.js | grep -n "config_version"

# (4) 出してはいけないものが 404 か
for p in answer_key_merged.json tools/ PRODUCTION.md index.html transfer_stimuli_kanon/ ; do
  echo "$p -> $(curl -s -o /dev/null -w '%{http_code}' $B/$p)"   # 全部 404 であること
done
```

**(5) ブラウザで最後まで通す（手作業。これだけは自動化できない）**

`https://kana-task.web.app/listen?prod=1&wid=uitest-fb1` のように、
**作業者IDの頭を `uitest-` にして**開く。この頭の名前が付いた回は
`is_test` の印が付き、本番の連番とは別のカウンタから番号が配られるので、
**本番のデータにも連番にも混ざらない**（`experiment/transfer_firestore.js` の `isTestPid`）。

見るところ:
- 音が鳴るか／文字のアニメが出るか（＝刺激ファイルの参照が壊れていないか）
- 最後まで進んで完了コードが出るか（＝Firestore への保存が通っているか）
- ブラウザの開発者ツールの Console に赤いエラーが無いか

4つの入口すべてで1回ずつ通すこと。

---

## 5. 移行が済んだら書き換える URL 一覧

**まだ書き換えていない。** デプロイして動作確認が通ってから、一括で直す。
`https://g19922ma.github.io/iFont/experiment/` を `https://kana-task.web.app/` に置き換え、
ファイル名は上の「1. URL 一覧」の短い名前にそろえる。

### 必ず直すもの（参加者に渡る／実際に叩く）

| ファイル | 行 | 何の URL か |
|---|---|---|
| `project/掲載文.md` | 121（2件） | 掲載1a・1b の仕様表の「作業URL」 |
| 〃 | 194 | 掲載1a の**貼り付け用本文**の中の作業URL |
| 〃 | 253 | 掲載1b の貼り付け用本文 |
| 〃 | 376, 422 | 検証フェーズの仕様表と貼り付け用本文 |
| 〃 | 513, 561 | 群C の仕様表と貼り付け用本文 |
| `project/掲載手順_最終.md` | 43〜46 | 掲載に貼る4本の作業URL |
| `project/掲載前チェックリスト.md` | 77 | `pre_launch` を実物で確かめる curl |
| 〃 | 277 | 版を上げた JavaScript が配信されているかの curl |
| 〃 | 768 | `B=https://...` の変数。この下の8本の疎通確認がまとめて変わる |
| 〃 | 791 | `config_version` の確認 |
| `project/先生への連絡_20260824.md` | 64, 65 | 先生に試してもらう2本 |
| `project/changes_from_main.md` | 5 | 先生への提出文書の「公開確認用URL」 |

> `project/掲載前チェックリスト.md` の 768 行目は `B=<URL>` の代入なので、
> **ここ1行を直せば下の8本が一度に直る**。

### ついでに直すとよいもの（研究者しか見ない）

| ファイル | 行 |
|---|---|
| `project/実験計画書_1文字課題.md` | 8（旧課題の確認用URL） |
| `project/フィードバック_実験計画書_1文字課題.md` | 5 |
| `project/音源比較_QC表.md` | 120 |
| `project/音源調査_標準DB.md` | 127 |
| `project/合成音声_話者候補.md` | 181 |
| `project/相談_合成かな1音の清濁混同.md` | 64 |
| `project/子音母音配分_方式比較.md` | 13, 14 |
| `experiment/tools/measure_raw_compare.py` | 278（生成後に表示する「公開先」の案内） |
| `.claude/settings.local.json` | 7（旧サイト向けの curl 許可。当たらなくなるだけ） |

これらは `experiment/tools/` にある聴き比べページを指しており、**新しいサイトには載せない**
（研究者用のツールなので公開範囲から外した）。移行後は「手元のファイルを開く」か
「GitHub Pages のほうを見る」に書き換える。

### 直さないもの

- `WORKLOG.md`（9件）、`project/project_log_260723.md`（29件）、
  `project/handover_260723.md`、`docs/` の各文書 —— **過去の記録**なので、
  当時そこにあったという事実がそのまま正しい。
- `experiment/PRODUCTION.md` 10〜13行目 —— 先生の元リポジトリ（`qurihara.github.io` →
  `unryu.org`）の話で、いまの転写検証実験とは別系統。ただし
  「参加者には `unryu.org` の URL を渡すこと」と書いてあり、`project/` 側の記述と
  食い違っている。**どちらが正なのか、移行のついでに整理したほうがよい**。

### すでに直したもの（このセッションで対応済み）

| ファイル | 内容 |
|---|---|
| `experiment/transfer_config.js` 167行目 | コメントの中の確認用 curl を新しい URL に変更。**このファイルは参加者に配信されるので、旧 URL が残っていると移行の意味が無かった** |
| `experiment/prod_common.js` 2行目 | 冒頭のコメントから「iFont」を削除（同じく配信されるファイル） |

---

## 6. GitHub Pages に戻す（切り戻し）

GitHub Pages は**止めずにそのまま残す**。したがって切り戻しは
「掲載に貼る URL を元に戻す」だけで済み、サーバ側の作業は要らない。

1. 掲載中のものがあれば、作業URL を
   `https://g19922ma.github.io/iFont/experiment/transfer_calib_audio.html?prod=1&wid=<作業者ID>`
   の形に戻す（上の「5.」の表を逆にたどる）。
2. GitHub Pages 側は `main` に push してあるものがそのまま配信されているので、
   何もしなくてよい。念のため疎通を確認する:
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" \
     https://g19922ma.github.io/iFont/experiment/transfer_calib_audio.html
   ```

Firebase のほうを止めたいときだけ:

```bash
firebase hosting:disable --site kana-task     # 公開を止める(サイトは残る)
```

すでに始めてしまった参加者がいる場合、**途中で配り先を変えないこと**。
実験の途中で JavaScript のファイルが別のサーバから来ると、
ブラウザに残っている進行状況（`localStorage`）と噛み合わずに止まることがある。
切り戻すなら、その掲載が終わってからにする。

---

## 7. 丸山の手作業が要るところ

| いつ | やること | なぜ自動化できないか |
|---|---|---|
| ~~移行前~~ | ~~Firebase に `kana-task` サイトを作る~~ | **2026-08-24 に作成済み**（`firebase hosting:sites:create kana-task`） |
| デプロイ後 | ブラウザで4つの入口を最後まで1回ずつ通す（`?wid=uitest-...`） | 音が鳴るか・アニメが出るか・完了コードが出るかは、実際に人が見ないと分からない |
| 掲載直前 | 掲載サイトの作業URL を貼り替える | 掲載サイトの管理画面での作業 |
| 掲載直前 | `project/` の URL を一括で書き換える（上の「5.」） | 移行が済んでからにする、と決めたため |
| 群Bの本番前 | `transfer_warp.json` を生成して置く | まだ存在しない。**無いと提案手法が等速で代用され、検証のデータにならない** |

---

## 8. 移行で壊れないと確認したこと

| 心配ごと | 調べた結果 |
|---|---|
| **相対パスが壊れないか** | 壊れない。実験の JavaScript・CSS・刺激の参照は**すべて同じ階層の相対パス**で書かれており、`/iFont/` で始まる絶対パスは1つも無い（コメント1か所だけだったので修正済み）。`transfer_stimuli_amitaro/あ_g0040.wav` や `base/あ.png` のような参照も、コピー後の階層をそのまま保っているのでそのまま通る。エミュレータで実際に 200 が返ることを確認した |
| **Firestore のセキュリティルール** | 変更不要。ルール（`firebase/firestore.transfer.rules`）にはドメイン・参照元の条件が1つも書かれておらず、どこから来た通信かで挙動が変わらない |
| **ウェブAPIキーが旧ドメイン限定になっていないか** | なっていない。参照元を「無し」「`kana-task.web.app`」「`g19922ma.github.io`」の3通りに変えて Firestore を叩いたところ、**3つとも同じ応答**（ルールによる拒否）で、キー側の参照元制限には当たらなかった。新しいドメインでもそのまま動く |
| **`?v=` のキャッシュ対策が効くか** | 効く。`?v=` の付いた URL はブラウザにとって別物として扱われる仕組みで、サーバの種類には関係ない。加えて `firebase.json` で、**HTML は毎回サーバに聞きに行く**（`no-cache`）、JavaScript と CSS は1時間、音声と画像は7日、と明示した。GitHub Pages では HTML も10分間キャッシュされていたので、**版を上げたときの反映はむしろ速くなる** |
| **検索エンジンに載らないか** | 二重に止めた。各 HTML の `<meta name="robots" content="noindex,nofollow">` に加えて、サーバが全ファイルに `X-Robots-Tag: noindex, nofollow` を付ける。`robots.txt` も全面禁止で書き直す |

---

## 9. 残っている懸念（判断待ち）

### 9-1. 配信する JavaScript のコメントに、研究の設計がそのまま書いてある

URL からは研究名が消えるが、**ページのソースを開くと設計が読める**状態は残る。

- `transfer_config.js`: 実験計画書・仮説・下見の正答率・`project/` の文書名に触れた
  コメントが **29行**（例:「対照条件が構造的に不利になっていた」「仮説1が勝って当たり前の比較」）
- `transfer.js`: 同種のコメントが 5行

これは **GitHub Pages のときから同じ**で、移行によって悪化はしない。
参加者が開発者ツールを開かないかぎり見えないので、優先度は URL の問題より低い。

気になるなら、`build_hosting.sh` のコピーの直後にコメントを落とす処理
（`npx terser --comments false` など）を足せる。ただし、
**「配信中のファイルを curl して `pre_launch` を grep する」という掲載前の確認手順が使えなくなる**
ので、確認のやり方を先に決める必要がある。今回は**手を付けていない**。

### 9-2. 消しきれなかった「ifont」の文字列

参加者の画面と `<title>` からは「iFont」を完全に消した（4つの入口の title は
「ひらがなの聞き取りの課題」など、研究名を含まない）。ソースに残っているのは次の3種類:

| 場所 | 何 | 残した理由 |
|---|---|---|
| `transfer_config.js` 278行目 | `project_id: "ifont-transfer"` | **消せない。** Firestore への通信先そのもの。消すには Firebase プロジェクトごと作り直してデータを移す必要がある。なお `ifont-transfer` という文字だけでは GitHub のアカウントにもリポジトリにもたどり着けない |
| `transfer.js` 200行目 / `transfer_comfort.js` 137行目 | `"ifont_transfer_assign_" + ...` | ブラウザに保存する覚え書きの名前。開発者ツールでしか見えない。**変えると、いま実験の途中の人の割り当ての記憶が消えて別の集団に入りかねない**ので触らなかった |
| `transfer_config.js` 268行目 | コメント「firebase CLI で作った(ifont-transfer / 東京)」 | 上と同じ名前の説明。実害が無いので残した |

「途中の人がいない」と分かっているタイミングなら、2つ目は安全に変えられる。

---

## 10. 変更したファイル（このセッション）

| ファイル | 変更 |
|---|---|
| `firebase.json` | `hosting` の節を追加（サイト `kana-task`／公開元 `hosting_dist`／短いURLの読み替え／キャッシュと検索避けの指定）。既存の `firestore` の節はそのまま |
| `.firebaserc`（新規） | 既定のプロジェクトを `ifont-transfer` に。以後 `--project` を省ける |
| `.gitignore` | `hosting_dist/` を追加（中身は全部コピーなので git に入れない） |
| `experiment/tools/build_hosting.sh`（新規） | 公開するファイルだけを `hosting_dist/` に集めるスクリプト |
| `experiment/transfer_config.js` | 167行目、コメント内の確認用 curl を新 URL に |
| `experiment/prod_common.js` | 2行目、コメントから「iFont」を削除 |
| `project/Firebase Hosting移行手順.md`（新規） | この文書 |

Firebase 側で行った操作は **`kana-task` サイトの作成のみ**。デプロイはしていない
（`https://kana-task.web.app/` はまだ 404 を返す）。

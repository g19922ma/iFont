# Firebase Hosting 移行手順

実験ページの配り先を、GitHub Pages（`https://g19922ma.github.io/iFont/experiment/...`）から
Firebase Hosting（`https://kana-task.web.app/...`）へ移すための手順書。

## 現在の状態（2026-08-24 時点）

**デプロイ済み。`https://kana-task.web.app` は動いている。掲載はまだしていない。**

| 項目 | 状態 |
|---|---|
| Hosting サイト `kana-task` | 作成済み・デプロイ済み（643ファイル・6.4MB） |
| 配信中の版 | `prov-2026-08-24e` ／ コミット `b29b1f5b3`（＝手元の `main` と同じ） |
| `pre_launch`（掲載前フラグ） | **`true`**。記録はすべて試し打ち扱いで、本番の連番も進まない |
| 聴覚刺激 | **「ん」を直した版**（後続音を「ぱ」に変えて作り直した544本）を配信済み |
| `transfer_warp.json`（転写の進み方の表） | まだ無い。群Bの本番前に要る |
| 掲載文・掲載手順のURL | `kana-task.web.app` に書き換え済み |
| GitHub Pages | 残してある（切り戻し用）。ただし**参加者には案内しない** |

> ### ⚠ 掲載するときに必ずやること
>
> 1. `experiment/transfer_config.js` の `pre_launch` を **`false`** に戻す
>    （いまは `true`。戻し忘れると、本物の参加者のデータが全部テスト扱いになる）
> 2. 入口4ページの `?v=` を上げる（`transfer_config.js` を変えたため）
> 3. `bash experiment/tools/build_hosting.sh` → `firebase deploy --only hosting:kana-task`
>
> 1 を忘れたままだと、**手順 3 のビルドがその場で止まる**ようにしてある。

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

**2026-08-25**: 較正（群Acal・A′）の掲載を2本→1本にまとめた。掲載に貼るのは
`/calib` の1本だけで、サイト側が重み80:150で聴覚・視覚に自動振り分けする。
`/listen`・`/look` は研究者の動作確認用として残すが、掲載には使わない。

| 掲載 | 集団 | 新しい URL | 中身のファイル |
|---|---|---|---|
| 較正（聴覚・視覚） | 群Acal・A′ | `https://kana-task.web.app/calib?prod=1&wid=<作業者ID>` | `transfer_calib.html` |
| 検証 | 群B | `https://kana-task.web.app/read?prod=1&wid=<作業者ID>` | `transfer_test.html` |
| 見え心地のアンケート | 群C | `https://kana-task.web.app/survey?prod=1&wid=<作業者ID>` | `transfer_comfort.html` |
| （掲載しない・研究者の動作確認用・聴覚単独） | 群Acal | `https://kana-task.web.app/listen?prod=1&wid=<作業者ID>` | `transfer_calib_audio.html` |
| （掲載しない・研究者の動作確認用・視覚単独） | 群A′ | `https://kana-task.web.app/look?prod=1&wid=<作業者ID>` | `transfer_calib_visual.html` |
| （掲載しない・研究者の確認用） | 振り分け版 | `https://kana-task.web.app/check?prod=1&wid=uitest-...` | `transfer_calib.html` |

短い名前（`/calib` など）は `firebase.json` の `rewrites` で本当のファイル名に読み替えている。
**ファイル名そのままの URL も動く**（`https://kana-task.web.app/transfer_calib.html`）。
掲載に貼るのは短いほうでよいが、貼り間違えると別の集団の課題を出すことになるので、
掲載前に下の「4. 掲載前の確認」で中身を必ず照合すること。

> ⚠ `/look`（研究者の動作確認用・視覚較正）と `/read`（群B・視覚の検証）は**どちらも見る課題**で紛らわしい。
> 使うときは表の行をそのままコピーし、目視で1回照合する。

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
| `transfer_calib.html` `transfer_test.html` `transfer_comfort.html` | 参加者が開く3つの入口（較正・検証・見え心地） |
| `transfer_calib_audio.html` `transfer_calib_visual.html` | 研究者の動作確認用（聴覚単独・視覚単独。掲載しない） |
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

# 2. 公開するファイルを集め直す
bash experiment/tools/build_hosting.sh
```

**掲載用のビルドは、`pre_launch` が `true` のままだとその場で止まる。**
確認を人の記憶に頼らないための仕掛けである。動作確認のために
`true` のまま作りたいときだけ、明示的に迂回する:

```bash
ALLOW_PRELAUNCH=1 bash experiment/tools/build_hosting.sh
```

スクリプトがやること（順番に）:

1. `transfer_config.js` から音源のフォルダ名と索引名を読み、必要なファイルだけコピーする
2. **JavaScript からコメントを落とす**（下の「3-1b」）
3. 落とす前後で**意味が変わっていないか**を確かめる
4. `build_info.json`（掲載前の確認に使う目印）を書き出す
5. `pre_launch` が `true` なら止まる
6. 正解表や `.py` `.md` が混ざっていないか名前で見張る

### 3-1b. 配信するファイルからコメントを落としている

`experiment/` の JavaScript には、実験計画書・仮説・下見の正答率に触れた説明が
大量に書いてある（`transfer_config.js` だけで設計の話が29行）。ファイルは
参加者のブラウザに配信されるので、開発者ツールを開かれると
「何を測られているか」が読めてしまう。URL から研究名を消しても、これが残ると隠した意味が薄い。

そこで、**配信用にコピーしたほうだけ**コメントを落としている。
`experiment/` の元のファイルはそのままで、説明も残っている。

- 使っているのは **esbuild**（本物の JavaScript 解析器）で、`--minify-whitespace` だけを
  指定している。**変数名の書き換えも構文の作り替えもしない**（コメントと余白を落とすだけ）。
  素朴な正規表現だと、文字列の中の `//`（URLなど）や正規表現リテラルを巻き込んで壊すので使わない。
- 初回だけネットにつながっている必要がある（以後は手元の控えで動く）。
  取ってこられないときは**素通しにせず止まる**。

落としたあと、`experiment/tools/verify_stripped_js.js` が次を確かめる。
1つでも落ちたら、配信用のファイルを差し替えずに止まる。

| 対象 | 確かめかた |
|---|---|
| 設定2本（`transfer_config.js` / `transfer_comfort_config.js`） | 実際に読み込んで、できあがる設定を**キーの順序ごと**突き合わせる |
| 部品2本（`prod_common.js` / `transfer_firestore.js`） | 外に出している関数の名前と種類の一覧を突き合わせる |
| 本体2本（`transfer.js` / `transfer_comfort.js`） | 画面に出る文字列（**使用許諾の表記**・所属名）が同じ回数あるか数える |
| 全6本 | 文法として読めるか（`node --check`）／極端に縮んでいないか |

> 使用許諾の表記「COEIROINK:あみたろ」は**画面に出す文字列**なので消えない
> （コメントではない）。検査でも回数を数えて見張っている。

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

# (1) 参加者用3入口＋研究者確認用2本が開くか、そして「どの集団のページか」が合っているか
for p in calib read survey listen look; do
  echo "--- /$p ---"
  curl -s "$B/$p" | grep -oE "<title>[^<]*</title>|TRANSFER_PAGE = \{[^}]*\}"
done
```

出るべきもの:

| URL | title | 集団の指定 |
|---|---|---|
| `/calib`（参加者用・較正） | ひらがなの聞き取り・見え方の課題 | `phase: "calib"`（重み80:150で聴覚・視覚に自動振り分け） |
| `/read`（参加者用・検証） | ひらがなの聞き取り・見え方の課題 | `phase: "test"` |
| `/survey`（参加者用・見え心地） | 文字の見え心地についてのアンケート | （指定なし。群Cは1集団だけ） |
| `/listen`（研究者の動作確認用・掲載しない） | ひらがなの聞き取りの課題 | `phase: "calib", force_group: "acal"` |
| `/look`（研究者の動作確認用・掲載しない） | ひらがなの見え方の課題 | `phase: "calib", force_group: "aprime"` |

```bash
# (2) 配信中のファイルで掲載前フラグが false か(手元ではなく実物を見る)
curl -s $B/build_info.json
#   → "pre_launch": false,  でなければ掲載しない
#   config_version / stimuli_dir / git_commit が手元と合っているかも合わせて見る
#
#   ⚠ かつては transfer_config.js を grep していたが、配信するファイルは
#     コメントを落としてあり全体が1行なので使えない。値だけを別に書き出してある。

# (3) 配信されているのが手元と同じ版か
git rev-parse --short HEAD     # build_info.json の git_commit と一致すること

# (4) 出してはいけないものが 404 か
for p in answer_key_merged.json tools/ PRODUCTION.md index.html transfer_stimuli_kanon/ ; do
  echo "$p -> $(curl -s -o /dev/null -w '%{http_code}' $B/$p)"   # 全部 404 であること
done
```

**(5) ブラウザで最後まで通す（手作業。これだけは自動化できない）**

`https://kana-task.web.app/calib?prod=1&wid=uitest-fb1` のように、
**作業者IDの頭を `uitest-` にして**開く。この頭の名前が付いた回は
`is_test` の印が付き、本番の連番とは別のカウンタから番号が配られるので、
**本番のデータにも連番にも混ざらない**（`experiment/transfer_firestore.js` の `isTestPid`）。

見るところ:
- 音が鳴るか／文字のアニメが出るか（＝刺激ファイルの参照が壊れていないか）
- 最後まで進んで完了コードが出るか（＝Firestore への保存が通っているか）
- ブラウザの開発者ツールの Console に赤いエラーが無いか

参加者用3入口（`/calib` `/read` `/survey`）＋研究者確認用2本（`/listen` `/look`）、
計5本すべてで1回ずつ通すこと。

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
| ~~移行前~~ | ~~Firebase に `kana-task` サイトを作る~~ | ✓ 2026-08-24 に作成済み |
| ~~移行前~~ | ~~デプロイする~~ | ✓ 2026-08-24 に実施済み |
| ~~移行後~~ | ~~`project/` の URL を書き換える~~ | ✓ 2026-08-24 に実施済み（上の「5.」） |
| **いま** | **ブラウザで参加者用3入口＋確認用2本を最後まで1回ずつ通す**（下の 7-1） | 音が鳴るか・アニメが出るか・完了コードが出るかは、実際に人が見ないと分からない |
| 刺激の作り直し後 | 再ビルドして再デプロイ | 「ん」が残る版のまま配信している |
| 掲載直前 | `pre_launch` を `false` に戻し、`?v=` を上げて再デプロイ | 実験の設定を変える判断そのもの |
| 掲載直前 | 掲載サイトの作業URL を貼り替える | 掲載サイトの管理画面での作業 |
| 群Bの本番前 | `transfer_warp.json` を生成して置く | まだ存在しない。**無いと提案手法が等速で代用され、検証のデータにならない** |

### 7-1. いまやってほしいブラウザでの確認

`?wid=` の頭を **`uitest-`** にして開くこと。この頭の名前が付いた回は
`is_test` の印が付き、本番の連番とは別のカウンタから番号が配られる
（いまは `pre_launch` も `true` なので二重に守られている）。

```
https://kana-task.web.app/calib?prod=1&wid=uitest-check0
https://kana-task.web.app/listen?prod=1&wid=uitest-check1
https://kana-task.web.app/look?prod=1&wid=uitest-check2
https://kana-task.web.app/read?prod=1&wid=uitest-check3
https://kana-task.web.app/survey?prod=1&wid=uitest-check4
```

見るところ:

- 音が鳴るか／文字のアニメが出るか（＝刺激ファイルの参照が壊れていないか）
- 最後まで進んで完了コードが出るか（＝Firestore への保存が通っているか）
- 画面の右上に「掲載前モード：この記録はテスト扱いです」の**赤い帯が出ているか**
  （`pre_launch: true` が効いている印。掲載時にはこれが消えていること）
- 開発者ツールの Console に赤いエラーが無いか

終わったら、試し打ちの行を消す:

```bash
python3 experiment/tools/purge_transfer_firestore.py --key firebase/ifont-transfer-sa.json        # 数えるだけ
python3 experiment/tools/purge_transfer_firestore.py --key firebase/ifont-transfer-sa.json --yes  # 実際に消す
```

> このスクリプトは **`is_test` の印が付いた行しか消さない**ので、
> 本物のデータに手が届かない。

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

## 9. 残っている懸念

### 9-1. 配信する JavaScript のコメント → **✓ 解決済み（2026-08-24）**

かつては、URL から研究名を消しても**ページのソースを開くと設計が読めた**
（`transfer_config.js` に実験計画書・仮説・下見の正答率に触れた説明が29行、
`transfer.js` に5行）。

配信用にコピーする段階でコメントを落とすようにして解決した（「3-1b」）。
元のファイルは触っていないので、開発時の読みやすさと設計判断の記録は残っている。

実際の効果（デプロイ済みのファイルで確認）:

| | 元のファイル | 配信されているファイル |
|---|---|---|
| 「仮説」「計画書」「パイロット」「対照条件」の出現 | 51 か所 | **0 か所** |
| `transfer_config.js` の大きさ | 85KB | 6.6KB |
| `transfer.js` の大きさ | 132KB | 69KB |
| 6本の合計 | 300KB | 135KB |
| 使用許諾の表記「COEIROINK:あみたろ」 | 1 か所 | **1 か所（残っている）** |

副産物として、参加者がダウンロードする量が半分以下になった。

**掲載前の確認への影響**: `transfer_config.js` を curl して `pre_launch` を grep する
やり方は使えなくなった（全体が1行に潰れるため）。かわりに 2 つ用意した。

1. `build_info.json` を配信し、`pre_launch` などの値をそこで確かめる（「4.」の (2)）
2. **`pre_launch` が `true` のままだと掲載用のビルドが止まる**（「3-1.」）
   —— 確認を忘れる余地をなくすほうが確実なので、こちらを主にした

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

### 9-3. ⚠ Firestore に「本物扱い」の行が 103 行たまっている（**要判断**）

デプロイ後の疎通確認のついでに Firestore の中身を数えたところ、
**`is_test` の印が付いていない行**が次のだけ入っていた（2026-08-24 時点）。

| コレクション | 全行 | うち印なし（＝解析に混ざる） |
|---|---|---|
| `transfer_trials`（回答） | 127 | **96** |
| `transfer_wellbeing`（見え心地） | 2 | **1** |
| `transfer_roster`（名簿） | 55 | **6** |

印なしの参加者IDは `anon-darawfgc` / `anon-w071hbw7` / `anon-11pism0f` /
`anon-tp56ewrj` / `anon-y0x05w11` の5人ぶんで、いずれも較正フェーズ（群Acal・群A′）である。

**掲載はまだしていないので、これはクラウドソーシングの参加者ではない。**
`pre_launch` が `false` だったあいだに GitHub Pages 側のページを
`uitest-` などの頭を付けずに開いた回（研究者・先生の動作確認）が、
そのまま本物として保存されたものと考えられる。
`transfer_config.js` のコメントが警告している 2026-08-21 の事故と同じ形である。

**放っておくと2つ困る。**

1. 解析の既定（`export_transfer_firestore.py`）は `is_test` の行だけを外すので、
   **この96行は本物の回答として集計に混ざる**
2. 名簿の6行が**本番の連番を6つ消費している**ので、較正フェーズの
   群Acal・群A′ の割り当ての釣り合いが最初からずれている

**丸山の判断が要る。** 心当たりのある回なら、印を付けてから消すのが安全:

```bash
# まず中身を見る（誰の・いつの回か）
python3 experiment/tools/export_transfer_firestore.py --key firebase/ifont-transfer-sa.json

# 動作確認だったと分かったら、名指しで印を付ける（--yes を付けるまで実際には変えない）
python3 experiment/tools/purge_transfer_firestore.py --key firebase/ifont-transfer-sa.json \
    --mark-test transfer_roster/calib_anon-darawfgc
# 印を付けたら purge で消え、--reset-counters で連番も0に戻せる
```

> ⚠ `--reset-counters` は**掲載が始まったあとは使わないこと**（配った番号と重なる）。
> いまは掲載前なので使ってよい。

---

## 10. 変更したファイル（このセッション）

| ファイル | 変更 |
|---|---|
| `firebase.json` | `hosting` の節を追加（サイト `kana-task`／公開元 `hosting_dist`／短いURLの読み替え／キャッシュと検索避けの指定）。既存の `firestore` の節はそのまま |
| `.firebaserc`（新規） | 既定のプロジェクトを `ifont-transfer` に。以後 `--project` を省ける |
| `.gitignore` | `hosting_dist/` を追加（中身は全部コピーなので git に入れない） |
| `experiment/tools/build_hosting.sh`（新規） | 公開するファイルだけを `hosting_dist/` に集め、コメントを落とし、検査し、`build_info.json` を書き出すスクリプト |
| `experiment/tools/verify_stripped_js.js`（新規） | コメントを落とす前後で意味が変わっていないかを確かめる |
| `experiment/transfer_config.js` | コメント内の確認用 curl を新 URL に／`pre_launch` を `true` に戻した（掲載しないため） |
| `experiment/prod_common.js` | 冒頭のコメントから「iFont」を削除 |
| `experiment/PRODUCTION.md` | 冒頭に「この文書は乙課題・frac課題だけ。転写検証は別の配信先」と範囲を明示 |
| `project/掲載文.md` | 参加者に渡す作業URL 7か所を `kana-task.web.app` に |
| `project/掲載手順_最終.md` | 掲載する4本のURL |
| `project/掲載前チェックリスト.md` | URL／`pre_launch` の確認を `build_info.json` に／Firebase へのデプロイ手順（E-1b）と非公開の確認（E-2b）を追加 |
| `project/先生への連絡_20260824.md` | 先生に試してもらう2本のURL |
| `project/Firebase Hosting移行手順.md`（新規） | この文書 |

Firebase 側で行った操作は **`kana-task` サイトの作成**と**デプロイ**の2つ。
`https://kana-task.web.app` は動いている（掲載はまだしていない）。

#!/usr/bin/env bash
# =============================================================================
# build_hosting.sh — 参加者に配るファイルだけを hosting_dist/ に集める
# -----------------------------------------------------------------------------
# なぜこの作りにしたか
# -----------------------------------------------------------------------------
# Firebase Hosting は「public に指定したフォルダの中身を丸ごと公開する」仕組みで、
# firebase.json の ignore は**除外リスト**しか書けない（「これだけ公開」とは書けない）。
#
# experiment/ をそのまま公開すると、公開してよいのは 7.7MB なのに
# フォルダ全体は 167MB あり、その中には
#
#   * answer_key_merged.json        … 旧課題の正解表（1.3MB）
#   * tools/                        … 解析スクリプト・下見のデータ・検定力の計算
#   * transfer_stimuli/ など        … 採用しなかった音源
#   * pilot_*.html / audio*.html    … 旧実験の一式
#
# が混ざっている。除外リストの書き漏らし1行で正解表が公開されるので、
# 「要るものだけを別のフォルダにコピーして、そこを公開する」方式にした。
#
# ⚠ .gitignore は Firebase には効かない。git に入れていないファイル（手元だけの
#   合成音の候補など）も、公開フォルダに置いてあれば**そのままアップロードされる**。
#   この点でも「コピー方式」のほうが安全である。
#
# -----------------------------------------------------------------------------
# 使い方
# -----------------------------------------------------------------------------
#   bash experiment/tools/build_hosting.sh      # リポジトリのどこから実行してもよい
#
# 出力: <リポジトリ直下>/hosting_dist/
# このスクリプトはデプロイしない。デプロイのコマンドは
# project/Firebase Hosting移行手順.md を見ること。
# =============================================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$REPO/experiment"
DIST="$REPO/hosting_dist"

echo "リポジトリ: $REPO"

# --- 1. 音源の置き場所は transfer_config.js から読む ------------------------
# 音源を切り替えたとき（あみたろ→別の話者）にこのスクリプトが古いままにならないよう、
# フォルダ名と索引ファイル名は手で書かず、設定ファイルの実際の値を取り出して使う。
# コメント行（// で始まる行）に同じ文字列が出てくるので、それは読み飛ばす。
read_cfg() {
  grep -E "^[[:space:]]*$1:[[:space:]]*\"" "$SRC/transfer_config.js" \
    | grep -v "^[[:space:]]*//" \
    | head -1 \
    | sed -E "s/.*$1:[[:space:]]*\"([^\"]+)\".*/\1/"
}

STIM_DIR="$(read_cfg stimuli_dir)"
MANIFEST="$(read_cfg manifest_url)"
BASE_DIR="$(read_cfg base_dir)"

if [ -z "$STIM_DIR" ] || [ -z "$MANIFEST" ] || [ -z "$BASE_DIR" ]; then
  echo "エラー: transfer_config.js から stimuli_dir / manifest_url / base_dir を読めなかった" >&2
  exit 1
fi
echo "設定から読んだ音源: $STIM_DIR  索引: $MANIFEST  文字画像: $BASE_DIR"

# --- 2. 公開するファイルの一覧（これが公開範囲の全て） ----------------------
# ここに書いていないものは絶対に公開されない。
FILES=(
  # 参加者が開く入口（掲載する4本）
  "transfer_calib_audio.html"    # 較正・聴覚（群Acal）
  "transfer_calib_visual.html"   # 較正・視覚（群A′）
  "transfer_test.html"           # 検証（群B）
  "transfer_comfort.html"        # 見え心地（群C）
  # 研究者の動作確認用（掲載しない。振り分け版の入口）
  "transfer_calib.html"
  # 見た目
  "transfer.css"
  # 中身
  "prod_common.js"
  "transfer_config.js"
  "transfer_firestore.js"
  "transfer.js"
  "transfer_comfort_config.js"
  "transfer_comfort.js"
)

# 生成できていれば公開するが、無くてもエラーにしないもの。
# transfer_warp.json は転写（提案手法）の進み方の表。
# **検証フェーズ（群B）の本番データを取る前には必ず要る**（無いと等速で代用され、
# 提案手法のデータにならない）。見え心地（群C）と較正フェーズは無くても動く。
OPTIONAL_FILES=(
  "transfer_warp.json"
  # 研究者が水準を目で見るためのページ（参加者には配らない。robots.txt で拾われない）。
  # ⚠ **これは静止画で、提示時間が入らない。** 本番は 33ms で消えるので、
  #   ここで読めても本番で読めるとは限らない。刻みの一望にだけ使うこと。
  "level_chooser.html"
)

# 聞き取り確認の音の置き場。**設定（audio.check.dir）から取り出す**ので、
# 設定を変えたらここも自動で追従する（手で書かない）。
CHECK_DIR="$(node -e 'const w={};require(process.argv[1]);
  const c=w.TRANSFER_CONFIG||global.window.TRANSFER_CONFIG;
  process.stdout.write(((c.audio&&c.audio.check&&c.audio.check.dir)||"audio_check"))' \
  "$SRC/transfer_config.js" 2>/dev/null || echo audio_check)"

DIRS=(
  "$STIM_DIR"    # 打ち切り済みの音声（544ファイル・約7MB）
  "$BASE_DIR"    # かなの完成形PNG 84字（約340KB）
  "$CHECK_DIR"   # 聞き取り確認の数字の音（4ファイル・約220KB）
)

# --- 3. 作り直し ------------------------------------------------------------
rm -rf "$DIST"
mkdir -p "$DIST"

for f in "${FILES[@]}" "$MANIFEST"; do
  if [ ! -f "$SRC/$f" ]; then
    echo "エラー: 見つからない: experiment/$f" >&2
    exit 1
  fi
  cp "$SRC/$f" "$DIST/$f"
done

for f in "${OPTIONAL_FILES[@]}"; do
  if [ -f "$SRC/$f" ]; then
    cp "$SRC/$f" "$DIST/$f"
    echo "任意ファイルを入れた: ${f}"
  else
    # ⚠ macOS 標準の bash 3.2 は、変数のすぐ後ろに全角文字が続くと
    #   変数名の一部と取り違える。日本語の直前では必ず ${f} と波括弧で囲む。
    echo "⚠ 任意ファイルが無い: ${f}（検証フェーズ・群Bの本番前には必要）"
  fi
done

for d in "${DIRS[@]}"; do
  if [ ! -d "$SRC/$d" ]; then
    echo "エラー: 見つからない: experiment/$d" >&2
    exit 1
  fi
  cp -R "$SRC/$d" "$DIST/$d"
done

# --- 4. robots.txt は作り直す ----------------------------------------------
# experiment/robots.txt は GitHub Pages の階層（/experiment/...）を前提に
# 一部のページだけ禁止していた。新しい配信では階層が変わるうえ、
# そもそも実験ページは1つも検索に載せたくないので、全面禁止で書き直す。
# （各HTMLの <meta name="robots" content="noindex,nofollow"> と二重の備え。）
cat > "$DIST/robots.txt" <<'EOF'
User-agent: *
Disallow: /
EOF

# --- 4.5 JavaScript からコメントを落とす -----------------------------------
# なぜやるか。experiment/ の JavaScript には、実験計画書・仮説・下見の正答率に
# 触れた説明が大量に書いてある（transfer_config.js だけで設計の話が29行）。
# ファイルは参加者のブラウザに配信されるので、開発者ツールを開かれると
# 「何を測られているか」が読めてしまう。URL から研究名を消しても、これが残ると
# 隠した意味が薄い。
#
# **元のファイルは触らない。** 説明は開発の役に立つし、なぜその値にしたかの記録でもある。
# 配信用にコピーしたほう（hosting_dist/）だけを削る。
#
# ⚠ 素朴な正規表現（"//" 以降を消す等）は使えない。文字列の中の "//"（URL など）や
#   正規表現リテラルの中の "/" を巻き込んで、コードを壊す。ここでは esbuild という
#   本物の JavaScript 解析器に読ませて書き出し直す。
#   --minify-whitespace だけを付けているのが要点で、これは
#   **変数名の書き換えも構文の作り替えもしない**（コメントと余白を落とすだけ）。
#   --charset=utf8 は、日本語を \uXXXX に潰されないようにするため。
ESBUILD_VER="0.23.1"
JS_FILES=(prod_common.js transfer_config.js transfer_firestore.js
          transfer.js transfer_comfort_config.js transfer_comfort.js)

echo
echo "JavaScript からコメントを落とす（esbuild ${ESBUILD_VER}）…"
TMPJS="$(mktemp -d)"
trap 'rm -rf "$TMPJS"' EXIT

# npx は一度取ってくればあとは手元の控えから動く（＝2回目以降はネット不要）。
# 取ってこられないときは**黙って素通しにせず、その場で止める**。
# 素通しすると設計の説明が付いたまま配信されてしまい、この工程の意味が無くなる。
if ! (cd "$DIST" && npx --prefer-offline --yes "esbuild@${ESBUILD_VER}" \
        "${JS_FILES[@]}" \
        --minify-whitespace --target=esnext --charset=utf8 \
        --legal-comments=none --outdir="$TMPJS" >/dev/null); then
  echo "エラー: esbuild を実行できなかった。" >&2
  echo "  初回だけネットにつながっている必要がある（以後は手元の控えで動く）。" >&2
  echo "  コメントを落とせないまま配信するのは危ないので、ここで止める。" >&2
  exit 1
fi

for f in "${JS_FILES[@]}"; do
  if [ ! -s "$TMPJS/$f" ]; then
    echo "エラー: ${f} の書き出しが空。" >&2
    exit 1
  fi
  # 文法として読めるか。**空ファイルでも通る検査**なので、これだけに頼らない
  # （中身が同じ意味かどうかは、この下の verify_stripped_js.js が見る）。
  if ! node --check "$TMPJS/$f"; then
    echo "エラー: ${f} がコメント除去で壊れた。" >&2
    exit 1
  fi
done

# --- 4.6 除去の前後で意味が変わっていないかを確かめる -----------------------
# 設定2本は「読み込んでできる値」を、部品2本は「外に出している関数の一覧」を、
# 本体2本は「画面に出る文字列（使用許諾の表記など）」を突き合わせる。
# ここで build_info.json（掲載前の確認に使う目印）も書き出す。
WARP_PRESENT=no
[ -f "$DIST/transfer_warp.json" ] && WARP_PRESENT=yes
GIT_COMMIT="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo unknown)"

echo
echo "コメント除去の前後で意味が変わっていないかを確かめる…"
if ! node "$SRC/tools/verify_stripped_js.js" \
        "$SRC" "$TMPJS" "$STIM_DIR" "$MANIFEST" "$GIT_COMMIT" "$WARP_PRESENT"; then
  echo "エラー: 検査に落ちた。配信用のファイルを差し替えずに止める。" >&2
  exit 1
fi

# 検査を通ったので、はじめて配信用フォルダのファイルを差し替える。
for f in "${JS_FILES[@]}"; do cp "$TMPJS/$f" "$DIST/$f"; done
cp "$TMPJS/build_info.json" "$DIST/build_info.json"

# --- 4.7 掲載前フラグの見張り ----------------------------------------------
# transfer_config.js の pre_launch が true のあいだは、記録がすべて「試し打ち」
# 扱いで保存され、名簿の連番も本番とは別のカウンタから配られる。
# **true のまま掲載すると、本物の参加者のデータが全部テスト扱いになる**
# （解析の既定では除外されるので、集計が0件になって初めて気づく）。
#
# コメントを落とすと、これまでの「配信中の transfer_config.js を curl して
# pre_launch を grep する」という確認ができなくなった（1行に潰れ、説明も消えるため）。
# かわりに **ここで止める**。確認を忘れる余地をなくす、という考え方である。
#
#   掲載用のビルド : そのまま実行する（pre_launch が true なら止まる）
#   動作確認のビルド: ALLOW_PRELAUNCH=1 bash experiment/tools/build_hosting.sh
PRE_LAUNCH="$(node -e 'const j=require(process.argv[1]);console.log(j.pre_launch?"true":"false")' "$DIST/build_info.json")"
echo
if [ "$PRE_LAUNCH" = "true" ]; then
  if [ "${ALLOW_PRELAUNCH:-}" = "1" ]; then
    echo "⚠ pre_launch は true。**動作確認用のビルド**として続ける（ALLOW_PRELAUNCH=1 が指定された）。"
    echo "  この状態で配信すると、記録はすべて試し打ち扱いになり本番データにならない。"
    echo "  掲載するときは transfer_config.js の pre_launch を false に戻すこと。"
  else
    echo "エラー: transfer_config.js の pre_launch が true のままである。" >&2
    echo "  このまま掲載すると、本物の参加者のデータが全部テスト扱いになる。" >&2
    echo "  ・掲載用に作るなら → transfer_config.js の pre_launch を false にする" >&2
    echo "  ・動作確認用に作るなら → ALLOW_PRELAUNCH=1 bash experiment/tools/build_hosting.sh" >&2
    exit 1
  fi
else
  echo "pre_launch は false（掲載用のビルド）。"
fi

# --- 5. 出してはいけないものが混ざっていないかの見張り ----------------------
# 名前で引っかける単純な検査だが、コピー漏れならぬ「コピーしすぎ」の事故は
# たいてい正解表・解析スクリプト・書きかけの文書が混ざる形で起きる。
LEAKS="$(find "$DIST" \( \
     -name 'answer_key*' -o -name '*.py' -o -name '*.md' -o -name '*.csv' \
  -o -name '*.docx' -o -name '*-sa.json' -o -name '.env' -o -name '.DS_Store' \
  \) -print)"
if [ -n "$LEAKS" ]; then
  echo "エラー: 公開してはいけないものが混ざっている:" >&2
  echo "$LEAKS" >&2
  exit 1
fi

# --- 6. 結果 ----------------------------------------------------------------
echo
echo "できあがり: $DIST"
echo "ファイル数: $(find "$DIST" -type f | wc -l | tr -d ' ')"
echo "大きさ:     $(du -sh "$DIST" | cut -f1)"
echo
echo "直下のファイル:"
find "$DIST" -maxdepth 1 -type f -exec basename {} \; | sort | sed 's/^/  /'
echo "フォルダ:"
find "$DIST" -maxdepth 1 -mindepth 1 -type d -exec basename {} \; | sort | sed 's/^/  /'
echo
echo "確認できたら次へ: project/Firebase Hosting移行手順.md"

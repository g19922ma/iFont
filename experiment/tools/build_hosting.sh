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
)

DIRS=(
  "$STIM_DIR"    # 打ち切り済みの音声（544ファイル・約7MB）
  "$BASE_DIR"    # かなの完成形PNG 84字（約340KB）
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

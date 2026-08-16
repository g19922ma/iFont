// iFont 全体像と現状 2026-08-04 版
const pptxgen = require("pptxgenjs");

const NAVY = "1E2A5E";
const INK = "22283C";
const MUTED = "6B7280";
const TINT = "F4F6FB";
const LINE = "E3E6EE";
const GOLD = "C8A44D";
const TEAL = "2E7D8F";
const RED = "C25B4E";
const ICE = "CADCFC";
const SOFT = "9FB0D8";
const W = "FFFFFF";
const FONT = "Yu Gothic";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.author = "iFont project";
pres.title = "iFont 全体像と現状 2026-08-04";

let page = 0;

function head(s, eyebrow, title) {
  s.addText(eyebrow, {
    x: 0.62, y: 0.4, w: 11, h: 0.3, fontFace: FONT, fontSize: 11, bold: true,
    color: GOLD, charSpacing: 3, margin: 0,
  });
  s.addText(title, {
    x: 0.6, y: 0.72, w: 12.15, h: 0.72, fontFace: FONT, fontSize: 27, bold: true,
    color: NAVY, margin: 0, valign: "top",
  });
}

function foot(s, dark) {
  page += 1;
  s.addText("iFont", {
    x: 0.62, y: 6.95, w: 2, h: 0.3, fontFace: FONT, fontSize: 10,
    color: dark ? SOFT : MUTED, margin: 0,
  });
  s.addText(String(page), {
    x: 11.9, y: 6.95, w: 0.8, h: 0.3, fontFace: FONT, fontSize: 10,
    color: dark ? SOFT : MUTED, align: "right", margin: 0,
  });
}

// 淡い下地のカード
function card(s, x, y, w, h, fill) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.06,
    fill: { color: fill || TINT }, line: { color: LINE, width: 1 },
  });
}

// 丸バッジ（番号や記号）
function badge(s, x, y, text, bg, fg, d) {
  const dia = d || 0.42;
  s.addShape(pres.ShapeType.ellipse, {
    x, y, w: dia, h: dia, fill: { color: bg || NAVY }, line: { color: bg || NAVY, width: 1 },
  });
  s.addText(text, {
    x, y, w: dia, h: dia, fontFace: FONT, fontSize: dia > 0.5 ? 15 : 13, bold: true,
    color: fg || W, align: "center", valign: "middle", margin: 0,
  });
}

// 見出し＋本文のカード
function infoCard(s, x, y, w, h, num, title, body, accent) {
  card(s, x, y, w, h);
  badge(s, x + 0.28, y + 0.28, num, accent || NAVY);
  s.addText(title, {
    x: x + 0.82, y: y + 0.26, w: w - 1.1, h: 0.42, fontFace: FONT, fontSize: 15,
    bold: true, color: NAVY, margin: 0, valign: "middle",
  });
  s.addText(body, {
    x: x + 0.28, y: y + 0.82, w: w - 0.56, h: h - 1.05, fontFace: FONT, fontSize: 12.5,
    color: INK, margin: 0, lineSpacingMultiple: 1.28, valign: "top",
  });
}

// 帯（結論・補足）
function note(s, x, y, w, label, text) {
  card(s, x, y, w, 0.72, "E8EEFC");
  s.addText(label, {
    x: x + 0.3, y: y + 0.06, w: 1.9, h: 0.6, fontFace: FONT, fontSize: 12, bold: true,
    color: NAVY, margin: 0, valign: "middle",
  });
  s.addText(text, {
    x: x + 2.15, y: y + 0.06, w: w - 2.45, h: 0.6, fontFace: FONT, fontSize: 12,
    color: INK, margin: 0, valign: "middle",
  });
}

/* ---------------------------------------------------------------- 1 表紙 */
{
  const s = pres.addSlide();
  s.background = { color: NAVY };
  s.addText("iFont", {
    x: 0.9, y: 1.5, w: 6, h: 1.0, fontFace: FONT, fontSize: 54, bold: true, color: W, margin: 0,
  });
  s.addText("インクルーシブ字幕プロジェクト — 全体像と現状", {
    x: 0.92, y: 2.5, w: 10, h: 0.5, fontFace: FONT, fontSize: 19, color: ICE, margin: 0,
  });
  s.addText(
    "音声で「いち早く理解する」ゲーム性を、視覚でも同じだけ成立させたい。\n" +
    "そのために、かな1文字ごとの「聞こえやすさ」と「見えやすさ」を同じ物差しで測り、\n" +
    "測ったデータで、音声と同期して動く字幕を作る。",
    { x: 0.92, y: 3.3, w: 10.5, h: 1.5, fontFace: FONT, fontSize: 15, color: W,
      margin: 0, lineSpacingMultiple: 1.5 });
  s.addShape(pres.ShapeType.rect, {
    x: 0.92, y: 5.05, w: 1.6, h: 0.035, fill: { color: GOLD }, line: { color: GOLD, width: 0 },
  });
  s.addText("2026-08-04  現状まとめ（初めて読む方向けの自己完結版）", {
    x: 0.92, y: 5.3, w: 10, h: 0.36, fontFace: FONT, fontSize: 13, color: ICE, margin: 0,
  });
  s.addText("github.com/qurihara/iFont  /  scrapbox.io/qurihara/iFont", {
    x: 0.92, y: 5.75, w: 10, h: 0.36, fontFace: FONT, fontSize: 11, color: SOFT, margin: 0,
  });
}

/* ------------------------------------------------------------- 2 やりたいこと */
{
  const s = pres.addSlide();
  head(s, "GOAL", "やりたいこと — 音声のゲーム性を、視覚でも成立させる");
  const y = 1.75, h = 2.35, w = 3.83;
  infoCard(s, 0.62, y, w, h, "1", "音声ならではのゲーム性",
    "競技かるたや早押しクイズでは、言葉が少しずつ届く音声だからこそ「どこで分かるか」を競える。文字で全部見せてしまうと勝負にならない。");
  infoCard(s, 0.62 + w + 0.25, y, w, h, "2", "聴覚に頼れない人",
    "聴覚障害などで音声が使えないと、このゲーム性ごと閉ざされる。普通の字幕は一度に全部見えてしまうため、代わりにならない。");
  infoCard(s, 0.62 + 2 * (w + 0.25), y, w, h, "3", "視覚で同じ体験を作る",
    "文字を「少しずつ分かるように」時間をかけて見せれば、目でも同じ勝負ができる。その見せ方を実測にもとづいて設計する。", GOLD);
  note(s, 0.62, 4.45, 12.13, "設計目標",
    "音声を聞いている人と、字幕を見ている人が、同じ時点に同じだけ分かること。");
  s.addText(
    "この設計目標を数値で満たすために、かな1文字ごとに「音をどこまで聞かせれば分かるか」と「字をどれだけ見せれば分かるか」を測り、両者を対応づける。",
    { x: 0.72, y: 5.45, w: 11.9, h: 0.9, fontFace: FONT, fontSize: 13, color: MUTED,
      margin: 0, lineSpacingMultiple: 1.4 });
  foot(s);
}

/* ------------------------------------------------------------ 3 仕組みの全体像 */
{
  const s = pres.addSlide();
  head(s, "SYSTEM", "仕組みの全体像 — 1つの文章から、音声とかな列を同期して出す");
  const y = 1.8;
  card(s, 0.62, y, 2.6, 1.75);
  s.addText("入力", { x: 0.85, y: y + 0.2, w: 2.2, h: 0.3, fontFace: FONT, fontSize: 12, bold: true, color: GOLD, margin: 0 });
  s.addText("かな漢字まじり文\n例:「秋の田の…」\n古語（ゑ・ゐ）も含みうる", {
    x: 0.85, y: y + 0.55, w: 2.2, h: 1.05, fontFace: FONT, fontSize: 12, color: INK, margin: 0, lineSpacingMultiple: 1.3 });

  card(s, 3.45, y, 2.6, 1.75);
  s.addText("前処理", { x: 3.68, y: y + 0.2, w: 2.2, h: 0.3, fontFace: FONT, fontSize: 12, bold: true, color: GOLD, margin: 0 });
  s.addText("読みを決める\n形態素解析にふりがなで上書きできる。百人一首は人手検証済みの読み対応表を使う", {
    x: 3.68, y: y + 0.55, w: 2.2, h: 1.1, fontFace: FONT, fontSize: 11.5, color: INK, margin: 0, lineSpacingMultiple: 1.25 });

  card(s, 6.28, y, 3.1, 1.75, "E8EEFC");
  s.addText("出力①  音声", { x: 6.51, y: y + 0.2, w: 2.7, h: 0.3, fontFace: FONT, fontSize: 12, bold: true, color: NAVY, margin: 0 });
  s.addText("読み上げ音声。モーラの長さと音高を設計どおりに固定して合成する", {
    x: 6.51, y: y + 0.55, w: 2.7, h: 1.05, fontFace: FONT, fontSize: 12, color: INK, margin: 0, lineSpacingMultiple: 1.3 });

  card(s, 9.62, y, 3.13, 1.75, "E8EEFC");
  s.addText("出力②  かな列", { x: 9.85, y: y + 0.2, w: 2.7, h: 0.3, fontFace: FONT, fontSize: 12, bold: true, color: NAVY, margin: 0 });
  s.addText("漢字は読みかなに直し、既存のかなは表記どおりに残す。各字を音声に同期して少しずつ見せる", {
    x: 9.85, y: y + 0.55, w: 2.7, h: 1.15, fontFace: FONT, fontSize: 11.5, color: INK, margin: 0, lineSpacingMultiple: 1.25 });

  s.addText("→", { x: 3.06, y: y + 0.6, w: 0.42, h: 0.5, fontFace: FONT, fontSize: 20, color: MUTED, align: "center", margin: 0 });
  s.addText("→", { x: 5.89, y: y + 0.6, w: 0.42, h: 0.5, fontFace: FONT, fontSize: 20, color: MUTED, align: "center", margin: 0 });

  note(s, 0.62, 3.85, 12.13, "同期の規則",
    "表示する字は「その字が実際に読まれる音」に合わせる。「を」はオの音、「ゑ」はエの音、助詞の「は」はワの音。");
  s.addText(
    "単独の音を持たない「っ・ゃ・ゅ・ょ」は、隣の字と組にする描画規則で扱う。時間の基準はモーラ1つあたりの長さで、この長さは実験で決める（10ページ）。\n" +
    "合成の要はタイムラインの決定論性である。どのモーラが何秒後に鳴るかを合成前に厳密に算出できるので、視覚側はそれに追従すればよい。",
    { x: 0.72, y: 4.8, w: 11.9, h: 1.3, fontFace: FONT, fontSize: 13, color: INK,
      margin: 0, lineSpacingMultiple: 1.45 });
  foot(s);
}

/* --------------------------------------------------------------- 4 中核の考え */
{
  const s = pres.addSlide();
  head(s, "CORE IDEA", "中核の考え — 「聞こえやすさ」と「見えやすさ」を同じ物差しでつなぐ");
  const y = 1.8, h = 2.5;
  card(s, 0.62, y, 5.2, h);
  s.addText("聴覚の曲線", { x: 0.92, y: y + 0.25, w: 4.6, h: 0.35, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0 });
  s.addText(
    "かな1音について、音の先頭から何％まで聞かせたら何％の人が正しく答えられるかを測る。対象は互いに聞き分けられる68音。",
    { x: 0.92, y: y + 0.72, w: 4.6, h: 1.5, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.35 });

  card(s, 7.55, y, 5.2, h);
  s.addText("視覚の曲線", { x: 7.85, y: y + 0.25, w: 4.6, h: 0.35, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0 });
  s.addText(
    "かな1文字について、字をどれだけ鮮明に出したら何％の人が正しく答えられるかを測る。対象は画面に出る全字形78字。",
    { x: 7.85, y: y + 0.72, w: 4.6, h: 1.5, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.35 });

  card(s, 6.05, y + 0.55, 1.28, 1.4, NAVY);
  s.addText("変換\ng", { x: 6.05, y: y + 0.55, w: 1.28, h: 1.4, fontFace: FONT, fontSize: 19, bold: true, color: W, align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 1.1 });

  note(s, 0.62, 4.55, 12.13, "つなぎ方",
    "同じ認識率になる点どうしを対応づける。gが決まれば、音声の進み方に合わせて各字の見せ方を機械的に設計できる。");
  s.addText(
    "曲線は文字ごとに違う。濁点のある字や小書きの字は、わずかな提示では取り違えられやすい。だから「かな全体で1本の曲線」ではなく、字ごとに1本ずつ推定する。データの少ない字も、字を変量効果に置いた階層モデルで安定して推定する。",
    { x: 0.72, y: 5.5, w: 11.9, h: 1.0, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.4 });
  foot(s);
}

/* ------------------------------------------------------------ 5 文字と音の対応 */
{
  const s = pres.addSlide();
  head(s, "UNITS", "文字と音の対応 — 音は68種類、字は78種類、ずれは読みでつなぐ");
  const y = 1.8, h = 3.35, w = 6.06;
  card(s, 0.62, y, w, h);
  badge(s, 0.92, y + 0.3, "68", TEAL, W, 0.62);
  s.addText("音（聴覚）", { x: 1.68, y: y + 0.32, w: 4, h: 0.4, fontFace: FONT, fontSize: 16, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText([
    { text: "日本語で互いに聞き分けられる音だけを使う", options: { bullet: true, breakLine: true } },
    { text: "を・ぢ・づ は お・じ・ず と同じ音なので外す（合成音声でも同一の音声データになることを確認済み）", options: { bullet: true, breakLine: true } },
    { text: "ゔ も多くの人が ぶ と区別して聞かないため外す", options: { bullet: true, breakLine: true } },
    { text: "っ・ゃ・ゅ・ょ は単独では音にならないため、もともと音の側に存在しない", options: { bullet: true } },
  ], { x: 0.95, y: y + 1.1, w: w - 0.66, h: h - 1.3, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, paraSpaceAfter: 8 });

  card(s, 0.62 + w + 0.25, y, w, h);
  badge(s, 0.92 + w + 0.25, y + 0.3, "78", GOLD, W, 0.62);
  s.addText("かな（視覚）", { x: 1.68 + w + 0.25, y: y + 0.32, w: 4, h: 0.4, fontFace: FONT, fontSize: 16, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText([
    { text: "表記どおりに表示するので、を・ゐ・ゑ・小書きが実際に画面に出る", options: { bullet: true, breakLine: true } },
    { text: "百人一首では、札が取れるかを決める先頭2文字の領域に「を」が21組も現れる", options: { bullet: true, breakLine: true } },
    { text: "同じ音の字は、その音の曲線と同期させる（を↔オ、ゑ↔エ、ゐ↔イ、ゔ↔ブ）", options: { bullet: true, breakLine: true } },
    { text: "音を持たない っ・ゃ・ゅ・ょ は、隣の字と組にする描画規則で同期させる", options: { bullet: true } },
  ], { x: 0.95 + w + 0.25, y: y + 1.1, w: w - 0.66, h: h - 1.3, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, paraSpaceAfter: 8 });

  note(s, 0.62, 5.45, 12.13, "測る量",
    "68音 × 78字の認識率曲線と、その対応づけ。日本語のかなの基礎データとしても公開する。");
  foot(s);
}

/* ---------------------------------------------------------------- 6 作る出力 */
{
  const s = pres.addSlide();
  head(s, "OUTPUTS", "作るものは2つ — 早押しクイズ向けの道具と、競技かるたの動画");
  const y = 1.8, h = 3.5, w = 6.06;

  card(s, 0.62, y, w, h);
  badge(s, 0.92, y + 0.3, "A", NAVY, W, 0.62);
  s.addText("早押しクイズ向けのコマンドラインツール", { x: 1.68, y: y + 0.3, w: 4.2, h: 0.62, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText(
    "現代日本語の文章を入れると、流暢な読み上げ音声と、それに同期して1文字ずつ現れるかな列を出す。\n\n" +
    "自然な抑揚のまま合成し、各モーラが何秒後に鳴るかを合成前に算出して視覚を追従させる。音の高さの設計は不要で、必要なのは時間の正確さである。\n\n" +
    "品質管理として、無声破裂音の有声開始時間の復元、モーラごとの音量の均一化、無声化した母音の復元を合成の工程に組み込む。",
    { x: 0.95, y: y + 1.12, w: w - 0.66, h: h - 1.35, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });

  card(s, 0.62 + w + 0.25, y, w, h);
  badge(s, 0.92 + w + 0.25, y + 0.3, "B", GOLD, W, 0.62);
  s.addText("競技かるたの動画", { x: 1.68 + w + 0.25, y: y + 0.3, w: 4.2, h: 0.62, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText(
    "百人一首のうち一部の歌について、読み上げ音声と同期したかな列の動画を作る。\n\n" +
    "音声は既に作ってある競技かるたの読み上げを使う。歌の選び方は、先行研究が人間の読手と合成音声で聞き分けの立ち上がりを実測している6首から選ぶ（12ページ）。\n\n" +
    "この動画は、測った曲線から予測した見え方が、実際の聞こえ方と揃っているかを見せる場になる。",
    { x: 0.95 + w + 0.25, y: y + 1.12, w: w - 0.66, h: h - 1.35, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });

  note(s, 0.62, 5.6, 12.13, "共通の土台",
    "どちらの出力も、同じ68音×78字の曲線と同じ変換gから作る。データが1つで応用が2つという構成である。");
  foot(s);
}

/* ------------------------------------------------------------ 7 実験の全体構成 */
{
  const s = pres.addSlide();
  head(s, "EXPERIMENT", "実験の全体構成 — まず速さの限界を測り、次に曲線の本体を測る");
  const y = 1.75, h = 2.2;
  card(s, 0.62, y, 6.06, h);
  s.addText("第1段階  乙課題（較正）", { x: 0.92, y: y + 0.22, w: 5.4, h: 0.35, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0 });
  s.addText(
    "文字（音）を3つ続けて出し、間隔Sを変えながら1番目と2番目を答えてもらう。連続して出すことで前の字の認識が悪くなるかどうかを、視覚と聴覚のそれぞれで確かめる。",
    { x: 0.92, y: y + 0.68, w: 5.46, h: 1.35, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });

  card(s, 6.93, y, 5.82, h);
  s.addText("第2段階  frac課題（曲線の本体）", { x: 7.23, y: y + 0.22, w: 5.2, h: 0.35, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0 });
  s.addText(
    "1文字（1音）をどこまで出せば分かるかを、0％から100％まで21段階で掃引して測る。聴覚は1文字と2文字、視覚は1文字と2文字を行う。",
    { x: 7.23, y: y + 0.68, w: 5.22, h: 1.35, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });

  const rows = [
    [{ text: "課題", options: { bold: true } }, { text: "1人あたり", options: { bold: true } }, { text: "所要", options: { bold: true } }, { text: "募集枠", options: { bold: true } }, { text: "測るもの", options: { bold: true } }],
    ["第1段階  聴覚 乙課題", "練習2＋本番42", "10〜12分", "71名", "0.2秒間隔で音の認識が落ちないか"],
    ["第1段階  視覚 乙課題", "練習2＋本番42", "約10分", "48名", "0.2秒間隔で字の認識が落ちないか"],
    ["第2段階  聴覚1文字", "練習5＋本番140", "約14分", "53名", "68音の認識率曲線"],
    ["第2段階  視覚1文字", "練習5＋本番320", "約25分", "53名", "78字の認識率曲線（提示速度2水準）"],
    ["第2段階  聴覚2文字", "練習5＋本番120", "13〜14分", "48名", "前の音の影響を含む曲線"],
    ["第2段階  視覚2文字", "練習5＋本番400", "約26分", "48名", "前の字が残る提示の効果（条件2水準）"],
  ];
  s.addTable(rows, {
    x: 0.62, y: 4.25, w: 12.13, colW: [2.6, 1.85, 1.2, 1.1, 5.38],
    fontFace: FONT, fontSize: 11.5, color: INK, border: { type: "solid", color: LINE, pt: 1 },
    fill: { color: W }, rowH: 0.33, valign: "middle", margin: [2, 6, 2, 6],
  });
  foot(s);
}

/* ----------------------------------------------------------------- 8 乙課題 */
{
  const s = pres.addSlide();
  head(s, "CALIBRATION", "乙課題 — 3つ続けて出し、前のものがどれだけ残るかを測る");
  const y = 1.78;
  const bx = [0.62, 3.55, 6.48, 9.41];
  const labels = ["1文字目", "2文字目", "3文字目", "白紙"];
  labels.forEach((t, i) => {
    card(s, bx[i], y, 2.6, 0.95, i === 3 ? W : TINT);
    s.addText(t, { x: bx[i], y, w: 2.6, h: 0.95, fontFace: FONT, fontSize: 15, bold: true, color: i === 3 ? MUTED : NAVY, align: "center", valign: "middle", margin: 0 });
  });
  [3.22, 6.15, 9.08].forEach((x) => {
    s.addText("→", { x, y: y + 0.25, w: 0.33, h: 0.45, fontFace: FONT, fontSize: 17, color: MUTED, align: "center", margin: 0 });
  });
  s.addText("間隔 S ＝ 50・83・133・200・300・450・700 ミリ秒　／　答えるのは1番目と2番目だけ", {
    x: 0.62, y: y + 1.08, w: 12.13, h: 0.35, fontFace: FONT, fontSize: 13, color: NAVY, bold: true, align: "center", margin: 0 });

  const y2 = 3.5, h2 = 1.75, w2 = 3.94;
  infoCard(s, 0.62, y2, w2, h2, "?", "3番目の役割",
    "2番目の見え終わり・聞こえ終わりを、実際の運用と同じ形（次の文字が来る）でそろえるために置く。3番目は答えない。", TEAL);
  infoCard(s, 0.62 + w2 + 0.22, y2, w2, h2, "=", "判定の仕方",
    "間隔が十分長いときの成績が、その人の急かされていないときの実力である。0.2秒間隔の成績がそれと同じなら干渉はない。", TEAL);
  infoCard(s, 0.62 + 2 * (w2 + 0.22), y2, w2, h2, "+", "副次的に分かること",
    "7つの間隔を全部測るので、成績が落ちない最速の提示速度そのものを推定できる。追加の費用はかからない。", GOLD);

  note(s, 0.62, 5.55, 12.13, "判定の設計",
    "第一段は聴覚60名・視覚40名でマージン8ポイント。保留のときだけ130名・80名に増やして5ポイントで判定し直す。");
  s.addText("この二段階で、干渉がないときに正しく「干渉なし」と結論できる確率は聴覚84.5％・視覚92.7％（1万回のシミュレーションによる実測値）。", {
    x: 0.72, y: 6.42, w: 11.9, h: 0.45, fontFace: FONT, fontSize: 12, color: MUTED, margin: 0 });
  foot(s);
}

/* --------------------------------------------------------------- 9 frac課題 */
{
  const s = pres.addSlide();
  head(s, "MAIN MEASUREMENT", "frac課題 — どこまで届けば分かるかの曲線を、文字ごとに測る");
  const y = 1.78, h = 2.35, w = 3.94;
  infoCard(s, 0.62, y, w, h, "聴", "聴覚1文字",
    "音声の先頭から一部だけ（0％から100％まで21段階）を聞かせて、何の音かを68音の表から答えてもらう。", TEAL);
  infoCard(s, 0.62 + w + 0.22, y, w, h, "聴", "聴覚2文字",
    "前の音を全部聞かせてから、目標の音を途中で打ち切る。前の音とのつながりが認識をどれだけ助けるかが分かる。", TEAL);
  infoCard(s, 0.62 + 2 * (w + 0.22), y, w, h, "視", "視覚1文字",
    "字の鮮明さを0％から100％まで21段階で変えて出し、78字の表から答えてもらう。見せ方は1種類に固定する。", GOLD);

  note(s, 0.62, 4.35, 12.13, "精度の目標",
    "字（音）ごとに約88観測を21段階に散らす。字ごとの推定の誤差は約5.4ポイントになる。");
  s.addText(
    "出題は水準ごとに均等に配ってから順序を混ぜる。毎回独立にくじを引くと、段階ごとの試行数が偏って空の組み合わせが出るためである。\n" +
    "全体の5％を「最後まで見せる（聞かせる）」統制の問題として混ぜ、その正答率が半分に満たない回答者は解析から除く。",
    { x: 0.72, y: 5.3, w: 11.9, h: 1.1, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.45 });
  foot(s);
}

/* --------------------------------------------------------------- 10 提示速度 */
{
  const s = pres.addSlide();
  head(s, "SPEED", "提示速度は2つ測る — ゆっくりの基準と、標準の読み上げ");
  const y = 1.72, h = 3.05, w = 6.06;

  card(s, 0.62, y, w, h);
  s.addText("200ミリ秒／モーラ", { x: 0.95, y: y + 0.25, w: 5.4, h: 0.45, fontFace: FONT, fontSize: 20, bold: true, color: NAVY, margin: 0 });
  s.addText("毎秒5.0モーラ", { x: 0.95, y: y + 0.76, w: 5.4, h: 0.3, fontFace: FONT, fontSize: 13, color: GOLD, bold: true, margin: 0 });
  s.addText(
    "日本語能力試験のもっとも易しい級の聴解音声（毎秒5.05モーラ）とほぼ同じで、初級学習者に最大限配慮した遅さにあたる。競技かるたの読み上げ規則もこの速さである。\n\n" +
    "聴覚の音声もこの速さで作ってあるので、聴覚と視覚を対応づける基準点になる。",
    { x: 0.95, y: y + 1.18, w: 5.46, h: 1.72, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });

  card(s, 0.62 + w + 0.25, y, w, h);
  s.addText("133ミリ秒／モーラ", { x: 0.95 + w + 0.25, y: y + 0.25, w: 5.4, h: 0.45, fontFace: FONT, fontSize: 20, bold: true, color: NAVY, margin: 0 });
  s.addText("毎秒7.5モーラ", { x: 0.95 + w + 0.25, y: y + 0.76, w: 5.4, h: 0.3, fontFace: FONT, fontSize: 13, color: GOLD, bold: true, margin: 0 });
  s.addText(
    "アナウンサーの標準的な読み上げに相当する速さで、日本語能力試験の最上級（毎秒7.07モーラ）をわずかに上回る。早押しクイズが想定する帯域である。\n\n" +
    "乙課題の間隔の水準にも133ミリ秒があるので、2つの実験を直接つないで解釈できる。",
    { x: 0.95 + w + 0.25, y: y + 1.18, w: 5.46, h: 1.72, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });

  note(s, 0.62, 4.95, 12.13, "測り方",
    "視覚1文字課題で、同じ参加者に両方の速さを行ってもらう。個人差を除いて2つの速さを比べられる。");
  s.addText(
    "聴覚は200ミリ秒の1点で測る。モーラの長さを変えると音そのものが変わり、速さと音の中身が混ざってしまうためである。視覚の字は何ミリ秒で出しても同じ画像なので、速さだけを独立に変えられる。",
    { x: 0.72, y: 5.88, w: 11.9, h: 0.8, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.4 });
  foot(s);
}

/* --------------------------------------------------- 11 先行文字の残存（視覚2文字） */
{
  const s = pres.addSlide();
  head(s, "VISUAL CONTEXT", "視覚にも時間の文脈を持たせる — 前の字を残して測る");
  s.addText(
    "流暢な音声には、時間の文脈がもともと入っている。前の音の響きが残り、次の音の準備が先に聞こえる。素の字幕にはそれがない。そこで視覚2文字課題に、前の字が薄くなりながら残る条件を加えて、その効果を測る。",
    { x: 0.72, y: 1.72, w: 11.9, h: 0.8, fontFace: FONT, fontSize: 13.5, color: INK, margin: 0, lineSpacingMultiple: 1.4 });

  const y = 2.6, h = 2.0, w = 6.06;
  card(s, 0.62, y, w, h);
  badge(s, 0.92, y + 0.28, "1", MUTED, W, 0.5);
  s.addText("統制の条件", { x: 1.58, y: y + 0.28, w: 4.2, h: 0.5, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText("1文字目が消えてから2文字目が出る。いまの実装のままの提示である。", {
    x: 0.95, y: y + 0.95, w: w - 0.66, h: 1.0, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });

  card(s, 0.62 + w + 0.25, y, w, h, "E8EEFC");
  badge(s, 0.92 + w + 0.25, y + 0.28, "2", GOLD, W, 0.5);
  s.addText("前の字が残る条件", { x: 1.58 + w + 0.25, y: y + 0.28, w: 4.2, h: 0.5, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText("2文字目が出ているあいだも、1文字目が薄くなりながら同じ枠に重なって残る。薄まり方の時定数は、聴覚で前の音が後の音に影響する時間の長さから決める。", {
    x: 0.95 + w + 0.25, y: y + 0.95, w: w - 0.66, h: 1.1, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });

  note(s, 0.62, 4.85, 12.13, "測定が壊れない理由",
    "答えるのは2文字目である。この条件で増えるのは1文字目の見える時間だけで、2文字目の見える時間は変わらない。");
  s.addText(
    "そのため「長く見せただけではないか」という反論が当たらず、露光量をそろえるための追加の条件を立てずに済む。同じ参加者に両方の条件を行ってもらうので、個人差を除いて比べられる。\n" +
    "なお、ごく短い提示では前の字が残ることでかえって成績が下がるという予測も立つ。どちらに転んでも、時間の文脈が視覚でどう働くかについての知見になる。",
    { x: 0.72, y: 5.75, w: 11.9, h: 1.0, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.4 });
  foot(s);
}

/* --------------------------------------------------------- 12 先行研究との照合 */
{
  const s = pres.addSlide();
  head(s, "VALIDATION", "外部のデータと突き合わせる — 先行研究の実測との照合");
  s.addText(
    "同じ研究グループの先行研究（高尾・丸山・栗原）が、競技かるたの読み上げを途中で切った音声に対して、聞き分けの確信度がどう立ち上がるかを実測している。この結果と、今回測る曲線から予測した値を突き合わせる。",
    { x: 0.72, y: 1.72, w: 11.9, h: 0.8, fontFace: FONT, fontSize: 13.5, color: INK, margin: 0, lineSpacingMultiple: 1.4 });

  const y = 2.7, h = 2.35, w = 3.94;
  infoCard(s, 0.62, y, w, h, "1", "先行研究が測ったもの",
    "6首（ありあ・ありま・はるす・はるの・なげき・なげけ）について、決まり字のあたりを27段階で切り出した音声を12名に聞かせ、確信度が75％に達する時点を推定した。", TEAL);
  infoCard(s, 0.62 + w + 0.22, y, w, h, "2", "軸がそろっている",
    "1段階あたりの平均時間は0.0075秒で、27段階でおよそ1モーラぶんにあたる。今回の課題が0.2秒を21段階で掃引するのと、同じ構造の測り方である。", TEAL);
  infoCard(s, 0.62 + 2 * (w + 0.22), y, w, h, "3", "音声の設計も同じ",
    "先行研究の合成音声は、1モーラ0.2秒・音高はB3とE4という競技かるたの統一規則で作られている。今回の刺激とまったく同じ設計である。", GOLD);

  note(s, 0.62, 5.25, 12.13, "この照合で言えること",
    "今回の実験の外側にあるデータで、曲線から予測した値が当たることを確かめられる。");
  s.addText(
    "動画にする歌は、この6首のうち読手のあいだのばらつきが小さいものから選ぶ。予測と実測が揃っていれば、測った曲線が実際の場面でも通用することの直接の証拠になる。",
    { x: 0.72, y: 6.12, w: 11.9, h: 0.6, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.35 });
  foot(s);
}

/* ------------------------------------------------------------- 13 解析の進め方 */
{
  const s = pres.addSlide();
  head(s, "ANALYSIS PLAN", "解析の進め方 — データを取る前に規則を決め、コミットで固定する");
  const y = 1.8, h = 2.4, w = 3.94;
  infoCard(s, 0.62, y, w, h, "1", "何を先に決めるか",
    "干渉ありと判定する規則、増員に進む条件、回答を除外する基準、必要な人数の根拠を、募集を始める前に文書として確定する。", NAVY);
  infoCard(s, 0.62 + w + 0.22, y, w, h, "2", "どうやって固定するか",
    "その文書を公開リポジトリにコミットする。コミットの記録は誰でも検証できるので、データを見る前に決めたことの証明になる。", NAVY);
  infoCard(s, 0.62 + 2 * (w + 0.22), y, w, h, "3", "論文にどう書くか",
    "解析計画を募集開始前に確定したことと、そのコミットを論文に記載する。判定確率はシミュレーションの実測値を示す。", GOLD);

  note(s, 0.62, 4.42, 12.13, "統計の考え方",
    "「差が出なかった」ではなく「差がマージンより小さい」ことを積極的に示す。非劣性検定の枠組みを使う。");
  s.addText(
    "差が有意でないことは、差が無いことの証拠にならない。そこで、劣化がマージンδより小さいことを検定する。第一段はδ＝8ポイント、保留のときだけ人数を増やしてδ＝5ポイントで判定し直す。二段階を通した誤りの確率は5％以内に保つ。\n" +
    "曲線そのものの推定には、参加者と字を変量効果に置いた階層モデルを使う。観測の少ない字も、全体の傾向を借りて安定して推定できる。",
    { x: 0.72, y: 5.32, w: 11.9, h: 1.3, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.45 });
  foot(s);
}

/* ------------------------------------------------------------------ 14 予算 */
{
  const s = pres.addSlide();
  head(s, "BUDGET", "予算と募集 — 総額はおよそ14万円");
  const rows = [
    [{ text: "課題", options: { bold: true } }, { text: "所要", options: { bold: true } }, { text: "謝礼", options: { bold: true } }, { text: "募集枠", options: { bold: true } }, { text: "小計（税込）", options: { bold: true } }],
    ["第1段階  聴覚 乙課題", "10〜12分", "130ポイント", "71名", "16,011円"],
    ["第1段階  視覚 乙課題", "約10分", "130ポイント", "48名", "10,824円"],
    ["第2段階  聴覚1文字", "約14分", "170ポイント", "53名", "15,450円"],
    ["第2段階  視覚1文字（速度2水準）", "約25分", "300ポイント", "53名", "26,818円"],
    ["第2段階  聴覚2文字", "13〜14分", "170ポイント", "48名", "13,992円"],
    ["第2段階  視覚2文字（条件2水準）", "約26分", "300ポイント", "48名", "24,288円"],
    [{ text: "本体合計", options: { bold: true } }, "", "", { text: "321名", options: { bold: true } }, { text: "107,382円", options: { bold: true } }],
    [{ text: "予備費（保留になったときの増員）", options: { bold: true } }, "", "", "", { text: "28,413円", options: { bold: true } }],
  ];
  s.addTable(rows, {
    x: 0.62, y: 1.8, w: 12.13, colW: [4.6, 1.75, 2.1, 1.5, 2.18],
    fontFace: FONT, fontSize: 12, color: INK, border: { type: "solid", color: LINE, pt: 1 },
    fill: { color: W }, rowH: 0.36, valign: "middle", margin: [2, 8, 2, 8],
  });
  note(s, 0.62, 5.55, 12.13, "予備費の使い道",
    "第1段階が保留になったときに人数を増やして判定し直すために取っておく。優先順位はこれが第1である。");
  s.addText("募集はYahoo!クラウドソーシングで行う。謝礼の時給換算はおよそ720〜780円で全課題をそろえてある。除外を15％見込んで募集枠を上乗せしている。", {
    x: 0.72, y: 6.42, w: 11.9, h: 0.45, fontFace: FONT, fontSize: 12, color: MUTED, margin: 0 });
  foot(s);
}

/* --------------------------------------------------------------- 15 現在の状態 */
{
  const s = pres.addSlide();
  head(s, "STATUS", "いまの状態 — 実験を始められるところまで来ている");
  const y = 1.78, h = 2.3, w = 3.94;
  infoCard(s, 0.62, y, w, h, "済", "倫理審査",
    "承認済み。実験の開始を止めているものは無い。参加者の負担が増える変更は軽微な変更として扱える。", TEAL);
  infoCard(s, 0.62 + w + 0.22, y, w, h, "済", "実験プログラム",
    "6課題すべてを本番仕様にした。同意画面、回答のサーバ保存、完了コード、自分のボタン押しで始める方式、実際の表示時刻の記録が入っている。", TEAL);
  infoCard(s, 0.62 + 2 * (w + 0.22), y, w, h, "済", "刺激",
    "音声は68音ぶんを合成し、有声開始時間の復元と音量の均一化まで済ませて凍結した。字は78字ぶんの画像を用意してある。", TEAL);

  const y2 = 4.3;
  infoCard(s, 0.62, y2, w, 2.1, "残", "サーバの公開",
    "回答を保存するスクリプトを公開する作業が残っている。これが済めば募集を開始できる。", GOLD);
  infoCard(s, 0.62 + w + 0.22, y2, w, 2.1, "残", "追加する2要因",
    "視覚1文字の提示速度2水準と、視覚2文字の前の字が残る条件を実装中である。", GOLD);
  infoCard(s, 0.62 + 2 * (w + 0.22), y2, w, 2.1, "残", "論文",
    "想定結果版を情報処理学会論文誌の体裁で書いてある。実データが入り次第、結果の章を差し替える。", GOLD);
  foot(s);
}

/* ------------------------------------------------------------------ 16 予定 */
{
  const s = pres.addSlide();
  head(s, "SCHEDULE", "これからの進み方 — 9月末の投稿に向けて");
  const steps = [
    ["8月上旬", "第1段階の募集を開始する", "サーバを公開し、解析計画を確定してコミットで固定してから、聴覚71名・視覚48名の募集を始める。"],
    ["8月中旬", "第2段階の準備を並行して進める", "第1段階のデータが集まるあいだに、提示速度2水準と前の字が残る条件の実装を仕上げ、時定数を決める。"],
    ["8月下旬", "第2段階の募集を開始する", "第1段階の判定を確認したうえで、frac課題4本の募集を始める。"],
    ["9月中旬", "データがそろう", "曲線を推定し、変換gを作り、先行研究の実測と突き合わせる。"],
    ["9月下旬", "インタラクションに投稿する", "論文の結果の章を実データで差し替える。競技かるたの動画も作る。"],
  ];
  let y = 1.72;
  steps.forEach(([when, what, detail], i) => {
    card(s, 0.62, y, 12.13, 0.88);
    s.addText(when, { x: 0.92, y: y + 0.06, w: 1.5, h: 0.76, fontFace: FONT, fontSize: 13, bold: true, color: GOLD, margin: 0, valign: "middle" });
    s.addText(what, { x: 2.5, y: y + 0.07, w: 4.0, h: 0.74, fontFace: FONT, fontSize: 13.5, bold: true, color: NAVY, margin: 0, valign: "middle" });
    s.addText(detail, { x: 6.6, y: y + 0.07, w: 5.9, h: 0.74, fontFace: FONT, fontSize: 12, color: INK, margin: 0, valign: "middle", lineSpacingMultiple: 1.2 });
    y += 0.96;
  });
  s.addText("投稿の候補は9月末のインタラクションである。実データを入れた形で出せる最も早い機会にあたる。", {
    x: 0.72, y: 6.5, w: 11.9, h: 0.35, fontFace: FONT, fontSize: 12, color: MUTED, margin: 0 });
  foot(s);
}

/* ------------------------------------------------------------------ 17 まとめ */
{
  const s = pres.addSlide();
  s.background = { color: NAVY };
  s.addText("SUMMARY", { x: 0.62, y: 0.4, w: 8, h: 0.3, fontFace: FONT, fontSize: 11, bold: true, color: GOLD, charSpacing: 3, margin: 0 });
  s.addText("まとめ — したいこと、測ること、作るもの", {
    x: 0.6, y: 0.72, w: 12.15, h: 0.7, fontFace: FONT, fontSize: 27, bold: true, color: W, margin: 0 });

  const items = [
    ["1", "したいこと", "音声で「いち早く理解する」ゲーム性を、聴覚に頼れない人にも視覚で同じだけ届ける。入力は普通の文章、出力は音声と、表記どおりのかな列である。"],
    ["2", "測ること", "乙課題で「どの速さまで前の文字が消されないか」を、frac課題で「どこまで届けば分かるか」の曲線を、68音と78字について測る。視覚は提示速度2水準と、前の字が残る条件も測る。"],
    ["3", "作るもの", "早押しクイズ向けのコマンドラインツールと、競技かるたの動画。どちらも同じ曲線と同じ変換gから作る。"],
    ["4", "いまの位置", "倫理審査は承認され、6課題すべてが本番仕様になっている。サーバを公開すれば募集を開始できる。9月末の投稿を目指す。"],
  ];
  let y = 1.85;
  items.forEach(([n, t, d]) => {
    badge(s, 0.68, y + 0.1, n, GOLD, NAVY, 0.5);
    s.addText(t, { x: 1.38, y: y + 0.02, w: 2.5, h: 0.5, fontFace: FONT, fontSize: 16, bold: true, color: ICE, margin: 0, valign: "middle" });
    s.addText(d, { x: 3.95, y: y, w: 8.65, h: 1.05, fontFace: FONT, fontSize: 13, color: W, margin: 0, lineSpacingMultiple: 1.35, valign: "top" });
    y += 1.24;
  });
  s.addText("github.com/qurihara/iFont  /  scrapbox.io/qurihara/iFont  /  2026-08-04", {
    x: 0.62, y: 6.85, w: 11, h: 0.4, fontFace: FONT, fontSize: 11, color: SOFT, margin: 0 });
  page += 1;
  s.addText(String(page), { x: 11.9, y: 6.85, w: 0.8, h: 0.4, fontFace: FONT, fontSize: 10, color: SOFT, align: "right", margin: 0 });
}

const out = process.argv[2];
pres.writeFile({ fileName: out }).then(() => console.log("書き出した: " + out));

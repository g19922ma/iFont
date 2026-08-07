// iFont 全体像と現状 2026-08-07 版
const pptxgen = require("pptxgenjs");

const NAVY = "1E2A5E", INK = "22283C", MUTED = "6B7280", TINT = "F4F6FB", LINE = "E3E6EE";
const GOLD = "C8A44D", TEAL = "2E7D8F", RED = "C25B4E", ICE = "CADCFC", SOFT = "9FB0D8", W = "FFFFFF";
const FONT = "Yu Gothic";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "iFont project";
pres.title = "iFont 全体像と現状 2026-08-07";

let page = 0;

function head(s, eyebrow, title) {
  s.addText(eyebrow, { x: 0.62, y: 0.4, w: 11, h: 0.3, fontFace: FONT, fontSize: 11, bold: true, color: GOLD, charSpacing: 3, margin: 0 });
  s.addText(title, { x: 0.6, y: 0.72, w: 12.15, h: 0.72, fontFace: FONT, fontSize: 27, bold: true, color: NAVY, margin: 0, valign: "top" });
}
function foot(s, dark) {
  page += 1;
  s.addText("iFont", { x: 0.62, y: 6.95, w: 2, h: 0.3, fontFace: FONT, fontSize: 10, color: dark ? SOFT : MUTED, margin: 0 });
  s.addText(String(page), { x: 11.9, y: 6.95, w: 0.8, h: 0.3, fontFace: FONT, fontSize: 10, color: dark ? SOFT : MUTED, align: "right", margin: 0 });
}
function card(s, x, y, w, h, fill) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.06, fill: { color: fill || TINT }, line: { color: LINE, width: 1 } });
}
function badge(s, x, y, text, bg, fg, d) {
  const dia = d || 0.42;
  s.addShape(pres.ShapeType.ellipse, { x, y, w: dia, h: dia, fill: { color: bg || NAVY }, line: { color: bg || NAVY, width: 1 } });
  s.addText(text, { x, y, w: dia, h: dia, fontFace: FONT, fontSize: dia > 0.5 ? 15 : 13, bold: true, color: fg || W, align: "center", valign: "middle", margin: 0 });
}
function infoCard(s, x, y, w, h, num, title, body, accent) {
  card(s, x, y, w, h);
  badge(s, x + 0.28, y + 0.28, num, accent || NAVY);
  s.addText(title, { x: x + 0.82, y: y + 0.26, w: w - 1.1, h: 0.42, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText(body, { x: x + 0.28, y: y + 0.82, w: w - 0.56, h: h - 1.05, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.28, valign: "top" });
}
function note(s, x, y, w, label, text, fill) {
  card(s, x, y, w, 0.72, fill || "E8EEFC");
  s.addText(label, { x: x + 0.3, y: y + 0.06, w: 2.1, h: 0.6, fontFace: FONT, fontSize: 12, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText(text, { x: x + 2.35, y: y + 0.06, w: w - 2.65, h: 0.6, fontFace: FONT, fontSize: 12, color: INK, margin: 0, valign: "middle" });
}

/* ------------------------------------------------------------ 1 表紙 */
{
  const s = pres.addSlide();
  s.background = { color: NAVY };
  s.addText("iFont", { x: 0.9, y: 1.5, w: 6, h: 1.0, fontFace: FONT, fontSize: 54, bold: true, color: W, margin: 0 });
  s.addText("インクルーシブ字幕プロジェクト — 全体像と進め方", { x: 0.92, y: 2.5, w: 10, h: 0.5, fontFace: FONT, fontSize: 19, color: ICE, margin: 0 });
  s.addText(
    "音声で「いち早く理解する」ゲーム性を、視覚でも同じだけ成立させたい。\n" +
    "そのために、かな1文字ごとの「聞こえやすさ」と「見えやすさ」を同じ物差しで測り、\n" +
    "測ったデータで、音声と同期して動く字幕を作る。",
    { x: 0.92, y: 3.3, w: 10.5, h: 1.5, fontFace: FONT, fontSize: 15, color: W, margin: 0, lineSpacingMultiple: 1.5 });
  s.addShape(pres.ShapeType.rect, { x: 0.92, y: 5.05, w: 1.6, h: 0.035, fill: { color: GOLD }, line: { color: GOLD, width: 0 } });
  s.addText("2026-08-07  自己完結版（初めて読む方向け）", { x: 0.92, y: 5.3, w: 10, h: 0.36, fontFace: FONT, fontSize: 13, color: ICE, margin: 0 });
  s.addText("github.com/qurihara/iFont  /  scrapbox.io/qurihara/iFont", { x: 0.92, y: 5.75, w: 10, h: 0.36, fontFace: FONT, fontSize: 11, color: SOFT, margin: 0 });
}

/* ------------------------------------------------------- 2 やりたいこと */
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
  note(s, 0.62, 4.45, 12.13, "設計目標", "音声を聞いている人と、字幕を見ている人が、同じ時点に同じだけ分かること。");
  s.addText("この目標を数値で満たすために、かな1文字ごとに「音をどこまで聞かせれば分かるか」と「字をどれだけ見せれば分かるか」を測り、両者を対応づける。",
    { x: 0.72, y: 5.45, w: 11.9, h: 0.9, fontFace: FONT, fontSize: 13, color: MUTED, margin: 0, lineSpacingMultiple: 1.4 });
  foot(s);
}

/* ------------------------------------------------------ 3 仕組みの全体像 */
{
  const s = pres.addSlide();
  head(s, "SYSTEM", "仕組みの全体像 — 1つの文章から、音声とかな列を同期して出す");
  const y = 1.8;
  const boxes = [
    [0.62, 2.6, "入力", "かな漢字まじり文\n例:「日本で一番高い山は何でしょう」", TINT],
    [3.45, 2.6, "前処理", "読みを決める\n形態素解析にふりがなで上書きできる", TINT],
    [6.28, 3.1, "出力①  音声", "読み上げ音声。どのモーラが何秒後に鳴るかを合成前に厳密に算出する", "E8EEFC"],
    [9.62, 3.13, "出力②  かな列", "漢字は読みかなに直し、既存のかなは表記どおりに残す。各字を音声に同期して少しずつ見せる", "E8EEFC"],
  ];
  boxes.forEach(([x, w, t, b, f]) => {
    card(s, x, y, w, 1.75, f);
    s.addText(t, { x: x + 0.23, y: y + 0.2, w: w - 0.46, h: 0.3, fontFace: FONT, fontSize: 12, bold: true, color: f === TINT ? GOLD : NAVY, margin: 0 });
    s.addText(b, { x: x + 0.23, y: y + 0.55, w: w - 0.46, h: 1.15, fontFace: FONT, fontSize: 11.5, color: INK, margin: 0, lineSpacingMultiple: 1.25 });
  });
  [3.06, 5.89].forEach((x) => s.addText("→", { x, y: y + 0.6, w: 0.42, h: 0.5, fontFace: FONT, fontSize: 20, color: MUTED, align: "center", margin: 0 }));
  note(s, 0.62, 3.85, 12.13, "同期の規則", "表示する字は「その字が実際に読まれる音」に合わせる。「を」はオの音、「ゑ」はエの音、助詞の「は」はワの音。");
  s.addText(
    "単独の音を持たない「っ・ゃ・ゅ・ょ」は、隣の字と組にする描画規則で扱う。\n" +
    "合成の要はタイムラインの決定論性にある。どのモーラが何秒後に鳴るかを合成前に算出できるので、視覚側はそれに追従すればよい。",
    { x: 0.72, y: 4.8, w: 11.9, h: 1.3, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.45 });
  foot(s);
}

/* ---------------------------------------------------------- 4 中核の考え */
{
  const s = pres.addSlide();
  head(s, "CORE IDEA", "中核の考え — 「聞こえやすさ」と「見えやすさ」を同じ物差しでつなぐ");
  const y = 1.8, h = 2.5;
  card(s, 0.62, y, 5.2, h);
  s.addText("聴覚の曲線", { x: 0.92, y: y + 0.25, w: 4.6, h: 0.35, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0 });
  s.addText("かな1音について、音の先頭から何％まで聞かせたら何％の人が正しく答えられるかを測る。対象は互いに聞き分けられる68音。",
    { x: 0.92, y: y + 0.72, w: 4.6, h: 1.5, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.35 });
  card(s, 7.55, y, 5.2, h);
  s.addText("視覚の曲線", { x: 7.85, y: y + 0.25, w: 4.6, h: 0.35, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0 });
  s.addText("かな1文字について、字をどれだけ鮮明に出したら何％の人が正しく答えられるかを測る。対象は画面に出る全字形78字。",
    { x: 7.85, y: y + 0.72, w: 4.6, h: 1.5, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.35 });
  card(s, 6.05, y + 0.55, 1.28, 1.4, NAVY);
  s.addText("変換\ng", { x: 6.05, y: y + 0.55, w: 1.28, h: 1.4, fontFace: FONT, fontSize: 19, bold: true, color: W, align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 1.1 });
  note(s, 0.62, 4.55, 12.13, "つなぎ方", "同じ認識率になる点どうしを対応づける。gが決まれば、音声の進み方に合わせて各字の見せ方を機械的に設計できる。");
  s.addText("曲線は文字ごとに違う。濁点のある字や小書きの字は、わずかな提示では取り違えられやすい。だから字ごとに1本ずつ推定する。データの少ない字も、字を変量効果に置いた階層モデルで安定して推定する。",
    { x: 0.72, y: 5.5, w: 11.9, h: 1.0, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.4 });
  foot(s);
}

/* -------------------------------------------------------- 5 文字と音の対応 */
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
  note(s, 0.62, 5.45, 12.13, "測る量", "68音 × 78字の認識率曲線と、その対応づけ。日本語のかなの基礎データとしても公開する。");
  foot(s);
}

/* ------------------------------------------------------------ 6 作る出力 */
{
  const s = pres.addSlide();
  head(s, "OUTPUTS", "作るものは2つ — 早押しクイズ向けの道具と、競技かるたの動画");
  const y = 1.8, h = 3.5, w = 6.06;
  card(s, 0.62, y, w, h);
  badge(s, 0.92, y + 0.3, "A", NAVY, W, 0.62);
  s.addText("早押しクイズ向けのコマンドラインツール", { x: 1.68, y: y + 0.3, w: 4.2, h: 0.62, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText(
    "現代日本語の文章を入れると、読み上げ音声と、それに同期して1文字ずつ現れるかな列を出す。\n\n" +
    "各モーラが何秒後に鳴るかを合成前に算出して視覚を追従させる。音の高さの設計は不要で、必要なのは時間の正確さである。\n\n" +
    "品質管理として、無声破裂音の有声開始時間の復元、モーラごとの音量の均一化、無声化した母音の復元を合成の工程に組み込む。",
    { x: 0.95, y: y + 1.12, w: w - 0.66, h: h - 1.35, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });
  card(s, 0.62 + w + 0.25, y, w, h);
  badge(s, 0.92 + w + 0.25, y + 0.3, "B", GOLD, W, 0.62);
  s.addText("競技かるたの動画", { x: 1.68 + w + 0.25, y: y + 0.3, w: 4.2, h: 0.62, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText(
    "百人一首のうち一部の歌について、読み上げ音声と同期したかな列の動画を作る。\n\n" +
    "音声は既に作ってある競技かるたの読み上げを使う。歌は、先行研究が人間の読手と合成音声で聞き分けの立ち上がりを実測している6首から選ぶ。\n\n" +
    "この動画は、測った曲線から予測した見え方が、実際の聞こえ方と揃っているかを見せる場になる。",
    { x: 0.95 + w + 0.25, y: y + 1.12, w: w - 0.66, h: h - 1.35, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });
  note(s, 0.62, 5.6, 12.13, "共通の土台", "どちらの出力も、同じ68音×78字の曲線と同じ変換gから作る。データが1つで応用が2つという構成である。");
  foot(s);
}

/* ---------------------------------------------------------- 7 提示速度 */
{
  const s = pres.addSlide();
  head(s, "SPEED", "提示速度という軸 — 1モーラを何ミリ秒で届けるか");
  s.addText("運用では、かなが一定の速さで次々に届く。1モーラあたり何ミリ秒か、というこの速さを提示速度と呼ぶ。ある速度でiFontを成立させるには、次の2つが両方そろわなければならない。",
    { x: 0.72, y: 1.72, w: 11.9, h: 0.8, fontFace: FONT, fontSize: 13.5, color: INK, margin: 0, lineSpacingMultiple: 1.4 });
  const y = 2.6, h = 1.75, w = 6.06;
  infoCard(s, 0.62, y, w, h, "1", "続けて出しても認識が落ちないという保証",
    "後ろから次の文字が来ることで手前の文字の認識が妨げられるなら、孤立して測った曲線は運用の場面を予測しない。", TEAL);
  infoCard(s, 0.62 + w + 0.25, y, w, h, "2", "その速度での認識率曲線",
    "かな1文字ごとに、どこまで提示すれば何％の人が分かるかの曲線。", GOLD);
  s.addText("→ 保証を第1段階の乙課題が、曲線を第2段階のfrac課題が引き受ける。", {
    x: 0.72, y: 4.5, w: 11.9, h: 0.4, fontFace: FONT, fontSize: 14, bold: true, color: NAVY, margin: 0 });
  note(s, 0.62, 5.05, 12.13, "速度の目安", "毎秒5.0モーラ＝200ms（日本語能力試験N5相当）／毎秒6.0＝167ms／毎秒7.5＝133ms（アナウンサーの標準的な読み上げ）");
  s.addText(
    "自然な抑揚のまま合成すると、モーラの長さは69〜163ミリ秒でばらつく。定速で合成すれば長さは一定になる。どちらを製品に採るかで、曲線が長さをまたいで移せるかを確かめる必要があるかどうかが決まる。",
    { x: 0.72, y: 5.98, w: 11.9, h: 0.8, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.4 });
  foot(s);
}

/* --------------------------------------------------------- 8 第1段階 乙課題 */
{
  const s = pres.addSlide();
  head(s, "STAGE 1", "乙課題 — どの速さまで、文字は互いに独立でいられるか");
  const y = 1.78;
  const bx = [0.62, 3.55, 6.48, 9.41];
  ["1文字目", "2文字目", "3文字目", "白紙"].forEach((t, i) => {
    card(s, bx[i], y, 2.6, 0.9, i === 3 ? W : TINT);
    s.addText(t, { x: bx[i], y, w: 2.6, h: 0.9, fontFace: FONT, fontSize: 15, bold: true, color: i === 3 ? MUTED : NAVY, align: "center", valign: "middle", margin: 0 });
  });
  [3.22, 6.15, 9.08].forEach((x) => s.addText("→", { x, y: y + 0.22, w: 0.33, h: 0.45, fontFace: FONT, fontSize: 17, color: MUTED, align: "center", margin: 0 }));
  s.addText("提示速度 S ＝ 50・83・133・167・200・450・700 ミリ秒　／　判定に使うのは1文字目", {
    x: 0.62, y: y + 1.02, w: 12.13, h: 0.35, fontFace: FONT, fontSize: 13, color: NAVY, bold: true, align: "center", margin: 0 });

  const y2 = 3.4, h2 = 1.75, w2 = 3.94;
  infoCard(s, 0.62, y2, w2, h2, "?", "3番目の役割",
    "2番目の見え終わり・聞こえ終わりを、運用と同じ形（次の文字が来る）にそろえるために置く。3番目は答えない。", TEAL);
  infoCard(s, 0.62 + w2 + 0.22, y2, w2, h2, "=", "判定の仕方",
    "間隔が十分長いとき（450・700）の成績が、その人の急かされていないときの実力。各速度の成績がそれと同じなら独立といえる。", TEAL);
  infoCard(s, 0.62 + 2 * (w2 + 0.22), y2, w2, h2, "±", "統計の枠組み",
    "「差がない」ではなく「差がマージンδより小さい」ことを積極的に検定する。非劣性検定の枠組みを使う。", GOLD);
  note(s, 0.62, 5.45, 12.13, "判定の設計", "第一段は聴覚60名・視覚40名でδ＝8ポイント。保留のときだけ130名・80名に増やしてδ＝5ポイントで判定し直す。");
  s.addText("真の差がないときに正しく「独立」と結論できる確率は、聴覚84.5％・視覚92.7％（1万回のシミュレーションによる実測値）。聴覚版と視覚版を同じ設計で別々に実施する。", {
    x: 0.72, y: 6.32, w: 11.9, h: 0.5, fontFace: FONT, fontSize: 12, color: MUTED, margin: 0 });
  foot(s);
}

/* ------------------------------------------------------- 9 限界独立速度 */
{
  const s = pres.addSlide();
  head(s, "LIMIT SPEED", "限界独立速度 X — 乙課題から得る、いちばん重要な数値");
  s.addText("乙課題は7つの速度すべてで独立かどうかを判定する。そこから、文字が互いに独立でいられるいちばん速い速度が求まる。これを限界独立速度 X と呼ぶ。",
    { x: 0.72, y: 1.72, w: 11.9, h: 0.7, fontFace: FONT, fontSize: 13.5, color: INK, margin: 0, lineSpacingMultiple: 1.4 });
  const y = 2.5, h = 2.0, w = 3.94;
  infoCard(s, 0.62, y, w, h, "1", "聴覚と視覚で別々に出る",
    "妨害の効きやすい向きがモダリティで違うため、2つの値が求まる。運用速度は両方を満たす必要があるので、遅いほうを採る。", NAVY);
  infoCard(s, 0.62 + w + 0.22, y, w, h, "2", "区間としてしか出ない",
    "水準が離散なので、分かるのは「133は通った、83は落ちた」といった情報だけ。保守的に区間の上端を採る。", NAVY);
  infoCard(s, 0.62 + 2 * (w + 0.22), y, w, h, "3", "水準の置き方",
    "関心のある帯域は83〜200ミリ秒なので、そこに水準を厚く置く。頭打ちの基準には450と700を使う。", GOLD);
  note(s, 0.62, 4.72, 12.13, "Xが決めること", "Xより遅い速度で運用するなら、孤立して測った曲線をそのまま持ち込める。Xより速いなら、文脈を含む測り方に変える。");
  s.addText(
    "つまり X は「1文字ずつ測った曲線だけで運用を予測してよいか」の境目である。どちらに転んでもiFontは作れる。変わるのは構成の単純さと精度であって、実現可能性ではない。\n" +
    "そして「この帯域で干渉が起きるかどうか」自体、まだ誰も測っていない知見なので、どちらの結果も論文の内容になる。",
    { x: 0.72, y: 5.62, w: 11.9, h: 1.1, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.45 });
  foot(s);
}

/* ---------------------------------------------------------- 10 判断フロー */
{
  const s = pres.addSlide();
  head(s, "DECISION", "判断フロー — 乙課題の結果で、第2段階の形が決まる");
  const y = 1.72;
  const st = [[0.62, "第1段階の乙課題"], [4.0, "限界独立速度 X が区間で出る"], [7.9, "第2段階の速度と形が決まる"]];
  st.forEach(([x, t], i) => {
    const w = i === 0 ? 3.0 : (i === 1 ? 3.5 : 4.85);
    card(s, x, y, w, 0.62, i === 2 ? "E8EEFC" : TINT);
    s.addText(t, { x, y, w, h: 0.62, fontFace: FONT, fontSize: 13, bold: true, color: NAVY, align: "center", valign: "middle", margin: 0 });
  });
  [3.68, 7.56].forEach((x) => s.addText("→", { x, y: y + 0.1, w: 0.32, h: 0.42, fontFace: FONT, fontSize: 17, color: MUTED, align: "center", margin: 0 }));

  const rows = [
    [{ text: "乙課題の結果", options: { bold: true } }, { text: "第2段階で採る形", options: { bold: true } }, { text: "得られるもの", options: { bold: true } }, { text: "引き換えに失うもの", options: { bold: true } }],
    [{ text: "133ミリ秒で独立", options: { bold: true, color: TEAL } }, "133ミリ秒で、文脈なしのfrac課題", "構成が単純／精度が高い／アナウンサーの標準速度という外的基準", "競技かるたの読み上げ規則との照合"],
    [{ text: "133で干渉、200で独立", options: { bold: true, color: GOLD } }, "167ミリ秒前後で定速合成を聴いて判断。耐えるならその速度で文脈なし、耐えないなら133ミリ秒で文脈つき", "前者は単純さと精度／後者は外的基準", "前者は「やや遅い」という但し書き／後者は精度"],
    [{ text: "200でも干渉", options: { bold: true, color: RED } }, "133ミリ秒で、文脈つきのfrac課題", "外的基準／「干渉は速度によらず存在する」という知見そのものが結果になる", "構成の単純さと精度"],
    [{ text: "133が音として成立しない", options: { bold: true, color: MUTED } }, "限界独立速度そのものを運用点にする", "実測にもとづく速度の根拠", "アナウンサー速度という説明"],
  ];
  s.addTable(rows, {
    x: 0.62, y: 2.62, w: 12.13, colW: [2.5, 3.5, 3.3, 2.83],
    fontFace: FONT, fontSize: 11.5, color: INK, border: { type: "solid", color: LINE, pt: 1 },
    fill: { color: W }, rowH: 0.5, valign: "middle", margin: [4, 7, 4, 7],
  });
  note(s, 0.62, 5.95, 12.13, "全てに共通する点", "どの枝に進んでもiFontは作れる。変わるのは構成の複雑さと精度、そして説明の据わりの良さである。");
  foot(s);
}

/* ------------------------------------------------------- 11 第2段階 frac課題 */
{
  const s = pres.addSlide();
  head(s, "STAGE 2", "frac課題 — どこまで届けば分かるかの曲線を、字ごとに測る");
  s.addText("かな1文字（1音）を途中まで提示して、それが何だったかを答えてもらう。提示の度合いを0％から100％まで21段階で変えると、認識率曲線が引ける。提示の形は乙課題の結果で決まる。",
    { x: 0.72, y: 1.7, w: 11.9, h: 0.7, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.35 });
  const y = 2.45, h = 2.3, w = 6.06;
  card(s, 0.62, y, w, h);
  badge(s, 0.92, y + 0.28, "A", TEAL, W, 0.5);
  s.addText("文脈なし（独立のとき）", { x: 1.58, y: y + 0.28, w: 4.3, h: 0.5, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText("対象の文字だけを提示して打ち切る。運用でも隣の文字の影響がないので、これで足りる。", {
    x: 0.95, y: y + 0.92, w: w - 0.66, h: 0.72, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });
  s.addText("［ 対象をfrac％まで ］ → 白紙 → 回答", {
    x: 0.95, y: y + 1.68, w: w - 0.66, h: 0.4, fontFace: FONT, fontSize: 12, color: TEAL, bold: true, margin: 0 });

  card(s, 0.62 + w + 0.25, y, w, h, "E8EEFC");
  badge(s, 0.92 + w + 0.25, y + 0.28, "B", GOLD, W, 0.5);
  s.addText("文脈つき（干渉があるとき）", { x: 1.58 + w + 0.25, y: y + 0.28, w: 4.3, h: 0.5, fontFace: FONT, fontSize: 15, bold: true, color: NAVY, margin: 0, valign: "middle" });
  s.addText("対象を打ち切ったあと、スロットの境界で次の文字を出す。運用と同じ時間構造で測る。打ち切りの後に来るので、提示の割合の定義は壊れない。", {
    x: 0.95 + w + 0.25, y: y + 0.92, w: w - 0.66, h: 0.72, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.3 });
  s.addText("［ 対象をfrac％まで ］［ 残り ］［ 次の文字 ］ → 回答", {
    x: 0.95 + w + 0.25, y: y + 1.68, w: w - 0.66, h: 0.4, fontFace: FONT, fontSize: 12, color: GOLD, bold: true, margin: 0 });

  note(s, 0.62, 4.88, 12.13, "精度の目標", "字（音）ごとに約88観測を21段階に散らす。字ごとの推定の誤差は約5.4ポイントになる。");
  s.addText(
    "対象は聴覚68音・視覚78字。出題は水準ごとに均等に配ってから順序を混ぜる。全体の5％を「最後まで見せる」統制の問題として混ぜ、その正答率が半分に満たない回答者は解析から除く。\n" +
    "聴覚には、前の音とのつながりが認識をどれだけ助けるかを測る2文字課題も置く。視覚には、前の字が薄く残る提示の効果を測る2文字課題を置く。",
    { x: 0.72, y: 5.72, w: 11.9, h: 1.1, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.4 });
  foot(s);
}

/* --------------------------------------------------------- 12 影響の向き */
{
  const s = pres.addSlide();
  head(s, "DIRECTION", "課題の分担 — 影響の向きで分けている");
  s.addText("同じ「続けて出す」でも、乙課題とfrac課題では測っている影響の向きが違う。だから両方を、聴覚と視覚の両方で行う。",
    { x: 0.72, y: 1.72, w: 11.9, h: 0.5, fontFace: FONT, fontSize: 13.5, color: INK, margin: 0 });
  const rows = [
    [{ text: "　", options: { bold: true } }, { text: "答える文字", options: { bold: true } }, { text: "その前", options: { bold: true } }, { text: "その後ろ", options: { bold: true } }, { text: "測る向き", options: { bold: true } }],
    [{ text: "乙課題", options: { bold: true } }, "1文字目", "何も来ない", "2文字目・3文字目", { text: "後ろ → 前", options: { bold: true, color: NAVY } }],
    [{ text: "frac課題（2文字版）", options: { bold: true } }, "2文字目", "1文字目（最後まで提示）", "何も来ない", { text: "前 → 後ろ", options: { bold: true, color: NAVY } }],
    [{ text: "frac課題（文脈つき）", options: { bold: true } }, "真ん中", "1文字目（任意）", "次の文字", { text: "両方", options: { bold: true, color: GOLD } }],
  ];
  s.addTable(rows, {
    x: 0.62, y: 2.35, w: 12.13, colW: [3.0, 1.9, 3.0, 2.4, 1.83],
    fontFace: FONT, fontSize: 12, color: INK, border: { type: "solid", color: LINE, pt: 1 },
    fill: { color: W }, rowH: 0.44, valign: "middle", margin: [3, 8, 3, 8],
  });
  const y = 4.3, h = 1.5, w = 6.06;
  infoCard(s, 0.62, y, w, h, "耳", "聴覚は前から後ろへの妨害が強い",
    "前の音の響きが次の音にかぶり、その影響は数百ミリ秒におよぶ。逆向きは20ミリ秒に満たない。", TEAL);
  infoCard(s, 0.62 + w + 0.25, y, w, h, "目", "視覚は後ろから前への妨害が強い",
    "あとから同じ場所に出た字が、直前の字の処理を途中で打ち切ってしまう。", GOLD);
  note(s, 0.62, 5.98, 12.13, "だから両方が要る", "聴覚で警戒すべき向きはfrac課題の2文字版が、視覚で警戒すべき向きは乙課題が押さえる。");
  foot(s);
}

/* --------------------------------------------------------- 13 刺激の品質 */
{
  const s = pres.addSlide();
  head(s, "STIMULUS QUALITY", "刺激の品質管理 — 測る前に、音が音として成立していること");
  s.addText("字ごとの曲線がその字の知覚を表すためには、最後まで提示したときにその音だと分かることが前提になる。合成音声はそのままではこの前提を満たさないので、実測して直す工程を置く。",
    { x: 0.72, y: 1.7, w: 11.9, h: 0.7, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.35 });
  const y = 2.45, h = 2.2, w = 2.93;
  const items = [
    ["1", "有声開始時間の復元", "無声破裂音は素の合成だと有声開始まで5〜10ミリ秒しかなく濁って聞こえる。子音長を字ごとの倍率で伸ばし、自然な25〜45ミリ秒に戻す。", TEAL],
    ["2", "後処理による音色の補正", "ぱ行は両唇音らしい低域寄りの傾斜を掛け、ぷは気息を増幅する。ぽは促音の後という明瞭な環境から切り出す。", TEAL],
    ["3", "音量の均一化", "各モーラの聞こえの大きさを中央値にそろえる。後から増幅すると音声圧縮で割れるので、合成時に底上げする。", TEAL],
    ["4", "切り出し窓の実測", "音声圧縮の復号には46ミリ秒の遅れが入る。これを算入して、モーラの実体の始まりから終わりまでを鳴らす。", GOLD],
  ];
  items.forEach(([n, t, b, c], i) => {
    const x = 0.62 + i * (w + 0.22);
    card(s, x, y, w, h);
    badge(s, x + 0.24, y + 0.24, n, c, W, 0.44);
    s.addText(t, { x: x + 0.24, y: y + 0.78, w: w - 0.48, h: 0.5, fontFace: FONT, fontSize: 13, bold: true, color: NAVY, margin: 0, valign: "top" });
    s.addText(b, { x: x + 0.24, y: y + 1.28, w: w - 0.48, h: h - 1.45, fontFace: FONT, fontSize: 11.5, color: INK, margin: 0, lineSpacingMultiple: 1.25 });
  });
  note(s, 0.62, 4.88, 12.13, "検証の仕方", "処方はすべてスクリプトに焼き込み、字ごとの倍率と後処理を付録の表として公開する。実測値で検算する。");
  s.addText(
    "そして最終的な検証は実験そのものが行う。字ごとの曲線が床に張り付く音があれば、それは刺激の問題として検出される。自然音声より聞き取りやすくする加工ではなく、自然音声が持つ手がかりの復元である。",
    { x: 0.72, y: 5.78, w: 11.9, h: 0.9, fontFace: FONT, fontSize: 12.5, color: INK, margin: 0, lineSpacingMultiple: 1.4 });
  foot(s);
}

/* --------------------------------------------------------- 14 解析の進め方 */
{
  const s = pres.addSlide();
  head(s, "ANALYSIS", "解析の進め方 — データを取る前に規則を決め、コミットで固定する");
  const y = 1.8, h = 2.4, w = 3.94;
  infoCard(s, 0.62, y, w, h, "1", "何を先に決めるか",
    "干渉ありと判定する規則、増員に進む条件、回答を除外する基準、必要な人数の根拠を、募集を始める前に文書として確定する。", NAVY);
  infoCard(s, 0.62 + w + 0.22, y, w, h, "2", "どうやって固定するか",
    "その文書を公開リポジトリにコミットする。コミットの記録は誰でも検証できるので、データを見る前に決めたことの証明になる。", NAVY);
  infoCard(s, 0.62 + 2 * (w + 0.22), y, w, h, "3", "曲線の推定",
    "参加者と字を変量効果に置いた階層モデルを使う。観測の少ない字も、全体の傾向を借りて安定して推定できる。", GOLD);
  note(s, 0.62, 4.42, 12.13, "統計の考え方", "「差が出なかった」ではなく「差がマージンより小さい」ことを積極的に示す。非劣性検定の枠組みを使う。");
  s.addText(
    "差が有意でないことは、差が無いことの証拠にならない。データが足りないだけでも有意差は出ないので、雑な実験ほど「干渉なし」に見えてしまう。そこで劣化がマージンδより小さいことを検定する。\n" +
    "第一段はδ＝8ポイント、保留のときだけ人数を増やしてδ＝5ポイントで判定し直す。二段階を通した誤りの確率は5％以内に保つ。",
    { x: 0.72, y: 5.32, w: 11.9, h: 1.3, fontFace: FONT, fontSize: 13, color: INK, margin: 0, lineSpacingMultiple: 1.45 });
  foot(s);
}

/* ------------------------------------------------------------ 15 予算 */
{
  const s = pres.addSlide();
  head(s, "BUDGET", "予算と募集 — 第1段階は確定、第2段階は判断フローで決まる");
  const rows = [
    [{ text: "段階", options: { bold: true } }, { text: "課題", options: { bold: true } }, { text: "所要", options: { bold: true } }, { text: "募集枠", options: { bold: true } }, { text: "小計（税込）", options: { bold: true } }],
    [{ text: "第1段階", options: { bold: true } }, "聴覚 乙課題", "10〜12分", "71名", "16,011円"],
    ["", "視覚 乙課題", "約10分", "48名", "10,824円"],
    [{ text: "第2段階", options: { bold: true } }, "聴覚1文字", "約14分", "53名", "15,450円"],
    ["", "視覚1文字", "約25分", "53名", "26,818円"],
    ["", "聴覚2文字", "13〜14分", "48名", "13,992円"],
    ["", "視覚2文字", "約26分", "48名", "24,288円"],
    [{ text: "本体合計", options: { bold: true } }, "", "", { text: "321名", options: { bold: true } }, { text: "107,382円", options: { bold: true } }],
    [{ text: "予備費", options: { bold: true } }, "保留になったときの増員に備える", "", "", { text: "28,413円", options: { bold: true } }],
  ];
  s.addTable(rows, {
    x: 0.62, y: 1.8, w: 12.13, colW: [1.8, 4.4, 2.0, 1.7, 2.23],
    fontFace: FONT, fontSize: 12, color: INK, border: { type: "solid", color: LINE, pt: 1 },
    fill: { color: W }, rowH: 0.36, valign: "middle", margin: [2, 8, 2, 8],
  });
  note(s, 0.62, 5.55, 12.13, "総額の目安", "およそ14万円。第2段階は判断フローで形が決まるので、そこで配分を確定する。");
  s.addText("募集はクラウドソーシングで行う。謝礼の時給換算はおよそ720〜780円で全課題をそろえてある。除外を15％見込んで募集枠を上乗せしている。", {
    x: 0.72, y: 6.42, w: 11.9, h: 0.45, fontFace: FONT, fontSize: 12, color: MUTED, margin: 0 });
  foot(s);
}

/* ------------------------------------------------------------ 16 進め方 */
{
  const s = pres.addSlide();
  head(s, "SCHEDULE", "進め方 — 4つの段階");
  const steps = [
    ["第0段階", "刺激を確かめる", "合成した68音を1音ずつ聴いて、すべての音がその音として成立していることを確認する。必要なら字ごとの処方を調整する。"],
    ["第1段階", "乙課題を実施する", "聴覚71名・視覚48名を募集し、7つの速度で独立かどうかを判定する。ここから限界独立速度 X が求まる。"],
    ["第2段階", "frac課題を実施する", "Xに応じて速度と提示の形を決め、68音・78字の認識率曲線を測る。字ごとに約88観測。"],
    ["第3段階", "変換gを作り、検証する", "曲線どうしを認識率で対応づけて g を作る。先行研究の実測と突き合わせ、2つの出力を作る。"],
  ];
  let y = 1.8;
  steps.forEach(([when, what, detail]) => {
    card(s, 0.62, y, 12.13, 1.06);
    s.addText(when, { x: 0.92, y: y + 0.08, w: 1.5, h: 0.9, fontFace: FONT, fontSize: 13, bold: true, color: GOLD, margin: 0, valign: "middle" });
    s.addText(what, { x: 2.5, y: y + 0.1, w: 3.5, h: 0.86, fontFace: FONT, fontSize: 14, bold: true, color: NAVY, margin: 0, valign: "middle" });
    s.addText(detail, { x: 6.1, y: y + 0.1, w: 6.4, h: 0.86, fontFace: FONT, fontSize: 12, color: INK, margin: 0, valign: "middle", lineSpacingMultiple: 1.25 });
    y += 1.16;
  });
  s.addText("倫理審査は承認済み。実験プログラムは6課題すべて本番仕様になっている。", {
    x: 0.72, y: 6.5, w: 11.9, h: 0.35, fontFace: FONT, fontSize: 12, color: MUTED, margin: 0 });
  foot(s);
}

/* ------------------------------------------------------------ 17 まとめ */
{
  const s = pres.addSlide();
  s.background = { color: NAVY };
  s.addText("SUMMARY", { x: 0.62, y: 0.4, w: 8, h: 0.3, fontFace: FONT, fontSize: 11, bold: true, color: GOLD, charSpacing: 3, margin: 0 });
  s.addText("まとめ — したいこと、測ること、決めること", { x: 0.6, y: 0.72, w: 12.15, h: 0.7, fontFace: FONT, fontSize: 27, bold: true, color: W, margin: 0 });
  const items = [
    ["1", "したいこと", "音声で「いち早く理解する」ゲーム性を、聴覚に頼れない人にも視覚で同じだけ届ける。入力は普通の文章、出力は音声と、表記どおりのかな列である。"],
    ["2", "測ること", "第1段階の乙課題で、どの速さまで文字が互いに独立でいられるかを測る。第2段階のfrac課題で、その速度での認識率曲線を68音・78字について測る。"],
    ["3", "決めること", "乙課題から求まる限界独立速度 X が、第2段階の速度と提示の形を決める。どの枝に進んでもiFontは作れる。変わるのは構成の単純さと精度である。"],
    ["4", "作るもの", "早押しクイズ向けのコマンドラインツールと、競技かるたの動画。どちらも同じ曲線と同じ変換gから作る。"],
  ];
  let y = 1.85;
  items.forEach(([n, t, d]) => {
    badge(s, 0.68, y + 0.1, n, GOLD, NAVY, 0.5);
    s.addText(t, { x: 1.38, y: y + 0.02, w: 2.5, h: 0.5, fontFace: FONT, fontSize: 16, bold: true, color: ICE, margin: 0, valign: "middle" });
    s.addText(d, { x: 3.95, y, w: 8.65, h: 1.05, fontFace: FONT, fontSize: 13, color: W, margin: 0, lineSpacingMultiple: 1.35, valign: "top" });
    y += 1.24;
  });
  s.addText("github.com/qurihara/iFont  /  scrapbox.io/qurihara/iFont  /  2026-08-07", {
    x: 0.62, y: 6.85, w: 11, h: 0.4, fontFace: FONT, fontSize: 11, color: SOFT, margin: 0 });
  page += 1;
  s.addText(String(page), { x: 11.9, y: 6.85, w: 0.8, h: 0.4, fontFace: FONT, fontSize: 10, color: SOFT, align: "right", margin: 0 });
}

const out = process.argv[2];
pres.writeFile({ fileName: out }).then(() => console.log("書き出した: " + out));

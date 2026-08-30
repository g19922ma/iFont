/* =========================================================================
 * verify_stripped_js.js — コメントを落とした JavaScript が
 *                         元と同じ意味のままかを確かめる
 * -------------------------------------------------------------------------
 * build_hosting.sh から呼ばれる。単体でも動く:
 *
 *   node experiment/tools/verify_stripped_js.js <元のフォルダ> <配信用フォルダ> \
 *        <音源フォルダ名> <索引ファイル名> <gitのコミット> <転写表の有無:yes|no>
 *
 * -------------------------------------------------------------------------
 * なぜ構文検査だけでは足りないか
 * -------------------------------------------------------------------------
 * `node --check` は「文法として読めるか」しか見ない。**中身が空のファイルでも通る**。
 * コメントを落とす処理が誤って本体まで削っても、文法さえ合っていれば気づけない。
 * そこで、ここでは「実際に読み込んで、出てくる値が同じか」を見る。
 *
 *   1. 設定ファイル2本  … 読み込んでできる設定の中身を、**キーの順序まで含めて**突き合わせる
 *   2. 部品ファイル2本  … 外に出している関数の名前と種類の一覧を突き合わせる
 *   3. 画面に出る文字   … 使用許諾の表記など、消えては困る文字列が残っているか数える
 *
 * 本体の2本（transfer.js / transfer_comfort.js）は画面が無いと動かないので、
 * ここでは 3 の文字列の検査だけを行う。動作の確認はブラウザで実際に通すこと
 * （project/Firebase Hosting移行手順.md の「4. 掲載前の確認」）。
 * ========================================================================= */
"use strict";
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const [SRC, DIST, STIM_DIR, MANIFEST, GIT_COMMIT, WARP] = process.argv.slice(2);
if (!SRC || !DIST) {
  console.error("使い方: node verify_stripped_js.js <元> <配信用> [音源] [索引] [コミット] [転写表]");
  process.exit(2);
}

let failures = 0;
const ok = (m) => console.log("  OK   " + m);
const ng = (m) => { failures++; console.log("  NG   " + m); };

/* ---- 読み込み用の張りぼて環境 -------------------------------------------
 * ブラウザにしか無いものを最低限そろえる。設定ファイルと部品ファイルは
 * これだけあれば読み込める。 */
function makeSandbox() {
  const sb = {
    console, JSON, Math, Date, Promise, Error, Object, Array, String, Number,
    Boolean, RegExp, Map, Set, isNaN, parseInt, parseFloat,
    setTimeout, clearTimeout, encodeURIComponent, decodeURIComponent,
    URLSearchParams, URL, TextEncoder, TextDecoder, AbortController,
    crypto: require("crypto").webcrypto,
    navigator: { userAgent: "node" },
    location: { search: "", href: "", hostname: "" },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
      addEventListener() {}, createElement: () => ({ style: {}, appendChild() {} }),
      getElementById: () => null, body: { appendChild() {} },
    },
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
  };
  sb.window = sb; sb.globalThis = sb; sb.self = sb;
  return vm.createContext(sb);
}

function run(file, sb) {
  vm.runInContext(fs.readFileSync(file, "utf8"), sb, { filename: file });
}

/* ---- 1. 設定ファイル: 出てくる値が一字一句同じか ------------------------
 * 実行環境（vm のコンテキスト）をまたぐと、中身が同じでも prototype が別物になり
 * deepStrictEqual は必ず落ちる。そこで「同じ順序で JSON 文字列にして比べる」。
 * キーの順序も込みで比べているので、並びが変わっただけでも気づける。 */
function loadGlobal(file, name) {
  const sb = makeSandbox();
  run(file, sb);
  return sb[name];
}

// JSON 化すると関数と undefined は消えてしまい、比較の意味が無くなる。
// 設定ファイルは純粋なデータのはずなので、混じっていたら知らせる。
function findNonData(v, p, out) {
  if (v === undefined) out.push(p + " が undefined");
  else if (typeof v === "function") out.push(p + " が関数");
  else if (v && typeof v === "object") {
    if (Array.isArray(v)) v.forEach((x, i) => findNonData(x, `${p}[${i}]`, out));
    else for (const k of Object.keys(v)) findNonData(v[k], `${p}.${k}`, out);
  }
  return out;
}

console.log("1. 設定ファイル: 読み込んでできる値の突き合わせ");
const CONFIGS = [
  ["transfer_config.js", "TRANSFER_CONFIG"],
  ["transfer_comfort_config.js", "TRANSFER_COMFORT_CONFIG"],
  ["transfer_pair_config.js", "TRANSFER_PAIR_CONFIG"],
];
let cfgValues = {};
for (const [file, name] of CONFIGS) {
  try {
    const a = loadGlobal(path.join(SRC, file), name);
    const b = loadGlobal(path.join(DIST, file), name);
    if (a === undefined) { ng(`${file}: 元のファイルが ${name} を作らない`); continue; }
    cfgValues[name] = a;
    const odd = findNonData(a, name, []);
    if (odd.length) console.log(`  注意 ${file}: 純粋なデータでない箇所 → ${odd.slice(0, 3).join(" / ")}`);
    const sa = JSON.stringify(a), sb2 = JSON.stringify(b);
    if (sa === sb2) ok(`${file} … ${name} が完全に一致（${sa.length} 文字ぶん・キーの順序も同じ）`);
    else {
      let i = 0; while (i < sa.length && sa[i] === sb2[i]) i++;
      ng(`${file} … ${i} 文字目から違う\n         元  …${sa.slice(Math.max(0, i - 50), i + 50)}…\n         除去…${sb2.slice(Math.max(0, i - 50), i + 50)}…`);
    }
  } catch (e) { ng(`${file}: 読み込めない → ${e.message}`); }
}

/* ---- 2. 部品ファイル: 外に出している名前の一覧が同じか ------------------ */
console.log("2. 部品ファイル: 外に出している関数の一覧の突き合わせ");
function surface(file) {
  const sb = makeSandbox();
  const before = new Set(Object.keys(sb));
  run(file, sb);
  const added = Object.keys(sb).filter((k) => !before.has(k)).sort();
  const out = {};
  for (const k of added) {
    const v = sb[k];
    out[k] = (v && typeof v === "object")
      ? Object.keys(v).sort().map((m) => `${m}:${typeof v[m]}`)
      : typeof v;
  }
  return JSON.stringify(out);
}
for (const file of ["prod_common.js", "transfer_firestore.js"]) {
  try {
    const a = surface(path.join(SRC, file));
    const b = surface(path.join(DIST, file));
    if (a === b) ok(`${file} … ${a.slice(0, 150)}${a.length > 150 ? "…" : ""}`);
    else ng(`${file}\n         元  ${a}\n         除去 ${b}`);
  } catch (e) { ng(`${file}: 読み込めない → ${e.message}`); }
}

/* ---- 3. 画面に出る文字が消えていないか ----------------------------------
 * とくに **使用許諾の表記は消すと規約違反**になる（COEIROINK の規約で
 * クレジットは必須。project/合成音声_話者候補.md）。
 * コメントの中にも同じ語が出てくるので、行数ではなく**出現回数**で数える。 */
console.log("3. 画面に出る文字列が残っているか");
function count(file, s) {
  const t = fs.readFileSync(file, "utf8");
  let n = 0, i = 0;
  while ((i = t.indexOf(s, i)) !== -1) { n++; i += s.length; }
  return n;
}
// これらは**文字列リテラルの中にしか出てこない**ものを選ぶ。
// コメントにも出てくる語（「完了コード」など）は、除去後に減って当然なので入れない。
const MUST_KEEP = [
  ["transfer.js", "COEIROINK:あみたろ", 1],
  ["transfer_comfort.js", "COEIROINK:あみたろ", 1],
  ["transfer.js", "津田塾大学 栗原研究室", 4],
  ["transfer_comfort.js", "津田塾大学 栗原研究室", 6],
  ["prod_common.js", "津田塾大学 栗原研究室", 1],
];
for (const [file, s, expect] of MUST_KEEP) {
  const a = count(path.join(SRC, file), s);
  const b = count(path.join(DIST, file), s);
  if (a === b) ok(`${file} … 「${s}」が ${b} 回（元と同じ）`);
  else ng(`${file} … 「${s}」が 元 ${a} 回 → 除去後 ${b} 回に変わった`
        + (expect != null ? `（想定 ${expect} 回）` : ""));
}

/* ---- 4. 中身が空になっていないか ---------------------------------------
 * node --check は空ファイルでも通ってしまうので、大きさも見ておく。
 *
 * ただし「何割まで縮んだか」は、**中身を確かめる手立てが無いファイルにだけ**当てる。
 * 設定ファイル(1)と部品ファイル(2)は、値そのもの・関数の一覧そのものを
 * 突き合わせて同じだと確かめてあるので、縮み具合は目安として出すだけにする。
 * とくに transfer_config.js は中身の9割が説明文なので、落とすと1割ほどになる。
 * これは**正しく動いている証拠**であって、異常ではない。
 *
 * 中身を確かめられていないのは本体2本（transfer.js / transfer_comfort.js）だけで、
 * こちらは実測で元の5割強に落ち着く。25%を下回ったら削りすぎを疑う。 */
console.log("4. 極端に縮んでいないか（本体まで削っていないか）");
const STRONGLY_CHECKED = new Set([
  "transfer_config.js", "transfer_comfort_config.js",   // 値を突き合わせ済み
  "transfer_pair_config.js",
  "prod_common.js", "transfer_firestore.js",            // 関数の一覧を突き合わせ済み
]);
const MIN_RATIO_PCT = 25;   // 中身を確かめられないファイル向けの下限
for (const f of fs.readdirSync(DIST).filter((x) => x.endsWith(".js"))) {
  const a = fs.statSync(path.join(SRC, f)).size;
  const b = fs.statSync(path.join(DIST, f)).size;
  const pct = Math.round((b / a) * 100);
  const size = `${a} → ${b} バイト（元の ${pct}%）`;
  if (b < 200) { ng(`${f} … ${b} バイトしかない`); continue; }
  if (STRONGLY_CHECKED.has(f)) ok(`${f} … ${size}／中身は突き合わせ済みなので割合は目安`);
  else if (pct < MIN_RATIO_PCT) ng(`${f} … ${size}。${MIN_RATIO_PCT}% を下回った（削りすぎの疑い）`);
  else ok(`${f} … ${size}`);
}

/* ---- 5. 配信の目印を書き出す -------------------------------------------
 * コメントを落とすと「配信中のファイルを curl して pre_launch を grep する」
 * という掲載前の確認ができなくなる（1行に潰れるうえ、周りの説明も消える）。
 * かわりに、確かめたい値だけをこの JSON に書き出して配信する。 */
const cfg = cfgValues.TRANSFER_CONFIG || {};
const info = {
  built_at: new Date().toISOString(),
  config_version: cfg.config_version || null,
  pre_launch: cfg.pre_launch === true,
  stimuli_dir: STIM_DIR || null,
  manifest_url: MANIFEST || null,
  warp_table: WARP === "yes",
  git_commit: GIT_COMMIT || null,
  comments_stripped: true,
};
fs.writeFileSync(path.join(DIST, "build_info.json"), JSON.stringify(info, null, 2) + "\n");
console.log("5. build_info.json を書き出した");
console.log("     " + JSON.stringify(info));

if (failures) {
  console.error(`\n検査に失敗した項目が ${failures} 件ある。配信してはいけない。`);
  process.exit(1);
}
console.log("\nすべての検査を通過した。");

// 各ゲームの問題データから「本当の最小手数」の表を機械で作り、src/mins.js に書く（手で書かない）。
//   node tools/build_mins.mjs          … 表を作り直して src/mins.js を上書き
//   node tools/build_mins.mjs --check  … 今の src/mins.js が問題データと一致するかだけ確かめる（テストから呼ぶ）
//
// 数え方は各ゲームのクエスト用モード（?quest=N）が親へ送る min と同じ（quest/docs/spec.md §4 の表）。
// ゲーム側の数え方が変わったら気づけるよう、各ゲームの index.html に「数え方の行」がそのまま残っているかも確かめる（GUARD）。
// 一致しなければ止まる＝表を作り直す前に、ゲーム側の変更とこの表の数え方を突き合わせること。
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const ROOT = new URL("../../", import.meta.url);           // puzzle-portal/
const OUT = new URL("../src/mins.js", import.meta.url);

const html = (g) => readFileSync(new URL(`${g}/index.html`, ROOT), "utf8");

/** `var NAME = [ ... ];` の配列リテラル（JSON）を取り出す。文字列の中の括弧は数えない */
function dataArray(src, name) {
  const at = src.indexOf(`var ${name} = [`);
  if (at < 0) throw new Error(`${name} が見つかりません`);
  let i = src.indexOf("[", at), depth = 0, inStr = false;
  const from = i;
  for (; i < src.length; i++) {
    const c = src[i];
    if (inStr) { if (c === "\\") i++; else if (c === '"') inStr = false; continue; }
    if (c === '"') inStr = true;
    else if (c === "[") depth++;
    else if (c === "]" && --depth === 0) return JSON.parse(src.slice(from, i + 1));
  }
  throw new Error(`${name} の終わりが見つかりません`);
}

/** 最初の <script> の純粋ロジック（window.<Name> を公開して閉じるもの）を vm で動かし、その名前空間を返す */
function namespace(src, name) {
  const s = src.indexOf("<script>") + "<script>".length;
  const e = src.indexOf("</script>", s);
  const code = src.slice(s, e);
  if (!code.includes(`window.${name} = ${name}`)) throw new Error(`最初の <script> に window.${name} がありません`);
  const ctx = { window: {} };
  vm.runInNewContext(code, ctx);
  return ctx.window[name];
}

const fromMin = (g) => dataArray(html(g), "LEVELS").map((lv) => lv.min);
const countOnes = (s) => [...s].filter((c) => c === "1").length;

/** ゲームごとの数え方。各ゲームの quest モードの該当行を GUARD に写してある */
const RULES = {
  "car-escape":     { guard: ["var min = LEVELS[levelIndex].min;"], mins: () => fromMin("car-escape") },
  "hakoiri-musume": { guard: ["var min = LEVELS[levelIndex].min;"], mins: () => fromMin("hakoiri-musume") },
  "slide-robots":   { guard: ["var lv = LEVELS[levelIndex], min = lv.min;"], mins: () => fromMin("slide-robots") },
  "nigekomi":       { guard: ["var min = LEVELS[levelIndex].min;"], mins: () => fromMin("nigekomi") },
  "hatatate":       { guard: ["min: LEVELS[Q].min"], mins: () => fromMin("hatatate") },
  // 空きマスの数
  "nanpure": {
    guard: ["var g = Sudoku.parse(PUZZLES[Q].puzzle), c = 0, k;", "for (k = 0; k < CELLS; k++) if (!g[k]) c++;"],
    mins: () => {
      const src = html("nanpure"), S = namespace(src, "Sudoku");
      return dataArray(src, "PUZZLES").map((p) => { const g = S.parse(p.puzzle); let c = 0; for (let k = 0; k < 81; k++) if (!g[k]) c++; return c; });
    },
  },
  // 解の★の数・塗るマスの数
  "hoshi-oki": {
    guard: ["var sol = PUZZLES[Q].solution, c = 0, k;", "if (sol.charAt(k) === '1') c++;"],
    mins: () => dataArray(html("hoshi-oki"), "PUZZLES").map((p) => countOnes(p.solution)),
  },
  "pixel": {
    guard: ["var sol = PUZZLES[Q].solution, c = 0, k;", "if (sol.charAt(k) === '1') c++;"],
    mins: () => dataArray(html("pixel"), "PUZZLES").map((p) => countOnes(p.solution)),
  },
  // 全マス数 − ペアの数
  "michi-tsunagi": {
    guard: ["n = d.n; N = d.N; K = d.pairs.length;", "qmin = N - K;"],
    mins: () => {
      const src = html("michi-tsunagi"), M = namespace(src, "MichiTsunagi");
      return dataArray(src, "PUZZLES").map((p) => { const d = M.parse(p); return d.N - d.pairs.length; });
    },
  },
  // 各マスを正解の見た目にする最少の時計回り回転数の和
  "kurukuru": {
    guard: ["base = d.cells.slice();", "if (Kurukuru.rotate(base[qi], qr) === d.sol[qi]) { qmin += qr; break; }"],
    mins: () => {
      const src = html("kurukuru"), K = namespace(src, "Kurukuru");
      return dataArray(src, "PUZZLES").map((p) => {
        const d = K.parse(p); let m = 0;
        for (let i = 0; i < d.N; i++) for (let r = 0; r < 4; r++) if (K.rotate(d.cells[i], r) === d.sol[i]) { m += r; break; }
        return m;
      });
    },
  },
  // 全マス数 − 部屋の数
  "mado-wake": {
    guard: ["p = MadoWake.parse(PUZZLES[i]);", "qmin = p.N - nroom;"],
    mins: () => {
      const src = html("mado-wake"), W = namespace(src, "MadoWake");
      return dataArray(src, "PUZZLES").map((raw) => { const p = W.parse(raw); return p.N - new Set(p.solution.slice(0, p.N)).size; });
    },
  },
};

export function buildMins() {
  const out = {};
  for (const [g, rule] of Object.entries(RULES)) {
    const src = html(g);
    for (const line of rule.guard) {
      if (!src.includes(line)) throw new Error(`${g}: クエスト用モードの数え方の行が変わっています（${line}）。数え方を突き合わせてから作り直してください`);
    }
    const mins = rule.mins();
    mins.forEach((m, i) => { if (!Number.isInteger(m) || m <= 0) throw new Error(`${g} ${i}: 最小手数が正の整数ではありません（${m}）`); });
    out[g] = mins;
  }
  return out;
}

export function render(mins) {
  const lines = Object.entries(mins).map(([g, a]) => `  ${JSON.stringify(g)}: ${JSON.stringify(a)},`);
  return "// 自動生成（worker/tools/build_mins.mjs）。手で直さない。\n"
    + "// 各ゲームの問題（添字＝?quest=N の N）の本当の最小手数。各ゲームのクエスト用モードが送る min と同じ数え方。\n"
    + `export const MINS = {\n${lines.join("\n")}\n};\n`;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const mins = buildMins();
  const text = render(mins);
  const total = Object.values(mins).reduce((s, a) => s + a.length, 0);
  if (process.argv.includes("--check")) {
    const cur = readFileSync(OUT, "utf8");
    if (cur !== text) { console.error("src/mins.js が問題データと一致しません。node tools/build_mins.mjs で作り直してください"); process.exit(1); }
    console.log(`一致：${Object.keys(mins).length}本・${total}問`);
  } else {
    writeFileSync(OUT, text);
    console.log(`src/mins.js を書きました：${Object.keys(mins).length}本・${total}問`);
    for (const [g, a] of Object.entries(mins)) console.log(`  ${g}: ${a.length}問（${Math.min(...a)}〜${Math.max(...a)}手）`);
  }
}

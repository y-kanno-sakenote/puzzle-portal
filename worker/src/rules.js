// クエストの採点の決まり（quest/index.html の写し）。値と式を変えたら両方を直す。
// 一致はテスト（test/board.test.js「quest/index.html と同じ決まり」）が quest/index.html を読んで確かめる。
import { MINS } from "./mins.js";

export const SYSTEMS = [
  { id: "move", emoji: "🚗", parts: ["歯車族", "せっかちな", "走り屋"], games: ["car-escape", "hakoiri-musume", "slide-robots", "nigekomi"] },
  { id: "fill", emoji: "🧩", parts: ["石板族", "几帳面な", "職人"], games: ["nanpure", "hoshi-oki", "pixel", "hatatate"] },
  { id: "link", emoji: "🔗", parts: ["糸族", "人懐っこい", "案内人"], games: ["michi-tsunagi", "kurukuru", "mado-wake"] },
];
export const QUEST = {
  "car-escape":     { easy: [0, 19], mid: [20, 29], hard: [30, 49] },
  "hakoiri-musume": { easy: [0, 9],  mid: [10, 29], hard: [30, 39] },
  "slide-robots":   { easy: [0, 9],  mid: [10, 29], hard: [30, 39] },
  "nigekomi":       { easy: [0, 9],  mid: [10, 29], hard: [30, 39] },
  "nanpure":        { easy: [0, 9],  mid: [10, 29], hard: [30, 39] },
  "hoshi-oki":      { easy: [0, 9],  mid: [10, 29], hard: [30, 39] },
  "pixel":          { easy: [0, 19], mid: [20, 39], hard: [40, 59] },
  "hatatate":       { easy: [0, 9],  mid: [10, 29], hard: [30, 39] },
  "michi-tsunagi":  { easy: [0, 9],  mid: [10, 29], hard: [30, 39] },
  "kurukuru":       { easy: [0, 9],  mid: [10, 29], hard: [30, 39] },
  "mado-wake":      { easy: [0, 9],  mid: [10, 29], hard: [30, 39] },
};
export const STAGES = [
  { tier: "easy", cap: 100 },
  { tier: "mid", cap: 1000 },
  { tier: "hard", cap: 10000 },
];
export const SLACK = 2, FLOOR = 10;
export const DUEL_RATE = 2;
export const BOSS_TOP = 13, BOSS_MAX = 10, BOSS_MIN = 2;
export const KIRIBAN = [777777, 77777777, 123456, 1234567, 1000000000];
/** 満点：100×1,000×10,000×2×2×10 */
export const SCORE_MAX = 40000000000;
/** ボスの手数の範囲（遊び手は3つ並べるのに最低3手・合わせて40手＝遊び手20手で打ち切り） */
export const BOSS_MOVES_MIN = 3, BOSS_MOVES_MAX = 20;

export { MINS };

/** quest/index.html の left()・points()・bossRate() と同じ式 */
export function left(moves, min) {
  if (!(moves > 0 && min > 0) || moves <= min) return 1;
  return Math.max(0, 1 - (moves - min) / Math.max(min * SLACK, FLOOR));
}
export function points(cap, moves, min) { return Math.round(cap * left(moves, min)); }
export function bossRate(moves) {
  if (!(moves > 0)) return BOSS_MIN;
  return Math.min(BOSS_MAX, Math.max(BOSS_MIN, BOSS_TOP - moves));
}
export function isKiriban(n) { return n % 1000 === 777 || KIRIBAN.indexOf(n) >= 0; }

export function systemOf(game) { return SYSTEMS.findIndex((s) => s.games.includes(game)); }

/**
 * 送られた中身から累計・キャラ名・レアを計算し直す（quest/index.html の solved()・boutEnd()・onward() と同じ順）。
 * stages=[{game,level,moves,min}]（検証済み）・duels=[true/false]・boss={win,moves}|null
 */
export function recompute({ end, stages, duels, boss }) {
  let total = 1, exact = false;
  stages.forEach((s, i) => {
    total *= Math.max(1, points(STAGES[i].cap, s.moves, s.min));
    if (s.moves === s.min) exact = true;
    if (i < duels.length && i < 2) total *= duels[i] ? DUEL_RATE : 1;
  });
  if (boss) total *= boss.win ? bossRate(boss.moves) : 1;
  const sy = stages.map((s) => SYSTEMS[systemOf(s.game)]);
  const emoji = sy.map((x) => x.emoji).join("");
  if (end !== "clear") return { total, emoji, char: "", rare: false };
  return { total, emoji, char: sy[1].parts[1] + sy[0].parts[0] + "の" + sy[2].parts[2], rare: exact || isKiriban(total) };
}

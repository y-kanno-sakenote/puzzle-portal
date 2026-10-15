// npm test（= node --test test/board.test.js。worker/ で。wrangler dev も鍵も要らない）
// 管理鍵はファイルに書かない：TEST_ADMIN_KEY があればそれを、無ければ実行のたびに乱数で作る（ボードを見る・載せるのに鍵は要らない）
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import vm from "node:vm";
import { buildMins, render } from "../tools/build_mins.mjs";
import * as R from "../src/rules.js";
import { createHandler, validateEntry, cleanName } from "../src/handler.js";
import { Board } from "../src/board.js";

const ADMIN_KEY = process.env.TEST_ADMIN_KEY || crypto.randomUUID();
const ORIGIN = "https://y-kanno-sakenote.github.io";

// ---- 最小手数の表と採点の決まりが、ゲームとクエスト画面の今の中身と一致する ----
test("最小手数の表（src/mins.js）は各ゲームの問題データから作り直したものと同じ", () => {
  assert.equal(readFileSync(new URL("../src/mins.js", import.meta.url), "utf8"), render(buildMins()));
  for (const [g, t] of Object.entries(R.QUEST)) {
    assert.ok(R.MINS[g].length > t.hard[1], `${g} の表が難の段の最後まで届く`);
  }
});

// quest/index.html の定数の塊（var SYSTEMS 〜 var $ の手前）と、left/points/bossRate/isKiriban をそのまま動かす
const questSrc = readFileSync(new URL("../../quest/index.html", import.meta.url), "utf8");
const quest = (() => {
  const consts = questSrc.slice(questSrc.indexOf("var SYSTEMS = ["), questSrc.indexOf("var $ = function"));
  // 1行の関数（{ … } が同じ行で閉じる）を先に探し、無ければ行頭の } で閉じる複数行の関数
  const fn = (name) => (new RegExp(`^function ${name}\\([^)]*\\) \\{.*\\}$`, "m").exec(questSrc) || new RegExp(`^function ${name}\\([^)]*\\) \\{\\n[\\s\\S]*?\\n\\}`, "m").exec(questSrc))[0];
  const ctx = {};
  vm.runInNewContext(consts + ["left", "points", "bossRate", "isKiriban"].map(fn).join("\n")
    + "\nthis.Q = {SYSTEMS, QUEST, STAGES, SLACK, FLOOR, DUEL_RATE, BOSS_TOP, BOSS_MAX, BOSS_MIN, KIRIBAN, left, points, bossRate, isKiriban};", ctx);
  return ctx.Q;
})();

test("quest/index.html と同じ決まり（系統・段の範囲・上限・SLACK/FLOOR・早撃ち・ボス・キリ番・式）", () => {
  const plain = (x) => JSON.parse(JSON.stringify(x));
  assert.deepEqual(R.SYSTEMS.map((s) => [s.id, s.emoji, s.parts, s.games]), plain(quest.SYSTEMS.map((s) => [s.id, s.emoji, s.parts, s.games])));
  assert.deepEqual(R.QUEST, plain(quest.QUEST));
  assert.deepEqual(R.STAGES, plain(quest.STAGES.map((s) => ({ tier: s.tier, cap: s.cap }))));
  assert.deepEqual([R.SLACK, R.FLOOR, R.DUEL_RATE, R.BOSS_TOP, R.BOSS_MAX, R.BOSS_MIN], [quest.SLACK, quest.FLOOR, quest.DUEL_RATE, quest.BOSS_TOP, quest.BOSS_MAX, quest.BOSS_MIN]);
  assert.deepEqual(R.KIRIBAN, plain(quest.KIRIBAN));
  for (let min = 1; min <= 150; min += 7) for (let moves = min; moves <= min * 4 + 12; moves++) {
    assert.equal(R.left(moves, min), quest.left(moves, min));
    for (const cap of [100, 1000, 10000]) assert.equal(R.points(cap, moves, min), quest.points(cap, moves, min));
  }
  for (let m = 0; m <= 25; m++) assert.equal(R.bossRate(m), quest.bossRate(m));
  for (const n of [777, 1777, 777777, 123456, 1000000000, 1000, 5]) assert.equal(R.isKiriban(n), quest.isKiriban(n));
  assert.equal(R.SCORE_MAX, 100 * 1000 * 10000 * 2 * 2 * 10);
});

// ---- 正しい記録の例 ----
// car-escape 入門0（最短3）・ナンプレ初級10・くるくる上級30、どれも最短ぴったり → 100×1000×10000、早撃ち 勝ち・負け ×2、ボス5手で勝ち ×8
const S = (game, level, extra = 0) => ({ game, level, min: R.MINS[game][level], moves: R.MINS[game][level] + extra });
function clearRun(over = {}) {
  return {
    name: "かんの", end: "clear",
    stages: [S("car-escape", 0), S("nanpure", 10), S("kurukuru", 30)],
    duels: [true, false], boss: { win: true, moves: 5 },
    total: 100 * 1000 * 10000 * 2 * 8, time: 123456, char: "几帳面な歯車族の案内人", rare: true, ...over,
  };
}
// アウト：1st を最短+5で（100×(1−5/10)=50）、早撃ち勝ち ×2 の後に 2nd でアウト
function outRun(over = {}) {
  return { name: "なかま", end: "out", stages: [S("slide-robots", 3, 5)], duels: [true], boss: null, total: 100, time: 5000, char: "", rare: false, ...over };
}

test("検証：正しい記録が通る（完走・アウト・ギブアップ）", () => {
  const a = validateEntry(clearRun());
  assert.equal(a.ok, true, a.message);
  assert.equal(a.entry.score, 16000000000);
  assert.equal(a.entry.emoji, "🚗🧩🔗");
  assert.equal(validateEntry(outRun()).ok, true);
  assert.equal(validateEntry(outRun({ end: "giveup" })).ok, true);
  // 2ステージでギブアップ（早撃ち2つ）
  const two = { ...outRun(), end: "giveup", stages: [S("pixel", 5), S("mado-wake", 20, 3)], duels: [false, true] };
  two.total = 100 * Math.round(1000 * (1 - 3 / Math.max(R.MINS["mado-wake"][20] * 2, 10))) * 2;
  assert.equal(validateEntry(two).ok, true, validateEntry(two).message);
  // ボスに負けた完走・最短ぴったりなしのキリ番でないもの
  const lose = clearRun({ stages: [S("car-escape", 0, 1), S("nanpure", 10, 1), S("kurukuru", 30, 1)], boss: { win: false, moves: 7 }, rare: false });
  lose.total = R.recompute({ end: "clear", stages: lose.stages, duels: lose.duels, boss: lose.boss }).total;
  assert.equal(quest.points(100, 4, 3) * quest.points(1000, lose.stages[1].moves, lose.stages[1].min) * quest.points(10000, lose.stages[2].moves, lose.stages[2].min) * 2, lose.total);
  assert.equal(validateEntry(lose).ok, true, validateEntry(lose).message);
});

test("検証：弾くもの", () => {
  const no = (b, re) => { const v = validateEntry(b); assert.equal(v.ok, false, JSON.stringify(b).slice(0, 80)); if (re) assert.match(v.message, re); };
  // 最短より少ない手数
  no(clearRun({ stages: [S("car-escape", 0, -1), S("nanpure", 10), S("kurukuru", 30)] }), /少なく/);
  // 最短の値そのものを小さく偽る
  no(clearRun({ stages: [{ ...S("car-escape", 0), min: 2, moves: 2 }, S("nanpure", 10), S("kurukuru", 30)] }), /最短手数/);
  // 段の範囲外（1st に中級の問題・存在しない番号）
  no(clearRun({ stages: [S("car-escape", 25), S("nanpure", 10), S("kurukuru", 30)] }), /段/);
  no(clearRun({ stages: [S("car-escape", 0), S("nanpure", 10), { ...S("kurukuru", 39), level: 40 }] }), /段/);
  no(clearRun({ stages: [S("car-escape", 0), S("nanpure", 10), { ...S("kurukuru", 30), level: 30.5 }] }));
  // 二重のゲーム
  no(clearRun({ stages: [S("nanpure", 0), S("nanpure", 10), S("kurukuru", 30)] }), /二度/);
  // 無いゲーム・はやつかみ
  no(clearRun({ stages: [{ game: "hayatsukami", level: 0, moves: 3, min: 3 }, S("nanpure", 10), S("kurukuru", 30)] }), /ゲーム/);
  // 累計の不一致・上限超え
  no(clearRun({ total: 16000000001 }), /累計/);
  no(clearRun({ total: "16000000000" }), /累計/);
  no(outRun({ total: 50 }), /累計/);
  // 持ち点が尽きた手数（最短3・+10手で0）
  no(outRun({ stages: [S("slide-robots", 3, Math.max(R.MINS["slide-robots"][3] * 2, 10))], total: 1 }), /尽き/);
  // 名前
  no(clearRun({ name: "あ".repeat(13) }), /なまえ/);
  no(clearRun({ name: "   " }), /なまえ/);
  no(clearRun({ name: "かん\nの" }), /なまえ/);
  no(clearRun({ name: "か​の" }), /なまえ/);
  no(clearRun({ name: 12 }), /なまえ/);
  // 数の合わない形
  no(clearRun({ duels: [true] }), /早撃ち/);
  no(clearRun({ duels: [true, 1] }), /早撃ち/);
  no(clearRun({ boss: null }), /ボス/);
  no(clearRun({ boss: { win: true, moves: 2 } }), /ボス/);
  no(outRun({ boss: { win: true, moves: 5 } }), /ボス/);
  no(outRun({ stages: [S("slide-robots", 3), S("nanpure", 10), S("kurukuru", 30)], duels: [true, true] }), /ステージ/);
  no(clearRun({ end: "win" }), /終わり方/);
  no(clearRun({ time: -1 }), /タイム/);
  no(clearRun({ char: "せっかちな歯車族の走り屋" }), /キャラ/);
  no(clearRun({ rare: false }), /レア/);
  no(null); no([]); no("x");
});

test("見える文字が1つも無い名前は弾く", () => {
  for (const cp of [0x3164, 0x2800, 0x115f, 0x1160, 0xffa0, 0x3000, 0x00a0, 0x2003, 0x200b, 0x2060, 0xfe0f, 0x034f, 0x0301]) {
    const ch = String.fromCodePoint(cp);
    assert.equal(cleanName(ch), null, cp.toString(16));
    assert.equal(cleanName(ch.repeat(3)), null, cp.toString(16) + "×3");
    assert.equal(validateEntry(clearRun({ name: ch + ch })).ok, false, cp.toString(16));
  }
  assert.equal(cleanName("\u3164あ\u2800"), "\u3164あ\u2800", "見える文字が残れば通す");
  assert.equal(cleanName("é"), "é");
});

test("タイムは7日まで通す（放置したタブ）", () => {
  const day = 24 * 3600e3;
  assert.equal(validateEntry(clearRun({ time: 2 * day })).ok, true);
  assert.equal(validateEntry(clearRun({ time: 7 * day })).ok, true);
  assert.match(validateEntry(clearRun({ time: 7 * day + 1 })).message, /タイム/);
});

test("名前は前後の空白を削る・絵文字も1文字", () => {
  assert.equal(cleanName("  かんの　"), "かんの");
  assert.equal(cleanName("🍶".repeat(12)), "🍶".repeat(12));
  assert.equal(cleanName("🍶".repeat(13)), null);
});

// ---- 中継の流れ（DO の代わりに本物の Board を node:sqlite で動かす）----
function fakeCtx() {
  const db = new DatabaseSync(":memory:");
  return { storage: { sql: { exec: (q, ...b) => { const rows = db.prepare(q).all(...b); return { toArray: () => rows }; } } } };
}
function boardNS() {
  const b = new Board(fakeCtx());
  const stub = { add: async (...a) => b.add(...a), list: async (...a) => b.list(...a), remove: async (...a) => b.remove(...a), failKey: async (...a) => b.failKey(...a), keyGate: async (...a) => b.keyGate(...a) };
  return { idFromName: () => "board", get: () => stub };
}
const env = (extra = {}) => ({ BOARD: boardNS(), ADMIN_KEY, ALLOWED_ORIGINS: `${ORIGIN},http://localhost:8733`, RATE_PER_MIN: "3", ...extra });
const req = (method, path, { body, key, admin, origin = ORIGIN, ip = "203.0.113.1" } = {}) => {
  const h = { "CF-Connecting-IP": ip, "content-type": "application/json" };
  if (origin) h.Origin = origin;
  if (key) h["X-Board-Key"] = encodeURIComponent(key);   // 合言葉のころの画面が送っていたヘッダ（今は見ない）
  if (admin) h["X-Admin-Key"] = encodeURIComponent(admin);
  return new Request("https://w.example" + path, { method, headers: h, body: body === undefined ? undefined : JSON.stringify(body) });
};

test("合言葉なしで見る・載せる（古い画面の合言葉は無視）・オリジン", async () => {
  let t = 1e12;
  const handle = createHandler({ now: () => (t += 61e3) });
  const e = env();
  const ok = await handle(req("GET", "/board"), e);
  assert.equal(ok.status, 200, "合言葉なしで見られる");
  assert.equal(ok.headers.get("access-control-allow-origin"), ORIGIN);
  assert.equal((await handle(req("POST", "/entries", { body: clearRun() }), e)).status, 200, "合言葉なしで載せられる");
  assert.equal((await handle(req("GET", "/board", { key: "むかしの合言葉" }), e)).status, 200, "古い画面の X-Board-Key は無視");
  assert.equal((await handle(req("POST", "/entries", { body: outRun(), key: "x" }), e)).status, 200);
  assert.equal((await handle(req("GET", "/board"), env({ BOARD_KEY: "のこっている secret" }))).status, 200, "BOARD_KEY が残っていても見ない");
  assert.equal((await handle(req("GET", "/board", { origin: null }), e)).status, 200, "curl（Origin なし）からも見られる");
  assert.equal((await handle(req("GET", "/board", { origin: "https://evil.example" }), e)).status, 403);
  assert.equal((await handle(req("POST", "/entries", { body: outRun(), origin: "https://evil.example" }), e)).status, 403);
  const pre = await handle(req("OPTIONS", "/entries"), e);
  assert.equal(pre.status, 204);
  assert.match(pre.headers.get("access-control-allow-headers"), /content-type/);
  assert.match(pre.headers.get("access-control-allow-headers"), /x-board-key/, "開いたままの古い画面も弾かない");
  assert.equal((await (await handle(req("GET", "/board"), e)).json()).entries.length, 2);
});

test("載せる・順位・並び順・弾いた理由", async () => {
  let t = 1e12;
  const handle = createHandler({ now: () => (t += 61e3) });   // 1件ごとに1分あける＝連投の制限に当たらない
  const e = env();
  const post = async (b) => { const r = await handle(req("POST", "/entries", { body: b }), e); return { status: r.status, body: await r.json() }; };
  assert.deepEqual((await post(outRun())).body.rank, 1);
  assert.equal((await post(clearRun())).body.rank, 1);
  assert.equal((await post(outRun({ name: "はやい", time: 4000 }))).body.rank, 2, "同点はタイムの速い方が上");
  const bad = await post(clearRun({ total: 1 }));
  assert.equal(bad.status, 400);
  assert.match(bad.body.message, /累計/);
  const r = await handle(req("GET", "/board"), e);
  const list = (await r.json()).entries;
  assert.deepEqual(list.map((x) => [x.name, x.score]), [["かんの", 16000000000], ["はやい", 100], ["なかま", 100]]);
  assert.equal(list[0].char, "几帳面な歯車族の案内人");
  assert.equal(list[0].ip_k, undefined);
  assert.equal(list[0].detail, undefined);
});

test("上位100件で切る", async () => {
  let t = 1e12;
  const handle = createHandler({ now: () => (t += 61e3) });
  const e = env();
  // 1st を最短+k手（k=0..9）・タイム違いで110件。点は 100,95,...,55
  for (let i = 0; i < 110; i++) {
    const k = i % 10, b = outRun({ name: "n" + i, stages: [S("slide-robots", 3, k)], time: 1000 + i });
    b.total = R.points(100, b.stages[0].moves, b.stages[0].min) * 2;
    const res = await handle(req("POST", "/entries", { body: b, ip: "198.51.100." + (i % 200) }), e);
    assert.equal(res.status, 200, (await res.clone().json()).message);
  }
  const list = (await (await handle(req("GET", "/board"), e)).json()).entries;
  assert.equal(list.length, 100);
  for (let i = 1; i < list.length; i++) {
    assert.ok(list[i - 1].score > list[i].score || (list[i - 1].score === list[i].score && list[i - 1].time <= list[i].time));
  }
  // 圏外の点を送ると rank 0（載らない）
  const low = outRun({ stages: [S("slide-robots", 3, 9)], time: 99999 });
  low.total = R.points(100, low.stages[0].moves, low.stages[0].min) * 2;
  const r = await (await handle(req("POST", "/entries", { body: low, ip: "192.0.2.9" }), e)).json();
  assert.equal(r.rank, 0);
  assert.equal((await (await handle(req("GET", "/board"), e)).json()).entries.length, 100);
});

test("連投の制限（同じ IP から1分に3件まで）", async () => {
  let t = 1e12;
  const handle = createHandler({ now: () => (t += 1000) });
  const e = env();
  for (let i = 0; i < 3; i++) assert.equal((await handle(req("POST", "/entries", { body: outRun() }), e)).status, 200);
  const r = await handle(req("POST", "/entries", { body: outRun() }), e);
  assert.equal(r.status, 429);
  assert.equal((await handle(req("POST", "/entries", { body: outRun(), ip: "203.0.113.2" }), e)).status, 200, "別の IP は通る");
  t += 61e3;
  assert.equal((await handle(req("POST", "/entries", { body: outRun() }), e)).status, 200, "1分たてば通る");
});

test("オーナーが1件消す（ADMIN_KEY のときだけ）", async () => {
  let t = 1e12;
  const handle = createHandler({ now: () => (t += 61e3) });
  const e = env();
  const { id } = await (await handle(req("POST", "/entries", { body: outRun() }), e)).json();
  assert.equal((await handle(req("DELETE", "/entries/" + id), e)).status, 403, "管理鍵が無ければ消せない");
  assert.equal((await handle(req("DELETE", "/entries/" + id, { key: "むかしの合言葉" }), e)).status, 403, "合言葉では消せない");
  assert.equal((await handle(req("DELETE", "/entries/" + id), env({ ADMIN_KEY: "" }))).status, 403, "管理鍵が未設定なら誰も消せない");
  assert.equal((await handle(req("DELETE", "/entries/" + id, { admin: "ちがう" }), e)).status, 403);
  assert.equal((await handle(req("DELETE", "/entries/" + id, { admin: ADMIN_KEY, origin: null }), e)).status, 200, "curl（Origin なし）から消せる");
  assert.equal((await handle(req("DELETE", "/entries/" + id, { admin: ADMIN_KEY, origin: null }), e)).status, 404);
  assert.equal((await (await handle(req("GET", "/board"), e)).json()).entries.length, 0);
});

test("管理鍵違いの総当たり：1分に10回を超えたらその IP は1分間、正しい管理鍵でも 429（当たり外れが見分けられない）。見る・載せるは止めない", async () => {
  let t = 1e12;
  const handle = createHandler({ now: () => (t += 100) });
  const e = env();
  const body = async (r) => [r.status, await r.text(), r.headers.get("retry-after")];
  const del = (admin, ip) => req("DELETE", "/entries/abc", { admin, origin: null, ip });
  for (let i = 0; i < 10; i++) assert.equal((await handle(del("a" + i), e)).status, 403, `${i + 1}回目`);
  assert.equal((await handle(del(ADMIN_KEY), e)).status, 404, "制限の前は正しい管理鍵が通る（その id は無い）");
  const first = await body(await handle(del("a10"), e));
  assert.equal(first[0], 429, "11回目の外れで制限");
  assert.deepEqual(await body(await handle(del(ADMIN_KEY), e)), first, "制限中は正しい管理鍵でも同じ 429");
  assert.deepEqual(await body(await handle(del("y"), e)), first);
  assert.deepEqual(await body(await handle(del(null), e)), first);
  // 同じ IP でも見る・載せるは止まらない
  assert.equal((await handle(req("GET", "/board"), e)).status, 200);
  assert.equal((await handle(req("POST", "/entries", { body: outRun() }), e)).status, 200);
  assert.equal((await handle(del(ADMIN_KEY, "203.0.113.9"), e)).status, 404, "別の IP は影響なし");
  // 1分たてば戻る
  t += 61e3;
  assert.equal((await handle(del(ADMIN_KEY), e)).status, 404);
  assert.equal((await handle(del("z"), e)).status, 403, "外れは 403 から数え直し");
});

test("見る・載せるは鍵違いに数えない（何度呼んでも削除の制限に入らない）", async () => {
  let t = 1e12;
  const handle = createHandler({ now: () => (t += 100) });
  const e = env();
  for (let i = 0; i < 30; i++) assert.equal((await handle(req("GET", "/board", { key: "x" + i }), e)).status, 200);
  assert.equal((await handle(req("DELETE", "/entries/abc", { admin: ADMIN_KEY, origin: null }), e)).status, 404);
});

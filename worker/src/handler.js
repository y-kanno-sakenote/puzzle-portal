// みんなの記録（誰でも見られて載せられるボード）の中身。Node から単体テストできる形（DO の外枠は index.js）。
// 流れ: オリジン → GET /board | POST /entries（検証 → 帳場で連投制限と記録） | DELETE /entries/:id（X-Admin-Key・鍵違いの制限つき）
// 軽いずる対策（quest/docs/spec.md §12）：置き場所の側で、問題の範囲・本当の最小手数・二重のゲーム・累計を計算し直して照らす
import { SYSTEMS, QUEST, STAGES, MINS, SCORE_MAX, BOSS_MOVES_MIN, BOSS_MOVES_MAX, left, recompute, systemOf } from "./rules.js";

const JSON_TYPE = "application/json; charset=utf-8";
const BODY_MAX = 4096;
export const NAME_MAX = 12;
export const BOARD_MAX = 100;
const TIME_MAX = 7 * 24 * 3600e3;   // タイムは7日まで（タブを開いたまま放置しても弾かない。タイムは表示だけで点に使わない）
const ENDS = ["clear", "out", "giveup"];

const isInt = (v) => Number.isInteger(v);
const bad = (message) => ({ ok: false, message });

/** 名前：前後の空白を削り、1〜12文字（絵文字も1文字）。制御文字・改行・書式文字（ゼロ幅など）は弾く */
export function cleanName(v) {
  if (typeof v !== "string") return null;
  const t = v.normalize("NFC").trim();
  if (/[\p{Cc}\p{Cf}\u2028\u2029]/u.test(t)) return null;
  const n = [...t].length;
  if (n < 1 || n > NAME_MAX) return null;
  // 見える文字が1つも無い名前は弾く：空白類・既定で無視される文字（ゼロ幅・ハングルのフィラー U+3164 など）・結合記号・点字の空白 U+2800 を除いて1文字以上
  return t.replace(/[\p{White_Space}\p{Default_Ignorable_Code_Point}\p{M}\u2800]/gu, "").length ? t : null;
}

/** 送られた1件を検証し、載せる形にする。{ok:true, entry} | {ok:false, message} */
export function validateEntry(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return bad("送られた内容が読めません");
  const name = cleanName(body.name);
  if (name === null) return bad(`なまえは1〜${NAME_MAX}文字（改行などは使えません）`);
  const { end, stages, duels, boss, total, time } = body;
  if (!ENDS.includes(end)) return bad("終わり方が正しくありません");
  if (!Array.isArray(stages) || !Array.isArray(duels)) return bad("送られた内容が読めません");
  // 完走は3ステージ＋早撃ち2つ＋ボス。アウト・ギブアップは1〜2ステージで、クリアした数だけ早撃ちを済ませている
  const n = stages.length;
  if (end === "clear" ? n !== 3 : n < 1 || n > 2) return bad("ステージの数が合いません");
  if (duels.length !== Math.min(n, 2) || !duels.every((d) => typeof d === "boolean")) return bad("早撃ちの数が合いません");
  let bossOk = null;
  if (end === "clear") {
    if (!boss || typeof boss !== "object" || typeof boss.win !== "boolean" || !isInt(boss.moves)) return bad("ボスの結果が読めません");
    if (boss.win && (boss.moves < BOSS_MOVES_MIN || boss.moves > BOSS_MOVES_MAX)) return bad("ボスの手数があり得ません");
    if (!boss.win && (boss.moves < 0 || boss.moves > BOSS_MOVES_MAX)) return bad("ボスの手数があり得ません");
    bossOk = { win: boss.win, moves: boss.moves };
  } else if (boss != null) return bad("ボスの結果が合いません");

  const seen = new Set(), clean = [];
  for (let i = 0; i < n; i++) {
    const s = stages[i];
    if (!s || typeof s !== "object") return bad("ステージの中身が読めません");
    const { game, level, moves, min } = s;
    if (typeof game !== "string" || systemOf(game) < 0 || !QUEST[game]) return bad(`${i + 1}つめのゲームがありません`);
    if (seen.has(game)) return bad("同じゲームが二度出ています");
    seen.add(game);
    const r = QUEST[game][STAGES[i].tier];
    if (!isInt(level) || level < r[0] || level > r[1]) return bad(`${i + 1}つめの問題がその段にありません`);
    if (!isInt(min) || min !== MINS[game][level]) return bad(`${i + 1}つめの最短手数が問題と合いません`);
    if (!isInt(moves) || moves < min) return bad(`${i + 1}つめの手数が最短より少なくなっています`);
    if (left(moves, min) <= 0) return bad(`${i + 1}つめは持ち点が尽きています`);
    clean.push({ game, level, moves, min });
  }
  if (!isInt(time) || time < 0 || time > TIME_MAX) return bad("タイムが正しくありません");
  const re = recompute({ end, stages: clean, duels, boss: bossOk });
  if (!isInt(total) || total !== re.total || total < 1 || total > SCORE_MAX) return bad("累計が計算し直した点と合いません");
  if (body.char !== undefined && body.char !== re.char) return bad("キャラ名が合いません");
  if (body.rare !== undefined && body.rare !== re.rare) return bad("レアの判定が合いません");
  return {
    ok: true,
    entry: { name, score: re.total, stages: n, end, time, emoji: re.emoji, char: re.char, rare: re.rare,
             detail: { stages: clean, duels, boss: bossOk } },
  };
}

/** IP を数える単位に（IPv6 は /64 にまとめる）→ SHA-256 の先頭16桁（帳場に生の IP を残さない）。brew-rap-battle と同じ */
export async function ipKey(ip) {
  let k = ip || "unknown";
  if (k.includes(":")) {
    const [head, tail = ""] = k.toLowerCase().split("::");
    const a = head ? head.split(":") : [], b = k.includes("::") && tail ? tail.split(":") : [];
    const full = k.includes("::") ? [...a, ...Array(Math.max(0, 8 - a.length - b.length)).fill("0"), ...b] : a;
    k = full.slice(0, 4).join(":") + "::/64";
  }
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(k));
  return [...new Uint8Array(h)].slice(0, 8).map((x) => x.toString(16).padStart(2, "0")).join("");
}

/** 管理鍵の照合（ハッシュどうしを全桁比べる＝一致した桁数で時間が変わらない）。鍵が設定されていなければ常に不一致 */
// ヘッダは ASCII しか運べないので、鍵は encodeURIComponent した形でも受ける（ここで戻してから比べる）
async function sameKey(header, secret) {
  if (!secret || typeof header !== "string" || !header) return false;
  let given = header;
  try { given = decodeURIComponent(header); } catch { /* 符号化されていない鍵はそのまま */ }
  const d = async (s) => new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
  const [a, b] = await Promise.all([d(given), d(secret)]);
  let x = 0;
  for (let i = 0; i < a.length; i++) x |= a[i] ^ b[i];
  return x === 0;
}

const num = (v, d) => { const n = Number(v); return v !== "" && v != null && Number.isFinite(n) ? n : d; };

/** 画面に返す形（IP・細目は出さない。id はオーナーが消すときに使う） */
export const publicEntry = (e) => ({ id: e.id, name: e.name, score: e.score, stages: e.stages, end: e.end, time: e.time, emoji: e.emoji, char: e.char, rare: e.rare, at: e.at });

export function createHandler(deps = {}) {
  const now = deps.now || Date.now;
  return async function handle(req, env) {
    const origin = req.headers.get("Origin");
    const allowed = (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
    // ブラウザからは許したページだけ。Origin の無い呼び出し（curl など）も通す（削除は管理鍵で判断する）
    const okOrigin = origin === null || allowed.includes(origin);
    const cors = origin && okOrigin ? { "access-control-allow-origin": origin, vary: "Origin" } : { vary: "Origin" };
    const json = (status, body, extra = {}) =>
      new Response(JSON.stringify(body), { status, headers: { "content-type": JSON_TYPE, "cache-control": "no-store", ...cors, ...extra } });

    if (!okOrigin) return json(403, { error: "origin_not_allowed", message: "このページからは使えません" });
    if (req.method === "OPTIONS") {
      // x-board-key は合言葉のころの画面（開いたままのタブ）が送ってくるので許すだけ。中身は見ない
      return new Response(null, { status: 204, headers: { ...cors, "access-control-allow-methods": "GET, POST, OPTIONS", "access-control-allow-headers": "content-type, x-board-key", "access-control-max-age": "86400" } });
    }
    const url = new URL(req.url);
    const path = url.pathname.replace(/\/+$/, "");
    if (!env.BOARD) return json(500, { error: "no_board", message: "いまは使えません" });
    const board = env.BOARD.get(env.BOARD.idFromName("board"));
    const ip = await ipKey(req.headers.get("CF-Connecting-IP") || "");

    // オーナーの削除（X-Admin-Key）。管理鍵の総当たり止め：鍵違いを IP ごとに数え、1分に BAD_KEY_PER_MIN 回を超えたら、
    // その IP は1分間、削除の要求（正しい鍵も含む）をすべて 429 にする。制限中は鍵を見ずに同じ応答＝当たり外れが応答から見分けられない
    const del = /^\/entries\/([A-Za-z0-9-]{1,64})$/.exec(path);
    if (del && req.method === "DELETE") {
      const blockedRes = () => json(429, { error: "rate_key", message: "鍵の間違いが続いています。少し待ってください" }, { "retry-after": "60" });
      try { if ((await board.keyGate(ip, { now: now() })).blocked) return blockedRes(); } catch { /* 帳場が読めなければ鍵の照合へ進む */ }
      if (!(await sameKey(req.headers.get("X-Admin-Key"), env.ADMIN_KEY))) {
        let r = { ok: true };
        try { r = await board.failKey(ip, { now: now(), limit: num(env.BAD_KEY_PER_MIN, 10) }); } catch { /* 数えられなくても 403 は返す */ }
        return r.ok ? json(403, { error: "forbidden", message: "消せません" }) : blockedRes();
      }
      const removed = await board.remove(del[1]);
      return removed ? json(200, { ok: true }) : json(404, { error: "not_found", message: "その記録はありません" });
    }

    if (path === "/board" && req.method === "GET") {
      const list = await board.list(BOARD_MAX);
      return json(200, { entries: list.map(publicEntry) });
    }
    if (path === "/entries" && req.method === "POST") {
      const raw = await req.text();
      if (raw.length > BODY_MAX) return json(400, { error: "bad_request", message: "送られた内容が長すぎます" });
      let body;
      try { body = JSON.parse(raw); } catch { return json(400, { error: "bad_request", message: "送られた内容が読めません" }); }
      const v = validateEntry(body);
      if (!v.ok) return json(400, { error: "rejected", message: v.message });
      let r;
      try {
        r = await board.add(v.entry, ip, { now: now(), perMin: num(env.RATE_PER_MIN, 3), max: BOARD_MAX });
      } catch {
        return json(500, { error: "no_board", message: "いまは使えません" });
      }
      if (!r.ok) return json(429, { error: "rate", message: "続けて送りすぎです。少し待ってください" }, { "retry-after": "60" });
      return json(200, { ok: true, id: r.id, rank: r.rank });
    }
    return json(404, { error: "not_found", message: "ありません" });
  };
}

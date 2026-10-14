// ボードの帳場（Durable Object 1個の中身。SQLite バックエンド）。すべて同期処理＝1個の DO の中で1件ずつ順に処理される。
// Node から単体テストできるよう cloudflare:workers に依存しない（DO の外枠は index.js の BoardDO）。
//   add(entry, ipK, {now, perMin, max}) → {ok:true, id, rank}（rank は上位 max 件に残れば順位、押し出されたら0） | {ok:false, error:'rate'}
//   list(limit) → 点の高い順（同点はタイムの速い順・その次は先に載った順）
//   remove(id) → 消せたら true
//   keyGate(ipK, {now}) → {blocked}：その IP が鍵違いの制限中か（鍵を照らす前に見る）
//   failKey(ipK, {now, limit}) → 鍵違いを1回数える。直近1分にその IP から limit 回を超えたら、そこから1分間の制限をかけて {ok:false}
const MINUTE = 60e3;
const ORDER = "score DESC, time ASC, at ASC, id ASC";

export class Board {
  constructor(ctx) {
    this.sql = ctx.storage.sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS entries (id TEXT PRIMARY KEY, score INTEGER NOT NULL, time INTEGER NOT NULL, at INTEGER NOT NULL, data TEXT NOT NULL)");
    this.sql.exec("CREATE TABLE IF NOT EXISTS hits (ip_k TEXT NOT NULL, at INTEGER NOT NULL)");
    this.sql.exec("CREATE TABLE IF NOT EXISTS fails (ip_k TEXT NOT NULL, at INTEGER NOT NULL)");
    this.sql.exec("CREATE TABLE IF NOT EXISTS blocks (ip_k TEXT PRIMARY KEY, until INTEGER NOT NULL)");
  }

  add(entry, ipK, { now, perMin, max }) {
    // 連投の制限：同じ IP（の要約）から直近1分に perMin 件まで
    this.sql.exec("DELETE FROM hits WHERE at < ?", now - MINUTE);
    const n = Number(this.sql.exec("SELECT COUNT(*) AS n FROM hits WHERE ip_k = ?", ipK).toArray()[0].n);
    if (n >= perMin) return { ok: false, error: "rate" };
    this.sql.exec("INSERT INTO hits (ip_k, at) VALUES (?, ?)", ipK, now);

    const id = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
    const row = { ...entry, id, at: now };
    this.sql.exec("INSERT INTO entries (id, score, time, at, data) VALUES (?, ?, ?, ?, ?)", id, row.score, row.time, now, JSON.stringify(row));
    // 上位 max 件より下は消す
    this.sql.exec(`DELETE FROM entries WHERE id NOT IN (SELECT id FROM entries ORDER BY ${ORDER} LIMIT ?)`, max);
    const ids = this.sql.exec(`SELECT id FROM entries ORDER BY ${ORDER}`).toArray().map((r) => r.id);
    return { ok: true, id, rank: ids.indexOf(id) + 1 };
  }

  list(limit) {
    return this.sql.exec(`SELECT data FROM entries ORDER BY ${ORDER} LIMIT ?`, limit).toArray().map((r) => JSON.parse(r.data));
  }

  keyGate(ipK, { now }) {
    this.sql.exec("DELETE FROM blocks WHERE until <= ?", now);
    return { blocked: this.sql.exec("SELECT 1 FROM blocks WHERE ip_k = ?", ipK).toArray().length > 0 };
  }

  failKey(ipK, { now, limit }) {
    this.sql.exec("DELETE FROM fails WHERE at < ?", now - MINUTE);
    this.sql.exec("INSERT INTO fails (ip_k, at) VALUES (?, ?)", ipK, now);
    const n = Number(this.sql.exec("SELECT COUNT(*) AS n FROM fails WHERE ip_k = ?", ipK).toArray()[0].n);
    if (n <= limit) return { ok: true };
    this.sql.exec("INSERT INTO blocks (ip_k, until) VALUES (?, ?) ON CONFLICT(ip_k) DO UPDATE SET until = excluded.until", ipK, now + MINUTE);
    this.sql.exec("DELETE FROM fails WHERE ip_k = ?", ipK);   // 制限が明けたら数え直し
    return { ok: false };
  }

  remove(id) {
    const had = this.sql.exec("SELECT id FROM entries WHERE id = ?", id).toArray().length > 0;
    if (had) this.sql.exec("DELETE FROM entries WHERE id = ?", id);
    return had;
  }
}

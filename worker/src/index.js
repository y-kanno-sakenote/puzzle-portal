// Cloudflare Workers の入口（npx wrangler deploy でこれをバンドルする）。中身は handler.js（Node から単体テストできる形）。
import { DurableObject } from "cloudflare:workers";
import { createHandler } from "./handler.js";
import { Board } from "./board.js";

/** ボード（SQLite バックエンドの Durable Object を1個だけ使う＝書き込みを1件ずつ処理）。中身は board.js */
export class BoardDO extends DurableObject {
  constructor(ctx, env) { super(ctx, env); this.b = new Board(ctx); }
  add(entry, ipK, opts) { return this.b.add(entry, ipK, opts); }
  list(limit) { return this.b.list(limit); }
  remove(id) { return this.b.remove(id); }
  keyGate(ipK, opts) { return this.b.keyGate(ipK, opts); }
  failKey(ipK, opts) { return this.b.failKey(ipK, opts); }
}

const handle = createHandler();

export default {
  fetch: (req, env) => handle(req, env),
};

# puzzle-quest-board（クエストの「みんなの記録」）

誰でも見られて載せられるボード（2026-10-15 に合言葉を外した）。仕様は `../quest/docs/spec.md` §12。Cloudflare Worker ＋ Durable Object 1個（SQLite バックエンド＝無料プランで使える）に上位100件を持つ。

## 中身
- `src/handler.js` 入口の流れ（オリジン → 検証 → 帳場。削除だけ管理鍵）と記録の検証 `validateEntry`
- `src/rules.js` 採点の決まり（`quest/index.html` の写し。テストが突き合わせる）
- `src/mins.js` 各ゲームの問題の本当の最小手数（**自動生成**。`npm run mins` で作り直す・手で直さない）
- `src/board.js` ボードの帳場（上位100件・連投の制限・削除）／`src/index.js` Durable Object の外枠
- `tools/build_mins.mjs` 最小手数の表を各ゲームの `index.html` の問題データから作る（`--check` で一致だけ確かめる）

## API（見る・載せるは鍵なし。ブラウザからは `ALLOWED_ORIGINS` のページだけ）
| | ヘッダ | 返すもの |
|---|---|---|
| `GET /board` | なし | `{entries:[{id,name,score,stages,end,time,emoji,char,rare,at}]}`（上位100件・点の高い順・同点はタイムの速い順） |
| `POST /entries` | なし | `{ok:true,id,rank}`（rank=0 は100位の外）／400 `{message}`（弾いた理由）／429（連投） |
| `DELETE /entries/:id` | `X-Admin-Key` | `{ok:true}`／404／403（鍵違い）／429（鍵違いが続いた） |

合言葉のころの画面が送ってくる `X-Board-Key` は受け取るが見ない。

## 手元で試す
```sh
cd worker
npm install
npm test                      # 鍵は要らない（テストは乱数の仮の管理鍵）
npx wrangler dev --var ADMIN_KEY:<仮の管理鍵>   # http://localhost:8790
```
手元の管理鍵は `.dev.vars`（gitignore 済み）に `ADMIN_KEY=…` の1行で置いてもよい。画面は `quest/index.html` の `BOARD_URL`（公開中の Worker）へ送るので、手元の Worker で試すときはその1行を `http://localhost:8790` に変える（戻し忘れに注意）。

## デプロイ（オーナーの確認を取ってから）
```sh
cd worker
npm install
npm test
npx wrangler deploy                   # Worker と Durable Object（BoardDO）。URL は https://puzzle-quest-board.sakenote.workers.dev
npx wrangler secret put ADMIN_KEY     # 初回だけ：オーナーの削除用（長い乱数。人に渡さない）
npx wrangler secret delete BOARD_KEY  # 合言葉のころの secret。もう使わないので消してよい（残っていても見ない）
```
1. **Worker を先に** deploy してから、パズル箱を push（＝公開）。逆の順だと、新しい画面（合言葉なし）が古い Worker に 403 で断られる
2. 載った記録は合言葉のころのものもそのまま残る

## オーナーが1件消す
```sh
# id を探す（名前・点・id が並ぶ）
curl -s https://puzzle-quest-board.sakenote.workers.dev/board
# 消す
curl -s -X DELETE https://puzzle-quest-board.sakenote.workers.dev/entries/<id> -H "X-Admin-Key: <管理鍵>"
```
（Origin の無い呼び出し＝curl も通る。ブラウザからは `ALLOWED_ORIGINS` のページだけ）

## ゲームの問題を足し替えたら
`npm run mins` → `npm test` → `npx wrangler deploy`。作り直さないと、新しい問題の記録が「最短手数が問題と合いません」で弾かれる。採点の式・段の範囲（`QUEST`）・系統を変えたら `src/rules.js` も直す（`npm test` が `quest/index.html` と突き合わせて落ちる）。

## 調整できる値（wrangler.toml の [vars]）
- `ALLOWED_ORIGINS` 呼んでよいページ（公開先と手元の 8733）
- `RATE_PER_MIN` 1つの IP から1分に載せられる件数（3・叩き台）
- `BAD_KEY_PER_MIN` 1つの IP から1分に許す管理鍵違いの回数（10・叩き台）。超えたらその IP は1分間、正しい管理鍵も含めて削除の要求がすべて 429（当たり外れを見分けさせない）。見る・載せるは止めない

## トラブルが出たら
合言葉の仕組みを戻す（2026-10-15 より前の `src/handler.js`・`test/board.test.js`・`quest/index.html` を git から戻し、`npx wrangler secret put BOARD_KEY`）か、名前を出さないボードにする（`quest/docs/spec.md` §12）

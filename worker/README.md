# puzzle-quest-board（クエストの「みんなの記録」）

合言葉を知る仲間だけのボード。仕様は `../quest/docs/spec.md` §12。Cloudflare Worker ＋ Durable Object 1個（SQLite バックエンド＝無料プランで使える）に上位100件を持つ。

## 中身
- `src/handler.js` 入口の流れ（オリジン → 合言葉 → 検証 → 帳場）と記録の検証 `validateEntry`
- `src/rules.js` 採点の決まり（`quest/index.html` の写し。テストが突き合わせる）
- `src/mins.js` 各ゲームの問題の本当の最小手数（**自動生成**。`npm run mins` で作り直す・手で直さない）
- `src/board.js` ボードの帳場（上位100件・連投の制限・削除）／`src/index.js` Durable Object の外枠
- `tools/build_mins.mjs` 最小手数の表を各ゲームの `index.html` の問題データから作る（`--check` で一致だけ確かめる）

## API（どれも合言葉が要る）
| | ヘッダ | 返すもの |
|---|---|---|
| `GET /board` | `X-Board-Key` | `{entries:[{id,name,score,stages,end,time,emoji,char,rare,at}]}`（上位100件・点の高い順・同点はタイムの速い順） |
| `POST /entries` | `X-Board-Key` | `{ok:true,id,rank}`（rank=0 は100位の外）／400 `{message}`（弾いた理由）／429（連投） |
| `DELETE /entries/:id` | `X-Admin-Key` | `{ok:true}`／404 |

ヘッダの鍵は `encodeURIComponent` した形で送る（画面はそうしている。英数字だけの鍵ならそのままで同じ）。

## 手元で試す
```sh
cd worker
npm install
npm test                      # 鍵は要らない（テストは乱数の仮の鍵）
npx wrangler dev --var BOARD_KEY:<仮の合言葉> --var ADMIN_KEY:<仮の管理鍵>   # http://localhost:8790
```
手元の鍵は `.dev.vars`（gitignore 済み）に `BOARD_KEY=…` と `ADMIN_KEY=…` の2行で置いてもよい。画面は `quest/index.html` の `BOARD_URL`（今は `http://localhost:8790`）へ送る。ページを `http://localhost:8733/quest/#board=<仮の合言葉>` で開くと合言葉を覚える。

## デプロイ（オーナーの確認を取ってから）
```sh
cd worker
npm install
npm test
npx wrangler deploy                   # Worker と Durable Object（BoardDO）ができる。出てきた URL を控える
npx wrangler secret put BOARD_KEY     # 合言葉（仲間に渡すもの）
npx wrangler secret put ADMIN_KEY     # オーナーの削除用（合言葉とは別の長い乱数。人に渡さない）
```
1. 出てきた Worker の URL（`https://puzzle-quest-board.<アカウント>.workers.dev`）を `quest/index.html` の `BOARD_URL` に入れて、パズル箱を push（＝公開）
2. 仲間には `https://y-kanno-sakenote.github.io/puzzle-portal/quest/#board=<合言葉>` を渡す（一度開けばその端末は覚える）。合言葉に日本語や記号を使うなら URL の中では `encodeURIComponent` した形にする
3. 合言葉を変えたいときは `npx wrangler secret put BOARD_KEY` で上書き（古い合言葉の端末は入れなくなる。載った記録は残る）

## オーナーが1件消す
```sh
# id を探す（名前・点・id が並ぶ）
curl -s https://puzzle-quest-board.<アカウント>.workers.dev/board -H "X-Board-Key: <合言葉>"
# 消す
curl -s -X DELETE https://puzzle-quest-board.<アカウント>.workers.dev/entries/<id> -H "X-Admin-Key: <管理鍵>"
```
（Origin の無い呼び出し＝curl は鍵だけで通る。ブラウザからは `ALLOWED_ORIGINS` のページだけ）

## ゲームの問題を足し替えたら
`npm run mins` → `npm test` → `npx wrangler deploy`。作り直さないと、新しい問題の記録が「最短手数が問題と合いません」で弾かれる。採点の式・段の範囲（`QUEST`）・系統を変えたら `src/rules.js` も直す（`npm test` が `quest/index.html` と突き合わせて落ちる）。

## 調整できる値（wrangler.toml の [vars]）
- `ALLOWED_ORIGINS` 呼んでよいページ（公開先と手元の 8733）
- `RATE_PER_MIN` 1つの IP から1分に載せられる件数（3・叩き台）
- `BAD_KEY_PER_MIN` 1つの IP から1分に許す鍵違いの回数（10・叩き台）。超えたらその IP は1分間、正しい鍵も含めて鍵を使う要求がすべて 429（当たり外れを見分けさせない）

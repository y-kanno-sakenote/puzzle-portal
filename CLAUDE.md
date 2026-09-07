# パズル箱（puzzle-portal）

スライド系パズルを集めたポータル。1リポジトリに「入口（`index.html`）＋各ゲームのフォルダ」を置く。
各ゲームは**単一HTML＋自前の docs/ と tools/** で完結し、ポータルはリンクを並べるだけ。

## 収録
- `car-escape/` 車をだせ！（ラッシュアワー型・6×6）— 正典は `car-escape/CLAUDE.md`
- `hakoiri-musume/` 箱入り娘（4×5・娘2×2を下の出口へ）— 正典は `hakoiri-musume/CLAUDE.md`

## 憲法（変えない原則）
- 入口は一覧と進み具合だけ。ランキング・ログイン・広告・共通ライブラリを足さない
- 各ゲームは同じスキームで作る：**生成器（BFSで最短手数を機械検証）→ 単一HTML に埋め込み → `window.<Game>` で純粋ロジック公開 → qa係が独立ソルバーで再検証**。手で盤面を書かない
- ゲーム間でコードを共有しない（小さな重複を許す。共通化はゲームが3つ超えてから決定ログを経て）
- 実機（スマホ）で遊ぶまで「完成」と言わない

## 作業ルール
- 日本語。ローカルプレビュー: ルート `.claude/launch.json` の "puzzle-portal"（python http.server 8733、tailnet からは http://100.71.44.114:8733/）
- 実装した本人は検証しない（qa係）。文言・画面は ui係
- 決定ログ: `docs/decision_log.md`（ポータル横断の判断）＋各ゲームの `docs/decision_log.md`。Vault は `10.Projects/パズル箱/90_開発ログ.md`

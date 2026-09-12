# パズル箱（puzzle-portal）

スライド系パズルを集めたポータル。1リポジトリに「入口（`index.html`）＋各ゲームのフォルダ」を置く。
各ゲームは**単一HTML＋自前の docs/ と tools/** で完結し、ポータルはリンクを並べるだけ。

## 収録
- `car-escape/` 車をだせ！（ラッシュアワー型・6×6）— 正典は `car-escape/CLAUDE.md`
- `hakoiri-musume/` 箱入り娘（4×5・娘2×2を下の出口へ）— 正典は `hakoiri-musume/CLAUDE.md`
- `slide-robots/` すべりロボ（ハイパーロボット型・12×12・宣言してから滑らせる）— 正典は `slide-robots/CLAUDE.md`
- `sudoku/` 数独（9×9・別スキーム＝一意解と推論の強さを検証）— 正典は `sudoku/CLAUDE.md`
- `mado-wake/` 窓わけ（領域分割・ルール組み合わせ・別スキーム）— 正典は `mado-wake/CLAUDE.md`
- `hoshi-oki/` 星おき（Queens 型・色/行/列に★1つ・隣接禁止・一意解）— 正典は `hoshi-oki/CLAUDE.md`
- `michi-tsunagi/` みちつなぎ（同じ数字を線でつなぐ・全マスを通る・一意解）— 正典は `michi-tsunagi/CLAUDE.md`
- `kurukuru/` くるくる（タップで回してパイプをつなぐ・一意解）— 正典は `kurukuru/CLAUDE.md`
- `hayatsukami/` はやつかみ（**箱で唯一の対戦**・向かい合って早取り）— 正典は `hayatsukami/CLAUDE.md`
- `pixel/` ピクセル（お絵描きロジック・5×5/10×10・一意解・完成で絵が浮かぶ）— 正典は `pixel/CLAUDE.md`

## 憲法（変えない原則）
- 入口は一覧と進み具合だけ。ランキング・ログイン・広告・共通ライブラリを足さない
- スライド系は同じスキームで作る（数独のような別系統は、その旨を各ゲームの憲法に書く）：**生成器（BFSで最短手数を機械検証）→ 単一HTML に埋め込み → `window.<Game>` で純粋ロジック公開 → qa係が独立ソルバーで再検証**。手で盤面を書かない
- ゲーム間でコードを共有しない（小さな重複を許す。共通化はゲームが3つ超えてから決定ログを経て）
- 実機（スマホ）で遊ぶまで「完成」と言わない

## 作業ルール
- 公開先: GitHub Pages https://y-kanno-sakenote.github.io/puzzle-portal/（main の root。push＝公開なので指示があるときだけ）
- 日本語。ローカルプレビュー: ルート `.claude/launch.json` の "puzzle-portal"（python http.server 8733、tailnet からは http://100.71.44.114:8733/）
- 実装した本人は検証しない（qa係）。文言・画面は ui係
- 決定ログ: `docs/decision_log.md`（ポータル横断の判断）＋各ゲームの `docs/decision_log.md`。Vault は `10.Projects/パズル箱/90_開発ログ.md`

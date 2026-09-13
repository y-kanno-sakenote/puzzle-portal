担当: 🧪 qa係

# ピクセル 再検証（2026-09-13・名画長方形化後）

## 結果: PASS

## 1. 既存 qa_check.py
`tools/qa_check.py`: 60問全問 `[OK] 一意解確認完了`、`ALL 60 PASSED`。
`tools/qa_indep.py`は今回未実行（qa_check.pyの独立バックトラック一致確認で一意解の証拠として足りると判断。
足さない案：qa_indep.pyの周回数分析は難度体感の傾向調査で、一意解の合否には寄与しないため今回は省略）。

## 2. index.html 埋め込み vs tools/puzzles.json
`var PUZZLES = [...]` 60問 deep equal（tools/puzzles.jsonと完全一致）。

## 3. 公開オブジェクト（window.Pixel）の検証関数
1本の`<script>`を`window.Pixel = Pixel;`までの範囲でvm実行。`Pixel.isSolution(p, state)`を60問で実行:
正解state→全問true、1マス反転させた誤りstate→全問false。FAIL 0件。

## 4. localStorage 壊れ値
保存キー名: `pixel-v2`
1本の`<script>`をvm実行、9パターン全部OK（未捕捉例外なし）。
※検証ハーネスのDOMスタブに`window.addEventListener`と`artImg.removeAttribute`が無いと落ちる
（ゲーム側の欠陥ではなくスタブ不備）。スタブ補完後は全パターン通過。

## 5. docs/spec.md との照合
段階配分（入門10/初級10/中級10/上級10/特級5/達人5/名画10=計60）・Dレンジ/Sレンジの実測表は
実データと一致。乖離なし。

## 6. 名画art項目とdocs/artworks.jsoの突合
puzzles.json側の`art`10件とartworks.json台帳10件、id集合が完全一致（過不足なし）。
`is_public_domain`は10件全て`true`。`art/`配下の画像ファイルも10件全て存在（欠落なし）。

## 7. 長方形盤の描画コード読解
`calculateSizes()`・`setupDOM()`とも`currentPuzzle.w`/`currentPuzzle.h`を独立変数として扱い、
`gridTemplateColumns=repeat(w,...)`・`gridTemplateRows=repeat(h,...)`・セルインデックス`i*w+j`で構築。
正方形決め打ちのハードコードは無く、25×25以外（18×30・25×20・25×17・16×30等）の長方形盤も
コード上は同じロジックで描画される設計になっている（コード読解のみ、実機描画は未確認）。

## 8. 保存キー
`SAVE_KEY = 'pixel-v2'`。旧キー`'pixel'`はコード中で読んでいない
（`index.html`323行目コメント「問題を50問に組み替えた。添字がずれるので旧キー'pixel'は読まない」で明示）。

## 【要確認】長方形盤の実機表示
7は静的コード読解のみ。375×667等の実機スマホでの縦長盤（18×30等）のレイアウト崩れ有無は
実機確認が必要（担当外）。

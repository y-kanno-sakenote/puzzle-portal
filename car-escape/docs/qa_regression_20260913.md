担当: 🧪 qa係

# 車をだせ！ 回帰再検証 2026-09-13

対象: `index.html`（50問）、`tools/levels.json`

## 1. 独立ソルバー（tools/qa_solver.py）
`python3 tools/qa_solver.py tools/levels.json --paths <scratch>` 実行。**PASS**：`boards=50 dup=0 all_ok=True`（min手数・tier 全50本 impl=qa 一致）。

## 2. embed(index.html) と tools/levels.json の一致
Python で `<script>` 内 `var LEVELS` を正規表現抽出し `tools/levels.json` と構造比較。**PASS**：50件完全一致。

## 3. Node実走 CarEscape.solve() 50本照合
`window` のみ定義した vm サンドボックスで `CarEscape.solve(board)` を50本呼び出し、`tools/levels.json` の `min` と突合。**PASS**：mismatches=0、最長61ms。
※ `solve()` の戻り値は手数の数値そのもの（オブジェクトではない）。最初のスクリプトで `r.min` と誤って比較し50件FAILと出たが、これは検証スクリプト側の誤り（`r`自体が数値）。修正後に再実行し0件に訂正。

## 4. localStorage 壊れ値
`tools/qa_solver.py` 内蔵ではなく、DOMスタブで `<script>` 全体を実走（前回2026-09-09と同一手法）。7ケース（非JSON文字列／last小数／last負数／last巨大／cleared文字列／null／getItem例外）全て**PASS**（クラッシュ無し）。

## 5. docs/spec.md との整合
`spec.md`「入門3〜5/初級6〜10/中級11〜18/上級19〜31/達人32〜」「各10本計50本」「達人だけ12台まで」＝qa_solver.py出力のtier列（全50本 impl_tier=qa_tier 一致）と符合。齟齬なし。

## 保存キー
`localStorage` キー名: `'car-escape'`。保存内容 `{cleared: {...}, last: number}`。

## 総合
1〜5 全PASS。前回2026-09-09時点から機能面の劣化なし（levels.json 50件・embed一致・solve一致とも崩れていない）。

## 未検証（範囲外）
実ブラウザでのポインタドラッグ・スマホ実機タッチ操作は担当外。

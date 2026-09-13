担当: 🧪 qa係

# みちつなぎ 回帰再検証 2026-09-13

対象: `index.html`、`tools/puzzles.json`（40問）。前回独立検証は `docs/qa_report_20260910.md`。

## 1. 独立ソルバー（tools/qa_check.py）
`python3 tools/qa_check.py` 実行。**PASS**：40/40 解=1・solution一致（計3.1秒）。

## 2. embed(index.html) と tools/puzzles.json の一致
qa_check.py内蔵チェックで**PASS**（差分0）。別途Pythonで `var PUZZLES` を抽出し再比較しても一致。

## 3. Node実走 JSロジック照合
qa_check.py 内蔵の Node 実行。**PASS**：
- `countSolutions` 40/40 が1（最長27ms）
- `isComplete`（正解）40/40 true
- `isComplete`（壊れ状態: 1マス空き／対未接続／完全重複path／両端接続だが全マス未被覆）全てfalse

## 4. localStorage 壊れ値
qa_check.py内蔵、最小DOMスタブでNode実走。**PASS**：全12ケースでクラッシュなし。

## 5. docs/spec.md との整合
難度ノード数実測: 入門34〜100／初級90〜600／中級316〜2373／上級3673〜40042。spec.md記載レンジと一致。段階順の逆転なし（中央値 65→220→1106→18230 と単調増加）。齟齬なし。

## 保存キー
`localStorage` キー名: `'michi-tsunagi'`。保存内容 `{cleared:{idx:1}, last:idx, paths:{idx:"引きかけの道"}}`。

## 総合
1〜5 全PASS。前回2026-09-10（`qa_report_20260910.md`）から劣化なし。

## 未検証（範囲外）
実機（スマホ）での指なぞり操作は担当外。

担当: 🧪 qa係

# 数独 再検証（2026-09-09）

## 結果: PASS

## 1. 既存 qa_check.py
```
python3 tools/qa_check.py
count: 40
uniqueness_fail PASS / solution_mismatch PASS / hint_mismatch PASS /
solution_not_complete PASS / tier_mismatch PASS / length_bad PASS /
givens_mismatch PASS / floor_violation PASS / order_violation PASS
総合: PASS
```

## 2. index.html 埋め込み vs tools/puzzles.json
40問 deep equal（JSON.stringify比較で完全一致）。

## 3. 公開オブジェクト（window.Sudoku）の検証関数
Node vm で1本目の`<script>`を実走し、`Sudoku.countSolutions(Sudoku.parse(p.puzzle), 2)`を40問で実行。
全問 `1`（一意解）。FAIL 0件。

## 4. localStorage 壊れ値
保存キー名: `sudoku`
2本の`<script>`を連結してvm実行し、9パターンで例外の有無を確認。
非JSON文字列 / last小数(2.5) / last負(-3) / last範囲外(99999) / last文字列型("abc") /
配列全体 / null / clearedが配列 / getItem throw — **全パターン OK（未捕捉例外なし）**。
`loadSave()`が`Number.isInteger(o.last) && o.last>=0 && o.last<PUZZLES.length`で防御しており頑健。

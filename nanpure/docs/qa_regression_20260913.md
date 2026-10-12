担当: 🧪 qa係

# 数独 再検証（2026-09-13）

## 結果: PASS

## 1. 既存 qa_check.py
```
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
全問 `1`（一意解）。FAIL 0件。最遅個体 index=12 1ms。

## 4. localStorage 壊れ値
保存キー名: `sudoku`
2本の`<script>`を連結してvm実行し、9パターン（非JSON文字列/last小数(2.5)/last負(-3)/last範囲外(99999)/
last文字列型("abc")/配列全体/null/clearedが配列でない/getItem throw）で例外の有無を確認。
全パターン OK（未捕捉例外なし）。

## 5. docs/spec.md との照合
ヒント数下限（入門36・初級28・中級24・上級17）に対し実データの最小値は入門36・初級28・中級26・上級24で、
いずれも下限以上（下限より易しい盤は存在しない＝仕様通り）。段階配分は各10本・計40本で一致。

担当: 🧪 qa係

# 箱入り娘 回帰再検証 2026-09-13

対象: `index.html`、`tools/levels.json`（40本）

## 1. 独立ソルバー（tools/qa_solver.py）
`python3 tools/qa_solver.py` 実行。**PASS**（`OVERALL PASS`）。
- 盤面重複: 0/40、空きマス最小: 2マス（規定 >=2 を満たす）

## 2. embed(index.html) と tools/levels.json の一致
qa_solver.py内蔵チェックで `True`。別途Pythonで `var LEVELS` を正規表現抽出し `levels.json` と再比較しても**PASS**（40件完全一致）。

## 3. Node実走 Hakoiri.solve() 40本照合
qa_solver.py 内蔵の Node vm 実行で40本全一致。**PASS**：`JS solve() 全一致: True / 最長 676ms`（盤 `BAACBAADoEoDFFGHIoJo`）。

## 4. localStorage 壊れ値・境界値
- 境界値（canMove/applyMove の盤外・対角・不正id等）：**PASS**（全ケース意図通りfalse/null）
- localStorage 7ケース（非JSON/last小数/負数/巨大/cleared文字列/null/getItem例外）：**PASS**（クラッシュ無し）
- 自動プレイ（自前最短経路をapplyMoveで適用）：**PASS**（40/40成功）

## 5. docs/spec.md との整合
tier別min実測: 入門5〜15／初級16〜35／中級36〜70／上級71〜114。spec.md記載の閾値（入門5〜15／初級16〜35／中級36〜70／上級71〜）と一致。齟齬なし。

## 保存キー
`localStorage` キー名: `'hakoiri-musume'`。

## 総合
1〜4 は qa_solver.py の `OVERALL PASS` に集約。5 は今回追加でtierレンジの上限下限を再計算し確認。前回2026-09-09から劣化なし。

## 未検証（範囲外）
実ブラウザ実機操作は担当外。

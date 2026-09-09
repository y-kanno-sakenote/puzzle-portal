担当: 🧪 qa係

# 箱入り娘 回帰再検証 2026-09-09

対象: `index.html`、`tools/levels.json`（40本）

## 1. 独立ソルバー（tools/qa_solver.py）
`python3 tools/qa_solver.py` 実行。**PASS**（`OVERALL PASS`）。
- 盤面重複: 0/40
- 空きマス最小: 2マス（規定 >=2 を満たす）

## 2. embed(index.html) と tools/levels.json の一致
qa_solver.py 出力：`embed(index.html) と tools/levels.json 一致: True`。**PASS**。

## 3. Node実走 Hakoiri.solve() 40本照合
qa_solver.py 内蔵の Node vm 実行で40本全一致。**PASS**：`JS solve() 全一致: True / 最長 611ms`（盤 `BAACBAADoEoDFFGHIoJo`）。

## 4. localStorage 壊れ値・境界値
- 境界値（canMove/applyMove の盤外・対角・不正id等）：**PASS**（全ケース意図通りfalse/null）
- localStorage 7ケース（非JSON/last小数/負数/巨大/cleared文字列/null/getItem例外）：**PASS**（クラッシュ無し）
- 自動プレイ（自前最短経路をapplyMoveで適用）：**PASS**（40/40成功）

## 5. docs/spec.md との整合
盤面から検証項目に食い違いは見当たらず。相互Jaccard最大0.455（0.5超のペア0組）で家族化なし、spec記載の「盤面のバリエーション確保」方針と符合。

## 保存キー
`localStorage` キー名: `'hakoiri-musume'`（`index.html` 348行目 `var KEY = 'hakoiri-musume';`）。

## 総合
1〜4 全項目 qa_solver.py の `OVERALL PASS` に集約。今回はスクリプトを素通しで再実行しただけで、独立チェックとして別途Node比較は不要と判断（qa_solver.py が既にNode vm照合とlocalStorage壊れ値検証を内蔵しているため）。

## 未検証（範囲外）
実ブラウザ実機操作は範囲外。

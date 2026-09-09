担当: 🧪 qa係

# すべりロボ 回帰再検証 2026-09-09

対象: `index.html`、`tools/levels.json`（40本）

## 1. 独立ソルバー（tools/qa_solver.py）
`python3 tools/qa_solver.py` 実行。**PASS**（`OVERALL PASS`）。独立BFS 全一致。

## 2. embed(index.html) と tools/levels.json の一致
qa_solver.py 出力：`embed一致=True`。**PASS**。

## 3. Node実走 SlideRobots.solve() 40本照合
qa_solver.py 内蔵の Node vm 実行で40本全一致。**PASS**：`JS solve() 全一致: True / 最長 65ms`（#39）。
※ `solve()` は盤面文字列でなく level オブジェクト（`{w, walls, robots, target, min, tier}`）を引数に取る設計（car-escape/hakoiri-musumeの `solve(board文字列)` とシグネチャが異なる点に注意）。

## 4. localStorage 壊れ値・境界値
- 境界値（slide/applyMove の不正id・不正方向・盤外座標）：**PASS**（全て null / 状態不変）
- 「盤外座標を直接書き換えてslide()」チェックあり：戻り値 `{"result":null}` で安全に弾かれる
- localStorage 7ケース：**PASS**（クラッシュ無し）
- 自動プレイ：**PASS**（40/40成功）

## 5. docs/spec.md との整合
levels.json の tier別min範囲を実測：入門3-4／初級5-6／中級7-8／上級9-12（各10本）。spec.md 30行「入門3〜4／初級5〜6／中級7〜8／上級9〜」と一致。齟齬なし。

## 保存キー
`localStorage` キー名: `'slide-robots'`（`index.html` 382行目 `var KEY = 'slide-robots';`）。

## 総合
1〜4 全項目 qa_solver.py の `OVERALL PASS` に集約。qa_solver.py が既にNode vm照合とlocalStorage壊れ値検証を内蔵しているため、今回は素通し再実行のみで独立性は担保されている（実装コードを一切使わない別BFSで照合済み）。

## 未検証（範囲外）
実ブラウザ実機操作は範囲外。

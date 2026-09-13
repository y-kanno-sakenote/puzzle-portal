担当: 🧪 qa係

# すべりロボ 回帰再検証 2026-09-13

対象: `index.html`、`tools/levels.json`（40本）

## 1. 独立ソルバー（tools/qa_solver.py）
`python3 tools/qa_solver.py` 実行。**PASS**（`OVERALL PASS`）。独立BFS 全一致。

## 2. embed(index.html) と tools/levels.json の一致
qa_solver.py出力：`embed一致=True`。別途Pythonで `var LEVELS` を抽出し再比較しても**PASS**（40件完全一致）。

## 3. Node実走 SlideRobots.solve() 40本照合
qa_solver.py 内蔵の Node vm 実行で40本全一致。**PASS**：`JS solve() 全一致: True / 最長 65ms`。

## 4. localStorage 壊れ値・境界値
- 境界値（slide/applyMove の不正id・不正方向・盤外座標）：**PASS**（全て null / 状態不変）
- 盤外座標を直接書き換えてslide()：戻り値 `{"result":null}` で安全に弾かれる
- localStorage 7ケース：**PASS**（クラッシュ無し）
- 自動プレイ：**PASS**（40/40成功）

## 5. docs/spec.md との整合
tier別min実測: 入門3〜4／初級5〜6／中級7〜8／上級9〜12。spec.md記載「入門3〜4／初級5〜6／中級7〜8／上級9〜」と一致。齟齬なし。

## 保存キー
`localStorage` キー名: `'slide-robots'`。保存内容 `{cleared:{idx:1}, last:idx}`。

## 総合
1〜5 全PASS。前回2026-09-09から劣化なし。

## 未検証（範囲外）
実ブラウザ実機操作は担当外。

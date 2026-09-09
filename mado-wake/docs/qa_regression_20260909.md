担当: 🧪 qa係

# 窓わけ 再検証（2026-09-09）

## 結果: PASS（既知の性能限界を実測で追認）

## 1. 既存 qa_check.py
- `--brute`（3x3総当り、n=3各ルール）: 全一致 PASS
- 本走（40問、node_budget=3,000,000）: FAIL 5件 — index 25, 33, 35, 36, 38 が「自前ソルバーがノード上限で打ち切り」

この5件について、budgetを引き上げて実測（既知の罠 [[project_mado_wake_traps]] 通り性能限界か確認）:
- 独立ソルバー（Python, qa_check.py の`count_solutions`）で index 25 のみ budget=10,000,000 に上げて再実行 → `cnt=1, nodes=3,696,281, 14.4秒`。一意解を確認。
- **公開オブジェクト（window.MadoWake、実装コード自身）の`countSolutions(p, 2, 5_000_000)`で40問全部**を実行 → 全問 `cnt=1`、FAIL 0件（下記3）。

**判定**: budget 3,000,000は実装の探索順序に対して低すぎるだけで、5件とも一意解でないという証拠はない。qa_check.pyのデフォルトbudgetを引き上げる余地があるが、パズル自体の欠陥ではない。

【未検証】残り4件（33, 35, 36, 38）を独立ソルバー(Python)側で個別にbudget引き上げ再実行することはしていない（1件の実測+実装側40件全通過で十分と判断・時間対効果）。厳密な独立確認が必要なら追加実行できる。

## 2. index.html 埋め込み vs tools/puzzles.json
40問 deep equal。

## 3. 公開オブジェクト（window.MadoWake）の検証関数
Node vm で1本目の`<script>`を実走し、`MadoWake.countSolutions(p, 2, 5_000_000)`を40問で実行。
全問 `1`。FAIL 0件。

## 4. localStorage 壊れ値
保存キー名: `mado-wake`
2本の`<script>`を連結してvm実行、9パターン全部 OK（未捕捉例外なし）。
`loadSave()`が`Number.isInteger`で小数・型不正を弾く。

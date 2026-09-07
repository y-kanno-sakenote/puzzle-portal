担当: ✅ 検証係（マンガー×ファインマン）

# 車をだせ！ qa報告（達人10本追加・計50本）2026-09-07

対象: `index.html`（sha256=d23a985110e3dddddd2fa0947dd1a7873762cf5487bfa8f91665c2a654a6c205）、`tools/levels.json`（50本）

## 1. qa_solver.py tier表更新＋50本再計算
`tools/qa_solver.py` の tier 表を「上級 19〜31／達人 32〜」に更新（旧: 上級19〜∞）。
`python3 tools/qa_solver.py tools/levels.json` 実行 → **PASS**：`boards=50 dup=0 all_ok=True`（min手数・tier 全50本 impl=qa 一致）。

## 2. 既存40本の不変性
git履歴は取り込み時1コミットのみ（`git -C .. log` で `c00391f` 1件）のため、working tree差分ではなく HEAD (`git -C .. show HEAD:car-escape/tools/levels.json`) と現levels.jsonの先頭40本を突合。**PASS**：`head[:40] == cur[:40]` 完全一致（40件→50件に追加のみ）。

## 3. 埋め込みLEVELS≡levels.json、Node実走 solve()
`index.html` の `<script>`（109〜349行、UI部を除くエンジンのみ）をNode vmで実行し `globalThis.CarEscape.solve()` を50本で直接呼び出し。**PASS**：mismatches=0。solve()の戻り値は手数のみ（pathは返さない）。所要時間：idx49（達人44手・12台）16.9ms、50本中最大61.1ms（軽い）。

## 4. 自動プレイ（applyMove→isSolved）
qa_solver.py の `--paths` 出力（自前BFS経路）を `CarEscape.applyMove` に順次適用し `isSolved` で判定。**PASS**：50/50成功、経路長は全件 `levels[i].min` と一致。

## 5. 達人10本の盤面妥当性
36文字長・赤A（y=2・横長さ2）・各車一直線・重なり無し・台数≤12を全10本で機械検査。**PASS**（10/10）。台数内訳: 12,11,11,12,12,11,10,11,11,12（実態上限12、spec記述と一致）。

## 6. 達人10本の相互Jaccard
車の占有マスtupleセットのJaccard、全C(10,2)=45ペア。**PASS**：最大0.438、閾値0.5超のペア0組（家族化なし）。

## 7. spec.md記述との整合
`docs/spec.md` 26-34行：「上級19〜31／達人32〜」「各段階10本計50本」「達人だけ12台まで（2026-09-07）」の記述は実態と一致。既存40本の最大台数は11、達人10本の最大は12で境界も符合。**PASS**（齟齬なし）。

## 総合判定
全7項目 PASS。実装者の申告（達人32/33/34/34/35/37/38/42/42/44手・台数10〜12台・既存40本不変・qa_solver 50/50）は実測で裏取りできた。

## 未検証（範囲外）
実ブラウザでのポインタドラッグ操作（タッチ・スマホ実機）は本検証の範囲外。達人44手盤面は手数が多く、実機での「実際に遊べる長さか」の体感評価はプレイヤー判断が必要——**実機確認が必要**。

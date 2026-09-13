担当: 🧪 qa係（マンガー×ファインマン）

# かぶせっこ ヘルプパネル追加後の回帰検証（2026-09-13）

## 1. 既存検証スクリプトの実行結果
`tools/qa_check.py`: **全項目 PASS**（合法手・勝ち判定・でたらめ対局1000局／長引かせ100局／
合法手ゼロ局面の探索、すべて食い違い・破損0件）。

`tools/qa_indep.py`: 初回実行 **FAIL**（[5]localStorage壊れ値11件すべてエラー）。

```
NG  localStorage: 非JSON文字列 → 起動が落ちない
    Cannot read properties of null (reading 'addEventListener')
```

原因切り分け: `qa_indep.py` の `STORAGE_HARNESS` 内 `makeDocument()` の id リストに
`helpBtn`/`helpPanel` が無かった（hayatsukamiと同型の罠）。index.html 側には
両id実在（133-134行目）。**検証スクリプトのスタブ陳腐化**であり実装バグではない。

裏取り: 一時的に id リストへ追加したパッチ版を `tools/` 配下で実行（実行後即削除）
→ **全項目 PASS**（[1]〜[7]すべてOK、探索400,005局面で合法手ゼロ0件）。

## 2. window.Kabusekko の実走
qa_check.py・qa_indep.py（パッチ版）双方で isLegal/legalMoves/applyMove/winnersOf を
Node vm で実走し、独立Python実装・でたらめ対局2000局超と完全一致。公開オブジェクトは
正常動作（move.player明示すり抜けの既知の罠は今回スコープ外・前回report参照）。

## 3. localStorage 壊れ値
qa_indep.py は11パターン（非JSON/raw=null/配列JSON/wins無し/wins型不正/wins.top文字列/
wins.top負数/wins.top小数/wins=null/getItem throw/setItem throw）をカバーしパッチ版で
全PASS。**seen型不正は未カバー**だったため自前スクリプト（scratchpad/seen_check.js）で
文字列'x'／'0'／負数／null／配列／オブジェクト／NaN を追加検証 → **全パターンで
起動が落ちない**（PASS）。**保存キー = `kabusekko`**。

## 4. #helpPanel / #helpBtn
両方とも index.html に実在（133-134行目）。`store.seen` による初回自動表示・？ボタン
再表示は実装通り動作。文言（「大きい駒は小さい駒にかぶせられる」等）は spec.md の
ルール説明と矛盾なし。

【要確認】spec.md（v0.1）にヘルプパネル機能・`seen`保存項目の記載が無い（hayatsukamiと
同じ更新漏れ）。

## 5. 「足さないもの」の遵守
qa_indep.py [7] で禁止語チェック PASS（検出=[]）。制限時間・待った・CPU相手・音・
盤サイズ変更・下を覗く機能・手数表示は見当たらない。

## 結論
ゲームロジックは **PASS**。**差し戻し対象は tools/qa_indep.py のみ**
（helpBtn/helpPanel を id リストに追加すれば正しく動く。実装コード側の修正は不要）。

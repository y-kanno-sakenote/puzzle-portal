担当: 🧪 qa係（マンガー×ファインマン）

# はやつかみ ヘルプパネル追加後の回帰検証（2026-09-13）

## 1. 既存 tools/qa_check.py の実行結果
初回実行: **FAIL**（総合FAIL、11件エラー）。

```
elHelpPanel.addEventListener('click', hideHelp);
              ^
TypeError: Cannot read properties of undefined (reading 'addEventListener')
```

原因切り分け: `tools/qa_check.py` 内 `buildSandbox()` の DOM スタブが持つ固定 id リスト
（`ids = ['rotate','app','countTop',...,'resBottom']`）に `helpBtn`/`helpPanel` が
無かった。index.html には両 id とも実在する（118-119行目）。**実装バグではなく
検証スクリプトのスタブ陳腐化**（ヘルプパネル追加に qa_check.py の更新が追従していない）。

裏取り: scratchpad にコピーした qa_check.py の ids リストへ `'helpBtn','helpPanel'` を
追加した上で、一時的に `tools/` 配下で実行（実行後即削除、原本は無変更）→ **全項目 PASS**。
先着ロジック本体・お手つき・7枚決着・localStorage 復元は健全と確認できた。

## 2. window.Hayatsukami の実走
パッチ版 qa_check.py 内で `Hayatsukami.answerOf` / `isValidCard` / 先着判定を Node vm で
実走し、300通り全数照合・壊れ値10パターンとも PASS。公開オブジェクトは正常動作。

## 3. localStorage 壊れ値
既存 qa_check.py がカバーするのは5パターン（空／非JSON／wins型不正／負数／getItem例外）
のみで、**setItem throw・配列JSON・wins無し・wins=null・seen型不正は未カバー**。
上記5件はパッチ版で PASS。**保存キー = `hayatsukami`**、値は `{wins:{top,bottom}, seen}`。

追加で自前スクリプト（scratchpad/seen_check.js）を書き、seen に文字列'x'／文字列'0'／
負数／null／配列／オブジェクト／NaN を入れて起動を実走 → **全パターンで起動が落ちない**。
truthy 値は「見た扱い」(helpPanelHidden=true)、falsy(null/NaN) は「未見扱い」で再表示、
という if(o.seen) のtruthy判定通りの挙動で、クラッシュも誤動作もなし。**PASS**。

## 4. #helpPanel / #helpBtn
両方とも index.html に実在（118-119行目）。`store.seen` による初回だけ自動表示
（649行目 `if (!store.seen) showHelp();`）、以降は？ボタンから開閉、が実装通りに動作。
文言（「形と色が正しい品が1つあれば、それを取る」等）は spec.md の判定ルール・
お手つきルールと矛盾しない。

【要確認】spec.md（v0.2）にはヘルプパネル機能自体の記載が無く、保存欄も
`{wins:{top:n,bottom:n}}` のみで `seen` フィールドの追記が無い。仕様書の更新漏れ。

## 5. 「足さないもの」の遵守
index.html に制限時間・音・連打・CPU対戦・練習モードに相当する語やコードは
見当たらない。禁止語チェック（qa_check.py内）も PASS。

## 結論
ゲームロジック自体は **PASS**（実測: パッチ版で全項目通過）。
**差し戻し対象は tools/qa_check.py のみ**（helpBtn/helpPanelをidリストに追加すれば
今後の回帰検証が正しく動く。実装コード側の修正は不要）。

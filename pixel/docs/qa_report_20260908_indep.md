担当: 🧪 qa係（独立検証・既存 tools/qa_check.py は未参照で独自実装）

## 1. 自前ラインソルバー（tools/qa_indep.py）
PASS: 40問全問、行・列の確定伝播だけ（仮定なし）で完全に解け、solutionと一致。ヒントもsolutionから機械的に再導出でき整合。solution長もw*hと一致。

## 2. 難度の実態
FAIL相当（逆転あり）: no20「ハサミ」(初級)だけ反復9周を要し全40問中最多。一方「上級」10問(no31-40)は全問一律iter=3で、40問中もっとも浅い部類。段階別平均周回数は 入門2.80 < 初級3.70 > 中級2.90 < 上級3.00 で単調でない。上級が名前通り難しいという実測的根拠がない。

## 3. 絵の妥当性（docs/pixel_gallery.txt）
FAIL: no36「宇宙飛行士」とno38「マトリョーシカ」はsolution/ヒントが完全に同一（同じ絵に別の題名を付けているだけ）。上級6問(31,34,35,36,37,38)は概ね同型の汎用ひし形ブロブで、題名が示す特徴（ヘルメット/だるまの顔/骸骨の目穴/入れ子人形の重なり）が絵から見て取れない。

## 4. JS整合
PASS: index.html埋め込みPUZZLES / tools/puzzles.json / node vm実行のPixel.isSolutionが40問すべて一致。正解グリッドでtrue、1マス反転でfalseを確認。

## 5. localStorage壊れ値
FAIL: `save.last` が整数以外の数値（例 `last:2.5`）のとき、`idx<0||idx>=PUZZLES.length`のガードを素通りし `PUZZLES[2.5]` が undefined となり `currentPuzzle.tier` 参照で例外、起動即クラッシュ。他7パターン（非JSON文字列・grid長さ不正・getItem例外・cleared配列化・トップレベル配列・null）はPASS（初期化されて継続）。

## 6. 途中フィードバック / ×印
PASS: judge()はpointerup/pointercancel時にのみ`Pixel.isSolution`の完全一致判定を行い、途中経過の正誤表示は画面コードに存在しない。×印(値2)はisSolutionの比較対象外（`state[i]===1`のみ判定）でメモ用途に徹しており、仕様と一致。

## 直すべき順
1. `save.last` に `Number.isInteger` チェックを追加（壊れ値で即クラッシュする実害。他の壊れ値は防げているのにここだけ穴）
2. no36/no38の重複絵（同一solution）をどちらか差し替え
3. 上級ティア（特に31,34,35,36,37,38）の絵と難度を作り直す — 絵は汎用ブロブで見分けがつかず、難度も実測周回数で中級以下

【要確認】これらは自動テストのみで実機未確認。実機（スマホ）でのドラッグ入力・完成演出は担当外。

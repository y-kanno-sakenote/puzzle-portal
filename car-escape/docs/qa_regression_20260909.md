担当: 🧪 qa係

# 車をだせ！ 回帰再検証 2026-09-09

対象: `index.html`（sha256=d23a985110e3dddddd2fa0947dd1a7873762cf5487bfa8f91665c2a654a6c205、`docs/qa_report_20260907_master.md` 時点と同一ファイル＝変更なし）

## 1. 独立ソルバー（tools/qa_solver.py）
`python3 tools/qa_solver.py tools/levels.json --paths <scratch>` 実行。**PASS**：`boards=50 dup=0 all_ok=True`（min手数・tier 全50本 impl=qa 一致、exit 0）。
※引数なしで叩くと `sys.argv[1]` で `IndexError`（このスクリプトは levels.json パス必須の設計。バグではない）。

## 2. embed(index.html) と tools/levels.json の一致
`<script>` 内 `var LEVELS` を Node vm で抽出し levels.json と `JSON.stringify` 比較。**PASS**：完全一致（50件）。

## 3. Node実走 CarEscape.solve() 50本照合
`window` のみ定義（`document` 未定義でUI初期化IIFEをスキップしエンジンのみ実走）した vm サンドボックスで `CarEscape.solve(board)` を50本呼び出し、qa_solver.py の独立BFS結果（`impl.min`）と突合。**PASS**：mismatches=0、最長60ms。
※ car-escape の qa_solver.py 自体はこのNode照合を内蔵していない（hakoiri/slide-robotsは内蔵済み）。今回はqa係が別途Node vmスクリプトで実施。

## 4. localStorage 壊れ値
DOMスタブ（[[technique_vm_dom_stub]]相当）で `<script>` 全体（UI初期化含む）を実走。7ケース（非JSON文字列／last小数／last負数／last巨大／cleared文字列／null／getItem例外）全て**PASS**（クラッシュ無し）。実装は `loadSave()` を try/catch で囲み、`o.last` を `Number.isInteger && 0<=last<LEVELS.length` で検証してから採用（範囲外・小数・型不正は黙って初期値 `last=0` に戻る）。

## 5. docs/spec.md との整合
`spec.md` 26行「入門3〜5/初級6〜10/中級11〜18/上級19〜31/達人32〜」「各10本計50本」「達人だけ12台まで」＝実データと一致。齟齬なし。

## 保存キー
`localStorage` キー名: `'car-escape'`（`index.html` 357行目 `var KEY = 'car-escape';`）。保存内容 `{cleared: {...}, last: number}`。

## 総合
1〜5 全PASS。前回（2026-09-07master）から index.html 変更なしのため機能面の劣化なし。

## 未検証（範囲外）
実ブラウザでのポインタドラッグ・スマホ実機タッチ操作は本検証の範囲外（要実機確認、担当外）。

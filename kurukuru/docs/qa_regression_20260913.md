担当: 🧪 qa係

# くるくる 回帰再検証 2026-09-13（`docs/qa_report_20260913.md` の初版検証を踏まえた再実行）

対象: `index.html`、`tools/puzzles.json`（40問）

## 1. 独立ソルバー（tools/qa_check.py）
`python3 tools/qa_check.py tools/puzzles.json` 実行。**PASS**：
`[自己検証] n=2,3 総当たり vs 列優先ソルバー: 300試行 mismatch=0` / `[40問] bad=0件`。

## 2. embed(index.html) と tools/puzzles.json の一致
Python で `var PUZZLES` を正規表現抽出し `tools/puzzles.json` と比較。**PASS**：40件完全一致。

## 3. Node実走 JSロジック照合（新規実施・qa_check.pyには未内蔵）
`window.Kurukuru` を vm で実走し `countSolutions`/`isSolved`/`rotate` を40問照合。**PASS**：
- `countSolutions(p,2)` 全問1、最長1ms
- `isSolved(solution)`=true・`isSolved(cells)`=false 全問
- `rotate(m,4)===m` 0〜15全パターンで反例0

## 4. localStorage 壊れ値（新規実施・qa_check.pyには未内蔵）
DOMスタブ（最小Elクラス、`style`含む）で `<script>` 2ブロックをそのまま実走。15パターン
（非JSON文字列／null文字列／数値／文字列／配列／last小数・負数・範囲外／cleared型不正／rot型不正・値型不正・長さ不正・不正16進／getItem例外／setItem例外）
全て**PASS**（クラッシュ無し）。
※ 検証スクリプト初回作成時にDOMスタブへ`style`プロパティを入れ忘れ全15件が`transformOrigin`設定エラーでFAILしたが、これはスタブ側の不備（実装のバグではない）。修正後に全PASS。

## 5. docs/spec.md との整合
`tools/puzzles.json` の `nodes`（行優先・実装値）を段階別集計：入門32〜51／初級57〜96／中級113〜203／上級242〜409。
spec.md記載の「採用する nodes の帯」表と完全一致。齟齬なし。

## 保存キー
`localStorage` キー名: `'kurukuru'`。保存内容 `{cleared:{idx:1}, last:idx, rot:{idx:"各マスの向き(16進)"}}`。
`restore()` が文字列型・長さ・16進範囲・4回転一致を全てチェックしてから採用するため、壊れた`rot`値は黙って無視され出題時の向きに戻る（堅牢）。

## 総合
1〜5 全PASS。同日の初版検証（`qa_report_20260913.md`）はNode実走・localStorage壊れ値を別スキームで検証済みだったが、qa_check.py単体にはその2項目が内蔵されていない点を今回embed一致とあわせて独立に確認した。

## 未検証（範囲外）
実機（スマホでのタップ操作・光り方の見え方）は担当外。

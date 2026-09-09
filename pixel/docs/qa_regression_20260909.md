担当: 🧪 qa係

# ピクセル 再検証（2026-09-09）

## 結果: PASS

## 1. 既存 qa_check.py / qa_indep.py
- `qa_check.py`: 60問全問 `[OK] 一意解確認完了`、`ALL 60 PASSED`
- `qa_indep.py`: 40問(入門〜上級)の周回数を出す網羅出力、加えて末尾に41〜60（特級/達人/名画）のiterationsも出力。
  「逆転（前段階より簡単な問題が上位段に混在）」チェック: **該当なし**（平均周回数は段階順に単調非減少: 入門2.60→初級2.80→中級3.50→上級4.40）。
  ※既知の罠（[[project_pixel_traps]]「上級が全問iter=3で最も浅い」逆転）はこの版では再発していない。

## 2. index.html 埋め込み vs tools/puzzles.json
tools配下に puzzles_v1〜v4.json とバージョン違いが複数存在（md5:
puzzles.json=279519e6..., puzzles_v3.json(50問)=f997f128..., puzzles_v4.json(60問)=790ea1ee...）。
`tools/puzzles.json`（60問）が現行版で、**index.html埋め込み60問とdeep equal一致**。
古いv1〜v3は使われていない旧版として残置（実害なし、次回棚卸し候補）。

## 3. 公開オブジェクト（window.Pixel）の検証関数
1本の`<script>`から `window.Pixel = Pixel;` までをロジック部として切り出しvm実行。
`Pixel.isSolution(p, state)`を60問で実行:
- 正解state → 全問 `true`
- 1マス反転した誤りstate → 全問 `false`（誤判定なし）
FAIL 0件。

## 4. localStorage 壊れ値
保存キー名: `pixel-v2`
1本の`<script>`（ロジック+画面制御が同一ファイル）をvm実行、9パターン全部 OK（未捕捉例外なし）。
`loadSave()`が`Number.isInteger`で小数・型不正を弾く。

## 5. photo.html / photo-color.html の入口露出
`index.html`（本体・puzzle-portal直下）から `pixel/photo.html` `pixel/photo-color.html` へのリンクは無し。
リポジトリ内でこの2ファイルを参照しているのは `pixel/docs/qa_report_photo_20260908.md` `pixel/docs/spec_photo.md`
`pixel/docs/spec_photo_color.md` の3ドキュメントのみ（HTMLからの導線ゼロ）。畳んだ実験として想定通り。

## 6. pixel/art/ と docs/artworks.json の突合
art/ 10ファイル ⇔ artworks.json 10件、id集合が完全一致（過不足なし）。
`is_public_domain` は10件全て `true`。

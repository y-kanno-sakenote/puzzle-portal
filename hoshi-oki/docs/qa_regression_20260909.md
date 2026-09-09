担当: 🧪 qa係

# 星おき 再検証（2026-09-09）

## 結果: PASS

## 1. 既存 qa_check.py
```
0. index.html と puzzles.json の一致: PASS 完全一致(40本)
1. 独立ソルバーで一意性再検証: PASS 40/40 一意解、独立ソルバーの解がsolutionと一致
2. 盤面妥当性（領域/連結/★配置/隣接）: PASS 40/40 妥当
3. 難度実態（自前簡易論理ソルバー）: 入門10/10・初級10/10が論理のみで解け、
   中級0/10・上級0/10はバックトラックが必要（申告nodes>0と整合）→ FAILではなく設計通り
```

## 2. index.html 埋め込み vs tools/puzzles.json
40問 deep equal。

## 3. 公開オブジェクト（window.HoshiOki）の検証関数
Node vm で1本目の`<script>`を実走し、`HoshiOki.countSolutions(p, 2)`を40問で実行。
全問 `1`。FAIL 0件。

## 4. localStorage 壊れ値
保存キー名: `hoshi-oki`
2本の`<script>`を連結してvm実行、9パターン全部 OK（未捕捉例外なし）。
`loadSave()`が`Number.isInteger`で小数・型不正を弾く。

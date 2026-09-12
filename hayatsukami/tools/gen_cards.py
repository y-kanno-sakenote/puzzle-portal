#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""はやつかみ 札の生成器（Python3 標準ライブラリのみ）

    python3 gen_cards.py                      # 生成して JSON を標準出力へ
    python3 gen_cards.py --out cards.json     # JSON に書き出す
    python3 gen_cards.py --embed ../index.html  # CARDS-BEGIN/END の間だけ差し替え
    python3 gen_cards.py --seed 123
    python3 gen_cards.py --stats              # 内訳だけ表示する

手順（docs/spec.md）
  1. 25 通りの絵柄（形5 × 色5）から2つ選ぶ組み合わせを全部作る
  2. 形が重複する札・色が重複する札を捨てる
  3. 正解の決まりで正解を求め、**ちょうど1つに定まる札だけ**採用する
       種類1（一致あり）: 形と色が本来の組み合わせと一致する絵柄が1つ → その品
       種類2（一致なし）: 形としても色としても出ていない品が1つ残る → その品
     一致が2つある札（v0.1 では使わない）と、残りが0個や2個以上になる札は捨てる
  4. 種を固定して並べ替える（出る順だけが乱数。札そのものは数え上げなので毎回同じ）
"""

import argparse
import itertools
import json
import random
import re
import sys

# 品は5つ。形と色が1対1
SHAPES = ["ハート", "しずく", "ほし", "はっぱ", "つき"]
COLORS = ["赤", "青", "黄", "緑", "黒"]
TRUE = dict(zip(SHAPES, COLORS))              # 形 -> 本来の色
OWNER = {c: s for s, c in TRUE.items()}       # 色 -> その色を本来持つ形


def answer_of(a, b):
    """札（絵柄2つ）の正解を返す。定まらない札は None。

    戻り値 (正解の形, 種類)。種類1=一致あり / 種類2=一致なし。
    """
    s1, c1 = a
    s2, c2 = b
    if s1 not in TRUE or s2 not in TRUE:
        return None
    if c1 not in OWNER or c2 not in OWNER:
        return None
    if s1 == s2:                                   # 形の重複
        return None
    if c1 == c2:                                   # 色の重複
        return None
    hit = [s for s, c in (a, b) if TRUE[s] == c]
    if len(hit) == 2:                              # 一致が2つ（上級札。v0.1 では使わない）
        return None
    if len(hit) == 1:
        return (hit[0], 1)
    used = {s1, s2, OWNER[c1], OWNER[c2]}          # 形として出た品 ∪ 色として出た品
    rest = [s for s in SHAPES if s not in used]
    if len(rest) != 1:                             # 正解が0個または2個以上＝定まらない
        return None
    return (rest[0], 2)


def build():
    """全パターンを数え上げて、正解が1つに定まる札だけ返す。内訳も返す"""
    motifs = [(s, c) for s in SHAPES for c in COLORS]
    cards = []
    tally = {"組み合わせ総数": 0, "形の重複": 0, "色の重複": 0,
             "一致2つ": 0, "正解が定まらない": 0, "種類1": 0, "種類2": 0}
    for a, b in itertools.combinations(motifs, 2):
        tally["組み合わせ総数"] += 1
        if a[0] == b[0]:
            tally["形の重複"] += 1
            continue
        if a[1] == b[1]:
            tally["色の重複"] += 1
            continue
        got = answer_of(a, b)
        if got is None:
            hit = [s for s, c in (a, b) if TRUE[s] == c]
            tally["一致2つ" if len(hit) == 2 else "正解が定まらない"] += 1
            continue
        ans, kind = got
        tally["種類1" if kind == 1 else "種類2"] += 1
        cards.append({"a": [a[0], a[1]], "b": [b[0], b[1]], "answer": ans, "kind": kind})
    return cards, tally


def verify(cards):
    """採用した札を機械で点検する。1枚でも怪しければ止める"""
    seen = set()
    for c in cards:
        a, b = tuple(c["a"]), tuple(c["b"])
        key = tuple(sorted([a, b]))
        if key in seen:
            raise SystemExit("同じ札が2度出た: %r" % (key,))
        seen.add(key)
        got = answer_of(a, b)
        if got is None:
            raise SystemExit("正解が定まらない札が混ざった: %r" % (c,))
        if got[0] != c["answer"] or got[1] != c["kind"]:
            raise SystemExit("正解が食い違う札: %r != %r" % (c, got))
        if a[0] == b[0] or a[1] == b[1]:
            raise SystemExit("形か色が重複した札: %r" % (c,))
    return len(cards)


def embed(path, cards):
    lines = ["var CARDS = ["]
    for k, c in enumerate(cards):
        lines.append('{"a":["%s","%s"],"b":["%s","%s"],"answer":"%s","kind":%d}%s'
                     % (c["a"][0], c["a"][1], c["b"][0], c["b"][1],
                        c["answer"], c["kind"], "," if k < len(cards) - 1 else ""))
    lines.append("];")
    body = "\n".join(lines)
    src = open(path, encoding="utf-8").read()
    pat = re.compile(r"(/\* CARDS-BEGIN[^\n]*\*/\n).*?(\n/\* CARDS-END \*/)", re.S)
    if not pat.search(src):
        raise SystemExit("CARDS-BEGIN / CARDS-END が見つからない: " + path)
    src = pat.sub(lambda m: m.group(1) + body + m.group(2), src)
    open(path, "w", encoding="utf-8").write(src)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260913, help="並べ替えの種")
    ap.add_argument("--out", default=None, help="JSON の書き出し先")
    ap.add_argument("--embed", default=None, help="index.html の CARDS-BEGIN/END を差し替える")
    ap.add_argument("--stats", action="store_true", help="内訳だけ表示する")
    a = ap.parse_args()

    cards, tally = build()
    verify(cards)
    random.Random(a.seed).shuffle(cards)

    k1 = sum(1 for c in cards if c["kind"] == 1)
    k2 = len(cards) - k1
    sys.stderr.write(
        "札 %d 枚（種類1=%d / 種類2=%d）　"
        "数え上げ %d 通り → 形の重複 %d・色の重複 %d・一致2つ %d・正解が定まらない %d を除外\n"
        % (len(cards), k1, k2, tally["組み合わせ総数"], tally["形の重複"],
           tally["色の重複"], tally["一致2つ"], tally["正解が定まらない"]))
    if a.stats:
        return

    text = json.dumps(cards, ensure_ascii=False, separators=(",", ":"))
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text + "\n")
    if a.embed:
        embed(a.embed, cards)
    if not a.out and not a.embed:
        sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()

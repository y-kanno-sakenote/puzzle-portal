#!/usr/bin/env python3
# 担当: qa係 独立検証スクリプト（既存 qa_check.py は読まずに独自実装）
import json, re, sys
from itertools import product

UNK, BLACK, WHITE = -1, 1, 0

def gen_arrangements(hints, length):
    """hints (e.g. [3,1] or [0]) に一致する 0/1 配列を全列挙"""
    if hints == [0]:
        return [tuple([0]*length)]
    blocks = hints
    n = len(blocks)
    total_block = sum(blocks)
    slack = length - total_block - (n - 1)
    if slack < 0:
        return []
    results = []
    # gaps: g0 (before block0, >=0), g1..g(n-1) (between blocks, >=1), gn (after last, >=0)
    def rec(i, pos, arr):
        if i == n:
            results.append(tuple(arr + [0]*(length-pos)))
            return
        max_extra = slack - (sum_extra[i] if False else 0)
        # try all extra gap amounts 0..slack_remaining at this point
        for extra in range(0, slack_remaining[i]+1):
            gap = (1 if i > 0 else 0) + extra
            p2 = pos + gap
            newarr = arr + [0]*gap + [1]*blocks[i]
            rec_helper(i+1, p2+blocks[i], newarr, slack_remaining[i]-extra)
    # simpler iterative approach using recursive generator with remaining slack budget
    def rec2(i, pos, arr, budget):
        if i == n:
            results.append(tuple(arr + [0]*(length-pos)))
            return
        min_gap = 1 if i > 0 else 0
        for extra in range(0, budget+1):
            gap = min_gap + extra
            newpos = pos + gap
            newarr = arr + [0]*gap + [1]*blocks[i]
            rec2(i+1, newpos+blocks[i], newarr, budget-extra)
    rec2(0, 0, [], slack)
    return results

def line_forced(hints, length, known):
    """known: list of UNK/BLACK/WHITE (len=length). 制約に合う全配置を求め、
    全配置で共通する値を確定値として返す（それ以外はUNK）。"""
    arrs = gen_arrangements(hints, length)
    valid = []
    for a in arrs:
        ok = True
        for i in range(length):
            if known[i] != UNK and known[i] != a[i]:
                ok = False
                break
        if ok:
            valid.append(a)
    if not valid:
        return None, 0  # 矛盾（バグの兆候）
    forced = list(known)
    for i in range(length):
        vals = set(a[i] for a in valid)
        if len(vals) == 1:
            forced[i] = vals.pop()
    return forced, len(valid)

def solve_puzzle(p):
    w, h = p['w'], p['h']
    grid = [[UNK]*w for _ in range(h)]
    iterations = 0
    stall = False
    history = []  # per-iteration: cells confirmed this pass
    while True:
        iterations += 1
        changed_cells = 0
        # rows
        for r in range(h):
            row = grid[r]
            forced, nvalid = line_forced(p['rowHints'][r], w, row)
            if forced is None:
                return {'ok': False, 'reason': f'row {r} contradiction', 'iterations': iterations}
            for c in range(w):
                if forced[c] != UNK and grid[r][c] == UNK:
                    grid[r][c] = forced[c]
                    changed_cells += 1
        # cols
        for c in range(w):
            col = [grid[r][c] for r in range(h)]
            forced, nvalid = line_forced(p['colHints'][c], h, col)
            if forced is None:
                return {'ok': False, 'reason': f'col {c} contradiction', 'iterations': iterations}
            for r in range(h):
                if forced[r] != UNK and grid[r][c] == UNK:
                    grid[r][c] = forced[r]
                    changed_cells += 1
        history.append(changed_cells)
        if changed_cells == 0:
            break
    total = w*h
    filled_unk = sum(1 for r in range(h) for c in range(w) if grid[r][c] == UNK)
    solved_by_lines = (filled_unk == 0)
    # 一致確認
    matches = None
    if solved_by_lines:
        flat = ''.join(str(grid[r][c]) for r in range(h) for c in range(w))
        matches = (flat == p['solution'])
    return {
        'ok': True,
        'solved_by_lines': solved_by_lines,
        'iterations': iterations,
        'history': history,
        'unresolved_cells': filled_unk,
        'matches_solution': matches,
        'grid': grid,
    }

def check_hint_consistency(p):
    """solution から実際に導出されるヒントと puzzle 記載のヒントが一致するか"""
    w, h = p['w'], p['h']
    sol = p['solution']
    def hints_of(bits):
        blocks = []
        cur = 0
        for b in bits:
            if b == '1':
                cur += 1
            else:
                if cur:
                    blocks.append(cur)
                cur = 0
        if cur:
            blocks.append(cur)
        return blocks if blocks else [0]
    row_ok = True
    for r in range(h):
        row_bits = sol[r*w:(r+1)*w]
        if hints_of(row_bits) != p['rowHints'][r]:
            row_ok = False
    col_ok = True
    for c in range(w):
        col_bits = ''.join(sol[r*w+c] for r in range(h))
        if hints_of(col_bits) != p['colHints'][c]:
            col_ok = False
    return row_ok, col_ok

def main():
    html_path = sys.argv[1] if len(sys.argv) > 1 else 'index.html'
    html = open(html_path, encoding='utf-8').read()
    m = re.search(r'var PUZZLES = (\[.*?\]);', html, re.S)
    puzzles = json.loads(m.group(1))

    print(f"puzzles: {len(puzzles)}")
    fail_guess_needed = []
    fail_mismatch = []
    fail_hint = []
    fail_len = []
    tier_stats = []  # (no, title, tier, iterations, first_pass_ratio)

    gallery_lines = []

    for p in puzzles:
        w, h = p['w'], p['h']
        if len(p['solution']) != w*h:
            fail_len.append(p['no'])
        row_ok, col_ok = check_hint_consistency(p)
        if not (row_ok and col_ok):
            fail_hint.append((p['no'], p['title'], 'row' if not row_ok else '', 'col' if not col_ok else ''))

        res = solve_puzzle(p)
        if not res['ok']:
            fail_guess_needed.append((p['no'], p['title'], res['reason']))
            continue
        if not res['solved_by_lines']:
            fail_guess_needed.append((p['no'], p['title'], f"unresolved={res['unresolved_cells']}"))
        elif res['matches_solution'] is False:
            fail_mismatch.append((p['no'], p['title']))

        first_pass = res['history'][0] if res['history'] else 0
        total = w*h
        tier_stats.append({
            'no': p['no'], 'title': p['title'], 'tier': p['tier'],
            'iterations': res['iterations'],
            'first_pass_ratio': round(first_pass/total, 3) if total else 0,
            'history': res['history'],
        })

        # gallery
        sol = p['solution']
        art = '\n'.join(sol[r*w:(r+1)*w].replace('1','#').replace('0','.') for r in range(h))
        fill_rate = sol.count('1') / len(sol)
        gallery_lines.append(f"[{p['no']:02d}] {p['title']} ({p['tier']} {w}x{h}) 塗り率={fill_rate:.0%}\n{art}\n")

    print("\n=== 1. 自前ラインソルバーで解けたか ===")
    if fail_guess_needed:
        print(f"FAIL: 仮定が必要な問題 {len(fail_guess_needed)}件: {fail_guess_needed}")
    else:
        print("PASS: 40問全てラインソルバー(仮定なし)のみで解ける")

    print("\n=== 1b. 解の一致 ===")
    if fail_mismatch:
        print(f"FAIL: solution不一致 {fail_mismatch}")
    else:
        print("PASS: 解けた問題は全てsolutionと一致")

    print("\n=== 1c. ヒントとsolutionの整合 ===")
    if fail_hint:
        print(f"FAIL: {fail_hint}")
    else:
        print("PASS: 全問でヒントがsolutionから機械的に再導出できる")

    print("\n=== 1d. solution長 ===")
    if fail_len:
        print(f"FAIL: w*hと不一致 {fail_len}")
    else:
        print("PASS: 全問solution長 == w*h")

    print("\n=== 2. 難度の実態（周回数と初手確定率） ===")
    tier_order = {'入門':0, '初級':1, '中級':2, '上級':3}
    for t in tier_stats:
        print(f"no{t['no']:02d} {t['tier']:2s} {t['title']:10s} iter={t['iterations']:2d} history={t['history']}")

    # 段階平均の単調性チェック（周回数の平均で比較）
    from collections import defaultdict
    agg = defaultdict(list)
    for t in tier_stats:
        agg[t['tier']].append(t['iterations'])
    print("\n段階別 平均周回数:")
    for tier in ['入門','初級','中級','上級']:
        vals = agg[tier]
        print(f"  {tier}: 平均{sum(vals)/len(vals):.2f} 範囲{min(vals)}-{max(vals)} 個別{vals}")

    # 逆転検出: tier順で並べたとき、iterationsが単調非減少でない箇所
    print("\n逆転（前段階より明らかに簡単な問題が上位段に混在）:")
    prev_tier_max = 0
    tiers_seq = ['入門','初級','中級','上級']
    inversions = []
    for i, tier in enumerate(tiers_seq):
        vals = agg[tier]
        avg = sum(vals)/len(vals)
        if i > 0:
            prev_avg = sum(agg[tiers_seq[i-1]])/len(agg[tiers_seq[i-1]])
            if avg < prev_avg:
                inversions.append((tiers_seq[i-1], prev_avg, tier, avg))
    if inversions:
        for a,av,b,bv in inversions:
            print(f"  FAIL候補: {a}(平均{av:.2f}) > {b}(平均{bv:.2f})")
    else:
        print("  平均周回数は段階順に単調非減少")

    # 個別問題で「別tierの中央値より簡単」な外れ値を index付きで
    print("\n個別の逆転候補 index（iterationsが自分のtierの前段tier最大値以下）:")
    for i, tier in enumerate(tiers_seq):
        if i == 0: continue
        prev_max = max(agg[tiers_seq[i-1]])
        for t in tier_stats:
            if t['tier'] == tier and t['iterations'] <= 1:
                print(f"  no{t['no']} {t['title']} ({tier}) iter={t['iterations']} は前段{tiers_seq[i-1]}の最大iter={prev_max}以下")

    print("\n=== 3. gallery出力 ===")
    out_path = sys.argv[2] if len(sys.argv) > 2 else 'pixel_gallery.txt'
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(gallery_lines))
    print(f"書き出し: {out_path}")

if __name__ == '__main__':
    main()

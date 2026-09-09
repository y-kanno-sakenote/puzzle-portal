# -*- coding: utf-8 -*-
"""名画（パブリックドメイン）の取得と台帳更新

    python3 tools/fetch_art.py search <検索語> [件数]   … 候補を一覧表示（PDのみ）
    python3 tools/fetch_art.py add <id> [<id> ...]      … 画像を art/ に保存し台帳へ追記

シカゴ美術館 API（キー不要・AIC-User-Agent ヘッダが要る）。標準ライブラリのみ。
is_public_domain: true のものだけ採る。既にある id は取り直さない。
"""
import json
import sys
import urllib.request
import urllib.parse
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART_DIR = ROOT / "art"
LEDGER = ROOT / "docs" / "artworks.json"

UA = "Mozilla/5.0"
AIC_UA = "sakenote-puzzle (y.kanno@sakenote.net)"
FIELDS = "id,title,artist_title,artist_display,date_display,is_public_domain,image_id,department_title,place_of_origin,medium_display,credit_line"
WIDTHS = [600, 500, 420, 360, 300, 260]
MAX_BYTES = 150 * 1024


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "AIC-User-Agent": AIC_UA})
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read()


def api(path, params):
    url = "https://api.artic.edu/api/v1/" + path + "?" + urllib.parse.urlencode(params)
    return json.loads(_get(url).decode("utf-8"))


def load_ledger():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return []


def save_ledger(rows):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_search(query, limit=20):
    data = api("artworks/search", {"q": query, "limit": limit, "fields": FIELDS})
    for d in data.get("data", []):
        pd = d.get("is_public_domain")
        img = d.get("image_id")
        if not pd or not img:
            continue
        print(
            f"{d['id']}\tPD={pd}\t{d.get('artist_title')}\t{d.get('title')}\t"
            f"{d.get('date_display')}\t{d.get('department_title')}"
        )


def cmd_add(ids):
    ART_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_ledger()
    have = {r["id"] for r in rows}
    today = date.today().isoformat()

    for aid in ids:
        key = f"aic-{aid}"
        if key in have:
            print(f"skip {key} (台帳にあり)")
            continue
        d = api(f"artworks/{aid}", {"fields": FIELDS})["data"]
        if not d.get("is_public_domain"):
            print(f"SKIP {aid}: is_public_domain={d.get('is_public_domain')} → 採らない")
            continue
        image_id = d.get("image_id")
        if not image_id:
            print(f"SKIP {aid}: image_id が無い")
            continue

        blob = None
        used_w = None
        for w in WIDTHS:
            url = f"https://www.artic.edu/iiif/2/{image_id}/full/{w},/0/default.jpg"
            blob = _get(url)
            used_w = w
            if len(blob) <= MAX_BYTES:
                break
        path = ART_DIR / f"{key}.jpg"
        path.write_bytes(blob)

        rows.append(
            {
                "id": key,
                "institution": "Art Institute of Chicago",
                "holder": "シカゴ美術館",
                "title": d.get("title"),
                "artist": d.get("artist_title"),
                "artist_display": d.get("artist_display"),
                "date": d.get("date_display"),
                "medium": d.get("medium_display"),
                "credit_line": d.get("credit_line"),
                "license": "Public Domain (CC0)",
                "is_public_domain": d.get("is_public_domain"),
                "image_id": image_id,
                "source": f"https://www.artic.edu/artworks/{aid}",
                "api": f"https://api.artic.edu/api/v1/artworks/{aid}",
                "file": f"art/{key}.jpg",
                "image_width": used_w,
                "bytes": len(blob),
                "fetched": today,
            }
        )
        have.add(key)
        print(f"got {key} w={used_w} {len(blob)//1024}KB  {d.get('artist_title')} / {d.get('title')}")

    save_ledger(rows)
    print(f"台帳 {LEDGER} に {len(rows)} 件")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "search":
        cmd_search(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 20)
    elif cmd == "add":
        cmd_add(sys.argv[2:])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

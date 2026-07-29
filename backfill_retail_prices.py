#!/usr/bin/env python3
"""
One-off backfill: look up a retail price (hobby.am / hobbygames.am) for every
existing BGG entry that doesn't have one yet. New entries get this
automatically via auto_add.py going forward — this script is only for the
catalog titles that predate that feature.

Usage:
  python backfill_retail_prices.py [--limit N] [--dry-run]
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).parent
HTML = ROOT / "index.html"

from retail_lookup import lookup_retail_price


def load_bgg(src):
    m = re.search(r'const BGG=(\{.*?\});', src, re.DOTALL)
    return json.loads(m.group(1)), m


def save_bgg(src, m, bgg):
    new_bgg = json.dumps(bgg, ensure_ascii=False, separators=(',', ':'))
    out = src[:m.start(1)] + new_bgg + src[m.end(1):]
    HTML.write_text(out, encoding='utf-8')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--limit', type=int, default=None)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()

    from curl_cffi import requests as cffi_requests
    session = cffi_requests.Session(impersonate="chrome131")

    src = HTML.read_text(encoding='utf-8')
    bgg, m = load_bgg(src)

    todo = [title for title, data in bgg.items() if 'retail_price' not in data]
    print(f"BGG entries: {len(bgg)}, missing retail price: {len(todo)}")
    if args.limit:
        todo = todo[:args.limit]
        print(f"Limited to {len(todo)} for this run")

    found, not_found = 0, 0
    for i, title in enumerate(todo):
        result = lookup_retail_price(session, title)
        if result:
            found += 1
            print(f"[{i+1}/{len(todo)}] {title} -> {result['price']} ֏ "
                  f"({result['source']}, "
                  f"{'in stock' if result['in_stock'] else 'sold out' if result['in_stock'] is False else 'unknown'})")
            if not args.dry_run:
                bgg[title]['retail_price'] = result['price']
                bgg[title]['retail_url'] = result['url']
                bgg[title]['retail_source'] = result['source']
                bgg[title]['retail_in_stock'] = result['in_stock']
        else:
            not_found += 1
            print(f"[{i+1}/{len(todo)}] {title} -> not found")

        if not args.dry_run and (i + 1) % 5 == 0:
            save_bgg(src, m, bgg)
            print(f"  (saved progress: {i+1}/{len(todo)})")

        time.sleep(1.5)  # be polite to the retailers' servers

    if not args.dry_run:
        save_bgg(src, m, bgg)

    print(f"\n=== Done: found={found}, not_found={not_found} ===")
    if args.dry_run:
        print("DRY-RUN: index.html not modified")


if __name__ == '__main__':
    main()

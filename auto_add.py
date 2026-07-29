#!/usr/bin/env python3
"""
Auto-add or update a game listing from Telegram message.
Called by GitHub Actions with parsed data from Make.

Usage:
  python auto_add.py \
    --title "Spirit Island" \
    --price 25000 \
    --lang ENG \
    --msg_id 5123 \
    --seller "username" \
    --note "Complete, all promos"
"""
import argparse, json, re, io, time, sys, difflib, urllib.parse, html as html_module
from pathlib import Path
from datetime import date

sys.stdout.reconfigure(encoding='utf-8')
ROOT   = Path(__file__).parent
HTML   = ROOT / "index.html"
COVERS = ROOT / "covers"
BLACKLIST_FILE = ROOT / "blacklist.json"

# ── Retail price lookup (hobby.am / hobbygames.am) ─────────────────────────────
def _normalize_title(t):
    t = re.sub(r'\s*\([^)]*\)\s*$', '', t)  # drop trailing "(Eng)"/"(РУС)" etc.
    return t.strip().lower()

def _parse_hobbyam(src):
    results = []
    for block in re.split(r'(?=<div class="wd-product )', src)[1:]:
        m_link = re.search(r'<a href="(https://hobby\.am/product/[^"]+)">([^<]+)</a>', block)
        m_price = re.search(r'<bdi>(\d+)', block)
        if not m_link or not m_price:
            continue
        results.append({
            'url': m_link.group(1),
            'name': html_module.unescape(m_link.group(2)),
            'price': int(m_price.group(1)),
            'in_stock': 'outofstock' not in block[:800],
        })
    return results

def _parse_hobbygames(src):
    results = []
    pattern = re.compile(
        r'<div class="product-card\s[^"]*"[^>]*data-price="(\d+)"[^>]*data-category="[^"]*"[^>]*>'
        r'.*?href="(/[^"]+)"[^>]*class="product-card__image.*?data-product-name="([^"]*)"',
        re.DOTALL)
    for m in pattern.finditer(src):
        price, url, name = m.groups()
        results.append({
            'url': 'https://hobbygames.am' + url,
            'name': html_module.unescape(name),
            'price': int(price),
            'in_stock': None,  # not exposed in search results markup
        })
    return results

def _best_retail_match(title, candidates):
    # Deliberately conservative: retailer catalogs contain many expansions/
    # accessories/localized-name variants of the same brand (e.g. dozens of
    # "Catan ..." products), so a generous fuzzy match risks confidently
    # showing the price of the WRONG product. Prefer no match over a wrong one.
    target = _normalize_title(title)
    scored = []
    for c in candidates:
        cname = _normalize_title(c['name'])
        ratio = 1.0 if cname == target else difflib.SequenceMatcher(None, target, cname).ratio()
        scored.append((ratio, -len(cname), c))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best_ratio, _, best = scored[0]
    return best if best_ratio >= 0.85 else None

def lookup_retail_price(session, title):
    sources = [
        ('hobby.am', f'https://hobby.am/?s={urllib.parse.quote(title)}&post_type=product', _parse_hobbyam),
        ('hobbygames.am', f'https://hobbygames.am/catalog/search?keyword={urllib.parse.quote(title)}', _parse_hobbygames),
    ]
    for source, url, parser in sources:
        try:
            r = session.get(url, headers={'Accept-Language': 'ru,en'}, timeout=10)
            if r.status_code != 200:
                continue
            match = _best_retail_match(title, parser(r.text))
            if match:
                return {'price': match['price'], 'url': match['url'],
                        'source': source, 'in_stock': match['in_stock']}
        except Exception as e:
            print(f"{source} retail lookup failed: {e}")
    return None

# ── Args ───────────────────────────────────────────────────────────────────────
p = argparse.ArgumentParser()
p.add_argument('--title',  required=True)
p.add_argument('--price',  type=int, default=None)
p.add_argument('--lang',   default='ENG')
p.add_argument('--msg_id', type=int, required=True)
p.add_argument('--seller', default='')
p.add_argument('--note',   default='')
p.add_argument('--exchange', action='store_true')
args = p.parse_args()

# ── Blacklist ─────────────────────────────────────────────────────────────────
blacklist = json.loads(BLACKLIST_FILE.read_text(encoding='utf-8'))
seller_lower = args.seller.lower().lstrip('@')
for blocked in blacklist:
    if seller_lower == blocked.lower().lstrip('@'):
        print(f"BLOCKED: seller '{args.seller}' is in blacklist")
        sys.exit(0)

# ── Load HTML ─────────────────────────────────────────────────────────────────
src = HTML.read_text(encoding='utf-8')
bgg_m = re.search(r'const BGG=(\{.*?\});', src, re.DOTALL)
d_m   = re.search(r'const D=(\[.*?\]);',   src, re.DOTALL)
BGG = json.loads(bgg_m.group(1))
D   = json.loads(d_m.group(1))

today = date.today().strftime('%d.%m.%Y')

# ── Deduplication: update existing listing if same title + seller ──────────────
for item in D:
    same_title  = item['t'].lower() == args.title.lower()
    same_seller = item.get('s','').lower().lstrip('@') == seller_lower
    if same_title and (same_seller or not args.seller):
        # Update price, date, msg_id, note if changed
        changed = []
        if args.price and item.get('p') != args.price:
            item['p'] = args.price; changed.append('price')
        if item.get('m') != args.msg_id:
            item['m'] = args.msg_id; changed.append('msg_id')
        if args.note and item.get('n') != args.note:
            item['n'] = args.note; changed.append('note')
        item['d'] = today
        if args.exchange:
            item['x'] = True
        print(f"UPDATED '{args.title}': {', '.join(changed) or 'date only'}")
        _updated = True
        break
else:
    _updated = False

if _updated:
    pass  # skip BGG lookup, just save
else:
    # ── New listing: look up BGG + download cover ──────────────────────────────
    print(f"NEW listing: '{args.title}'")

    try:
        from curl_cffi import requests as cffi_requests
        from PIL import Image
        session = cffi_requests.Session(impersonate="chrome131")
    except ImportError:
        session = None

    bgg_id   = None
    bgg_data = {}

    # BGG search
    if session:
        try:
            r = session.get(
                'https://boardgamegeek.com/xmlapi2/search',
                params={'query': args.title, 'type': 'boardgame', 'exact': 1},
                timeout=10)
            m = re.search(r'<item.*?id="(\d+)"', r.text)
            if not m:  # try non-exact
                r = session.get(
                    'https://boardgamegeek.com/xmlapi2/search',
                    params={'query': args.title, 'type': 'boardgame'},
                    timeout=10)
                m = re.search(r'<item.*?id="(\d+)"', r.text)
            if m:
                bgg_id = int(m.group(1))
                # Fetch details
                r2 = session.get(
                    f'https://boardgamegeek.com/xmlapi2/thing',
                    params={'id': bgg_id, 'stats': 1},
                    timeout=10)
                t2 = r2.text
                rating_m  = re.search(r'<average value="([\d.]+)"', t2)
                minp_m    = re.search(r'minplayers value="(\d+)"', t2)
                maxp_m    = re.search(r'maxplayers value="(\d+)"', t2)
                mint_m    = re.search(r'minplaytime value="(\d+)"', t2)
                maxt_m    = re.search(r'maxplaytime value="(\d+)"', t2)
                img_m     = re.search(r'<image>(.*?)</image>', t2)
                cats      = re.findall(r'boardgamecategory[^>]+value="([^"]+)"', t2)
                bgg_data = {
                    'bgg_id':      bgg_id,
                    'bgg_name':    args.title,
                    'rating':      round(float(rating_m.group(1)), 1) if rating_m else None,
                    'min_players': int(minp_m.group(1)) if minp_m else None,
                    'max_players': int(maxp_m.group(1)) if maxp_m else None,
                    'min_playtime':int(mint_m.group(1)) if mint_m else None,
                    'max_playtime':int(maxt_m.group(1)) if maxt_m else None,
                    'categories':  cats[:3],
                    'image':       img_m.group(1).strip() if img_m else '',
                    'bgg_url':     f'https://boardgamegeek.com/boardgame/{bgg_id}',
                }
                print(f"BGG found: {bgg_id}, rating={bgg_data.get('rating')}")
        except Exception as e:
            print(f"BGG lookup failed: {e}")

    # Add to BGG if not present
    if args.title not in BGG and bgg_data:
        BGG[args.title] = bgg_data
        print(f"BGG entry added: {args.title}")
    elif args.title not in BGG:
        BGG[args.title] = {
            'bgg_id': bgg_id or 0, 'bgg_name': args.title,
            'rating': None, 'min_players': None, 'max_players': None,
            'min_playtime': None, 'max_playtime': None,
            'categories': [], 'image': '', 'bgg_url': ''
        }

    # Retail price lookup (best-effort, cached once per game)
    if session:
        retail = lookup_retail_price(session, args.title)
        if retail:
            BGG[args.title]['retail_price'] = retail['price']
            BGG[args.title]['retail_url'] = retail['url']
            BGG[args.title]['retail_source'] = retail['source']
            BGG[args.title]['retail_in_stock'] = retail['in_stock']
            stock_txt = {True: 'in stock', False: 'sold out', None: 'stock unknown'}[retail['in_stock']]
            print(f"Retail price: {retail['price']} ֏ ({retail['source']}, {stock_txt})")
        else:
            print("Retail price: not found")

    # Download cover
    if session and bgg_id:
        bgg_slug = args.title.lower().replace(' ','-').replace(':','').replace("'",'')
        cover_saved = False

        # Try Tesera first
        try:
            r = session.get(f'https://tesera.ru/game/{bgg_slug}/',
                            headers={'Accept-Language':'ru,en'}, timeout=10)
            og = re.search(r'og:image["\s]+content="([^"]+)"', r.text)
            if og and 'p404' not in r.url:
                url = og.group(1).replace('200x200xpa','600x600xpa').replace('200x200','600x600')
                r2 = session.get(url, timeout=10)
                if r2.status_code == 200 and len(r2.content) > 5000:
                    img = Image.open(io.BytesIO(r2.content)).convert('RGB')
                    img.thumbnail((300,300), Image.LANCZOS)
                    img.save(COVERS / f'{bgg_id}.webp', 'WEBP', quality=82)
                    cover_saved = True
                    print(f"Cover: Tesera OK")
        except Exception as e:
            print(f"Tesera failed: {e}")

        # Fallback: Yandex
        if not cover_saved:
            try:
                SKIP = ('instagram','facebook','twitter','vk.com','pinterest','tiktok','amazon','ebay')
                r = session.get('https://yandex.ru/images/search',
                    params={'text': f'{args.title} board game box'},
                    headers={'Accept-Language':'ru-RU,ru;q=0.9,en;q=0.8'}, timeout=15)
                matches = re.findall(r'&quot;origUrl&quot;:&quot;(https?://[^&]+)&quot;', r.text)
                for raw in matches[:10]:
                    url = html_module.unescape(raw)
                    if any(d in url for d in SKIP): continue
                    r2 = session.get(url, timeout=10)
                    if r2.status_code == 200 and len(r2.content) >= 10000:
                        img = Image.open(io.BytesIO(r2.content)).convert('RGB')
                        if max(img.size)/min(img.size) < 2.5:
                            img.thumbnail((300,300), Image.LANCZOS)
                            img.save(COVERS / f'{bgg_id}.webp', 'WEBP', quality=82)
                            cover_saved = True
                            print(f"Cover: Yandex OK")
                            break
            except Exception as e:
                print(f"Yandex failed: {e}")

    # Add D listing
    new_entry = {
        't': args.title,
        's': args.seller,
        'p': args.price,
        'l': args.lang,
        'n': args.note,
        'd': today,
        'm': args.msg_id,
    }
    if args.exchange:
        new_entry['x'] = True
    D.append(new_entry)
    print(f"D entry added: {args.title} — {args.price} ֏ ({args.lang})")

# ── Save HTML ─────────────────────────────────────────────────────────────────
new_bgg = json.dumps(BGG, ensure_ascii=False, separators=(',',':'))
new_d   = json.dumps(D,   ensure_ascii=False, separators=(',',':'))
out = src[:bgg_m.start(1)] + new_bgg + src[bgg_m.end(1):]
d2  = re.search(r'const D=(\[.*?\]);', out, re.DOTALL)
out = out[:d2.start(1)] + new_d + out[d2.end(1):]
HTML.write_text(out, encoding='utf-8')
print(f"Saved. BGG={len(BGG)}, D={len(D)}")

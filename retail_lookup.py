"""
Best-effort retail price lookup on hobby.am / hobbygames.am, shared by
auto_add.py (single new game) and backfill_retail_prices.py (bulk backfill).

Usage:
  from retail_lookup import lookup_retail_price
  result = lookup_retail_price(session, "Spirit Island")
  # -> {'price': 48900, 'url': '...', 'source': 'hobby.am', 'in_stock': True} or None
"""
import re
import difflib
import urllib.parse
import html as html_module


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

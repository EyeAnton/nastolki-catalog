#!/usr/bin/env python3
"""Replace weserv.nl proxy URLs with direct BGG CDN URLs in index.html BGG data."""
import re, sys, urllib.parse

HTML_FILE = "index.html"

def weserv_to_direct(url):
    if "weserv.nl" not in url and "wsrv.nl" not in url:
        return url
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    src = qs.get("url", [None])[0]
    if src:
        return "https://" + src
    return url

with open(HTML_FILE, encoding="utf-8") as f:
    html = f.read()

# Replace every weserv/wsrv URL string inside the BGG block
def replace_url(m):
    orig = m.group(0)
    inner = m.group(1)
    fixed = weserv_to_direct(inner)
    return orig.replace(inner, fixed)

# Match quoted URL strings that contain weserv.nl
count = 0
def replacer(m):
    global count
    orig = m.group(0)
    fixed = weserv_to_direct(m.group(1))
    if fixed != m.group(1):
        count += 1
        return orig.replace(m.group(1), fixed)
    return orig

pattern = r'"(https?://(?:images\.weserv\.nl|wsrv\.nl)[^"]+)"'
new_html = re.sub(pattern, replacer, html)

if count == 0:
    print("No weserv.nl URLs found — nothing to change.")
    sys.exit(0)

with open(HTML_FILE, "w", encoding="utf-8") as f:
    f.write(new_html)

print(f"Replaced {count} weserv.nl URLs with direct BGG CDN URLs.")

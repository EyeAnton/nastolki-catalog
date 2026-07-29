#!/usr/bin/env python3
"""
Fetch new messages from the Telegram group via Bot API, classify them with
Claude (a message may list multiple games at once), and either apply
confident matches via auto_add.py or queue uncertain ones in
review_needed.json for manual review.

Usage:
  export ANTHROPIC_API_KEY=...
  export TELEGRAM_BOT_TOKEN=...
  python add_new_listings.py [--dry-run] [--limit N] [--chat-id ID] [--debug-save-raw]

Notes on the Telegram Bot API:
  - The bot only ever sees messages sent to a chat AFTER it joined that chat.
    It cannot backfill history from before it was added.
  - Calling getUpdates with an `offset` permanently clears every update with
    update_id < offset from Telegram's side, so the new offset is only
    persisted to state.json after a successful non-dry-run pass.
  - Entities (bold/strikethrough/...) are given as separate offset/length
    spans in UTF-16 code units, not embedded in the text — sellers strike
    through items that are already sold, so we re-render those spans as
    ~~sold item~~ before handing the text to Claude.
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.parse
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).parent
HTML = ROOT / "index.html"
STATE_FILE = ROOT / "state.json"
REVIEW_FILE = ROOT / "review_needed.json"
BLACKLIST_FILE = ROOT / "blacklist.json"
AUTO_ADD = ROOT / "auto_add.py"

# Group username as configured on t.me; used only to sanity-check we're
# reading the right chat once the bot has actually joined it.
TARGET_USERNAME = "used_boardgames_armenia"

CONFIDENCE_THRESHOLD = 0.7
TITLE_MATCH_CUTOFF = 0.85

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """You extract board game sale listings from a single Telegram message sent \
in a channel that sells/exchanges used board games in Armenia.

A message may advertise ONE game or MANY games at once (e.g. a bulleted price list).
Text wrapped like ~~this~~ means that item has ALREADY BEEN SOLD — never include it.

Return ONLY a JSON array (no markdown fences), one object per game still available:
[
  {
    "title": string,         // best-guess EXACT board game title (English box title, no seller commentary)
    "price": number or null, // integer AMD, null if not stated
    "lang": "ENG" or "РУС",  // language/edition of the physical copy, best guess from context
    "note": string,          // short extra info from seller (condition, missing pieces, etc), "" if none
    "exchange": boolean,     // true if seller explicitly offers exchange/trade (обмен) for this item
    "confidence": number     // 0.0-1.0, how confident you are this is a real, unambiguous game listing
  }
]

If the message is not a sale/exchange post at all (chat, question, meta post), return [].
"""


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return default


def load_bgg_keys():
    src = HTML.read_text(encoding='utf-8')
    m = re.search(r'const BGG=(\{.*?\});', src, re.DOTALL)
    bgg = json.loads(m.group(1))
    return list(bgg.keys())


def load_d_max_msg_id():
    src = HTML.read_text(encoding='utf-8')
    m = re.search(r'const D=(\[.*?\]);', src, re.DOTALL)
    d = json.loads(m.group(1))
    ids = [item.get('m', 0) for item in d if item.get('m')]
    return max(ids) if ids else 0


def utf16_apply_strikethrough(text, entities):
    """Re-render `strikethrough` entities (offsets are UTF-16 code units) as ~~text~~."""
    spans = sorted(
        (e for e in entities if e.get('type') == 'strikethrough'),
        key=lambda e: e['offset'], reverse=True)
    if not spans:
        return text
    b = bytearray(text.encode('utf-16-le'))
    marker = '~~'.encode('utf-16-le')
    for e in spans:
        start, end = e['offset'] * 2, (e['offset'] + e['length']) * 2
        b[end:end] = marker
        b[start:start] = marker
    return bytes(b).decode('utf-16-le')


def fetch_updates(token, offset=None):
    params = {'timeout': 0}
    if offset is not None:
        params['offset'] = offset
    url = f"https://api.telegram.org/bot{token}/getUpdates?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.load(r)
    if not data.get('ok'):
        raise RuntimeError(f"Telegram API error: {data}")
    return data['result']


def extract_messages(updates, chat_id_filter):
    """Turn raw Bot API updates into [{msg_id, seller, text}], merging photo
    albums (media_group_id) into a single message using whichever part of
    the album actually carried the caption."""
    groups = {}
    standalone = []

    for upd in updates:
        msg = upd.get('message')
        if not msg:
            continue
        chat = msg.get('chat', {})
        if chat_id_filter is not None and chat.get('id') != chat_id_filter:
            continue

        raw_text = msg.get('text') or msg.get('caption') or ''
        entities = msg.get('entities') or msg.get('caption_entities') or []
        text = utf16_apply_strikethrough(raw_text, entities) if raw_text else ''
        seller = (msg.get('from') or {}).get('username', '')
        msg_id = msg['message_id']
        mgid = msg.get('media_group_id')

        if mgid:
            g = groups.setdefault(mgid, {'msg_id': msg_id, 'seller': seller, 'text': ''})
            g['msg_id'] = min(g['msg_id'], msg_id)
            if text and not g['text']:
                g['text'] = text
        elif text:
            standalone.append({'msg_id': msg_id, 'seller': seller, 'text': text})

    standalone.extend(g for g in groups.values() if g['text'])
    return standalone


def is_blacklisted(seller, blacklist):
    seller_lower = seller.lower().lstrip('@')
    return any(seller_lower == b.lower().lstrip('@') for b in blacklist)


def classify_with_claude(client, text):
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
    listings = json.loads(raw)
    return listings if isinstance(listings, list) else [listings]


def best_bgg_match(title, bgg_keys):
    if title in bgg_keys:
        return title
    matches = difflib.get_close_matches(
        title, bgg_keys, n=1, cutoff=TITLE_MATCH_CUTOFF)
    return matches[0] if matches else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--limit', type=int, default=None)
    p.add_argument('--chat-id', type=int, default=None,
                    help="Restrict to this chat id (defaults to state.json's stored chat_id, "
                         "or accepts any chat if none is known yet)")
    p.add_argument('--debug-save-raw', action='store_true')
    p.add_argument('--min-msg-id', type=int, default=None,
                    help="Override state.json's last_msg_id filter (handy when testing "
                         "against a sandbox chat with its own message numbering)")
    args = p.parse_args()

    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set", file=sys.stderr)
        sys.exit(1)
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    state = load_json(STATE_FILE, {'last_msg_id': load_d_max_msg_id()})
    blacklist = load_json(BLACKLIST_FILE, [])
    bgg_keys = load_bgg_keys()
    review_queue = load_json(REVIEW_FILE, [])

    last_msg_id = args.min_msg_id if args.min_msg_id is not None else state.get('last_msg_id', 0)
    last_update_id = state.get('last_update_id')
    chat_id_filter = args.chat_id if args.chat_id is not None else state.get('chat_id')

    print(f"State: last_msg_id={last_msg_id}, last_update_id={last_update_id}, "
          f"chat_id_filter={chat_id_filter}")

    updates = fetch_updates(bot_token, offset=last_update_id)
    print(f"Fetched {len(updates)} raw updates from Bot API")

    if args.debug_save_raw:
        debug_path = ROOT / "debug_updates.json"
        debug_path.write_text(json.dumps(updates, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"Saved raw updates to {debug_path}")

    # Learn the chat_id the first time the bot sees a message, so future runs
    # don't need --chat-id passed by hand.
    if chat_id_filter is None:
        for upd in updates:
            msg = upd.get('message')
            if msg:
                chat_id_filter = msg['chat']['id']
                print(f"Learned chat_id={chat_id_filter} ({msg['chat'].get('title')})")
                break

    messages = extract_messages(updates, chat_id_filter)
    print(f"Parsed {len(messages)} messages (after album merge, filtered to chat_id={chat_id_filter})")

    new_messages = sorted(
        (m for m in messages if m['msg_id'] > last_msg_id),
        key=lambda m: m['msg_id'])
    print(f"New messages (id > {last_msg_id}): {len(new_messages)}")

    if args.limit:
        new_messages = new_messages[:args.limit]
        print(f"Limited to {len(new_messages)} messages")

    max_update_id = max((u['update_id'] for u in updates), default=(last_update_id - 1 if last_update_id else -1))
    max_seen_id = last_msg_id
    applied, queued, skipped = 0, 0, 0

    for msg in new_messages:
        max_seen_id = max(max_seen_id, msg['msg_id'])
        print(f"\n--- msg {msg['msg_id']} (@{msg['seller']}) ---")
        print(msg['text'][:300])

        if is_blacklisted(msg['seller'], blacklist):
            print("SKIP: seller is blacklisted")
            skipped += 1
            continue

        try:
            listings = classify_with_claude(client, msg['text'])
        except Exception as e:
            print(f"SKIP: Claude classification failed: {e}")
            skipped += 1
            continue

        if not listings:
            print("SKIP: not a sale/exchange post")
            skipped += 1
            continue

        for extracted in listings:
            print(f"Extracted: {extracted}")

            confidence = extracted.get('confidence', 0)
            title = extracted.get('title', '')
            bgg_match = best_bgg_match(title, bgg_keys) if title else None

            reason = None
            if confidence < CONFIDENCE_THRESHOLD:
                reason = f"low confidence ({confidence})"
            elif not title:
                reason = "no title extracted"
            elif not bgg_match:
                reason = f"no confident BGG match for '{title}'"

            if reason:
                print(f"REVIEW NEEDED: {reason}")
                review_queue.append({
                    'msg_id': msg['msg_id'],
                    'seller': msg['seller'],
                    'raw_text': msg['text'],
                    'extracted': extracted,
                    'reason': reason,
                })
                queued += 1
                continue

            cmd = [
                sys.executable, str(AUTO_ADD),
                '--title', bgg_match,
                '--price', str(extracted.get('price') or 0),
                '--lang', extracted.get('lang', 'ENG'),
                '--msg_id', str(msg['msg_id']),
                '--seller', msg['seller'],
                '--note', extracted.get('note', ''),
            ]
            if extracted.get('exchange'):
                cmd.append('--exchange')

            if args.dry_run:
                print(f"DRY-RUN would run: {' '.join(cmd)}")
            else:
                subprocess.run(cmd, check=True)
            applied += 1

    print(f"\n=== Summary: applied={applied}, queued_for_review={queued}, "
          f"skipped={skipped} ===")

    if not args.dry_run:
        state['last_msg_id'] = max_seen_id
        state['last_update_id'] = max_update_id + 1
        if chat_id_filter is not None:
            state['chat_id'] = chat_id_filter
        STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        REVIEW_FILE.write_text(
            json.dumps(review_queue, ensure_ascii=False, indent=2),
            encoding='utf-8')
        print(f"Saved state.json (last_msg_id={max_seen_id}, last_update_id={state['last_update_id']}) "
              f"and review_needed.json ({len(review_queue)} entries)")
    else:
        print("DRY-RUN: state.json and review_needed.json not modified "
              "(NOTE: Telegram still queues these updates since we didn't confirm an offset — "
              "safe to re-run dry-run or real run without losing anything)")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Single-shot HMT Kohinoor stock check, designed to run on GitHub Actions
every 5 minutes (see .github/workflows/hmt-watch.yml).

- Reads state.json (committed in the repo) for previous statuses.
- Checks all three HMT variants via the server-rendered stock flags.
- Posts to Discord (DISCORD_WEBHOOK_URL secret) on out->in transitions,
  or if something is already in stock on the very first run.
- Writes state.json + last_check.txt (committed back by the workflow).

Run locally to test:  python hmt_github_action.py
(Without DISCORD_WEBHOOK_URL set it just prints what it would send.)
"""

import json
import os
import re
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE, "state.json")
LAST_CHECK_FILE = os.path.join(BASE, "last_check.txt")
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

TARGETS = [
    {"key": "b-maroon-sunray",
     "name": "Kohinoor Quartz B Maroon Sunray",
     "price": "₹2,899",
     "url": "https://www.hmtwatches.store/product/77733243-645c-4eac-8e69-63425e1cc09b",
     "color": None},
    {"key": "b1-maroon",
     "name": "Kohinoor Quartz B1 - Maroon",
     "price": "₹2,799",
     "url": "https://www.hmtwatches.store/product/0035cf80-48d5-4cf3-a02f-1f36b01071a5",
     "color": "Maroon"},
    {"key": "b1-light-blue-sunray",
     "name": "Kohinoor Quartz B1 - Light Blue Sunray",
     "price": "₹2,375",
     "url": "https://www.hmtwatches.store/product/3f9c0b65-255a-46d6-b957-0b5c51b9cdd6",
     "color": "Light Blue Sunray"},
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def product_stock(html):
    m = re.search(r'"availability"\s*:\s*\{\s*"inStock"\s*:\s*(true|false)', html)
    return m.group(1) == "true" if m else None


def variant_stock(html, color):
    for m in re.finditer(r'"color"\s*:\s*\{\s*"value"\s*:\s*"' + re.escape(color) + r'"', html):
        tail = html[m.end():m.end() + 12000]
        s = re.search(r'"inStock"\s*:\s*(true|false)', tail)
        if s and not re.search(r'"color"\s*:\s*\{', tail[:s.start()]):
            return s.group(1) == "true"
    return None


def check_all():
    pages, out = {}, {}
    for t in TARGETS:
        url = t["url"]
        if url not in pages:
            try:
                pages[url] = fetch(url)
            except Exception as e:
                print(f"fetch failed for {url}: {e}", flush=True)
                pages[url] = None
        html = pages[url]
        if html is None:
            out[t["key"]] = None
        elif t["color"]:
            out[t["key"]] = variant_stock(html, t["color"])
        else:
            out[t["key"]] = product_stock(html)
    return out


def discord_post(text):
    if not WEBHOOK_URL:
        print("[discord] no webhook set; would have sent:", flush=True)
        print("   " + text.replace("\n", " | "), flush=True)
        return
    data = json.dumps({"content": text}).encode("utf-8")
    req = urllib.request.Request(WEBHOOK_URL, data=data,
                                 headers={"Content-Type": "application/json", **UA})
    urllib.request.urlopen(req, timeout=15).read()
    print("[discord] alert sent", flush=True)


def main():
    first_run = not os.path.exists(STATE_FILE)
    last = {}
    if not first_run:
        try:
            last = json.load(open(STATE_FILE))
        except Exception:
            last = {}

    cur = check_all()
    print("status:", {t["key"]: ("in" if cur.get(t["key"]) else "out"
                                 if cur.get(t["key"]) is False else "?")
                       for t in TARGETS}, flush=True)

    if first_run:
        discord_post("👀 **HMT Kohinoor watch is live** - checking every 5 min, "
                     "24/7. I'll ping here the second anything comes in stock.")

    new_state = dict(last)
    for t in TARGETS:
        key = t["key"]
        was, is_now = last.get(key), cur.get(key)
        if is_now is True:
            new_state[key] = "in"
        elif is_now is False:
            new_state[key] = "out"
        # None -> keep previous value
        if is_now and was != "in":
            discord_post(f"🚨 **HMT RESTOCK!** {t['name']} is **IN STOCK** "
                         f"at {t['price']}!\nBuy now before it sells out: {t['url']}")

    with open(STATE_FILE, "w") as f:
        json.dump(new_state, f, indent=2)
    with open(LAST_CHECK_FILE, "w") as f:
        f.write(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    print("state saved", flush=True)


if __name__ == "__main__":
    main()

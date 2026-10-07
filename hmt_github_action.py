#!/usr/bin/env python3
"""
Single-shot HMT Kohinoor stock check, designed to run on GitHub Actions
(see .github/workflows/hmt-watch.yml). It is triggered by
an external scheduler (cron-job.org, every 2 minutes), with GitHub's own schedule as a backup.

- Reads state.json (committed in the repo) for previous statuses.
- Finds each watch on its product page by the SKU in its URL, so it never
  picks up the stock flag of a related product or a same-named variant.
- Posts to Discord (DISCORD_WEBHOOK_URL secret) on out->in transitions.
- Warns on Discord if a watch can't be checked several runs in a row
  (site down, blocked, or page layout changed), and again when it recovers.
- Writes state.json, plus last_check.txt once a day as a heartbeat.

Send a Discord test message (no stock check):  set SEND_TEST_MESSAGE=true,
or run the workflow from the Actions tab with "Send a test message" ticked.

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

# Alert after this many consecutive runs where a watch couldn't be checked.
UNKNOWN_ALERT_AFTER = 3

TARGETS = [
    {"key": "b-maroon-sunray",
     "name": "Kohinoor Quartz B Maroon Sunray",
     "price": "₹2,899",
     "url": "https://www.hmtwatches.store/product/77733243-645c-4eac-8e69-63425e1cc09b"},
    {"key": "b1-maroon",
     "name": "Kohinoor Quartz B1 - Maroon",
     "price": "₹2,799",
     "url": "https://www.hmtwatches.store/product/0035cf80-48d5-4cf3-a02f-1f36b01071a5"},
    {"key": "b1-light-blue-sunray",
     "name": "Kohinoor Quartz B1 - Light Blue Sunray",
     "price": "₹2,375",
     "url": "https://www.hmtwatches.store/product/3f9c0b65-255a-46d6-b957-0b5c51b9cdd6"},
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def sku_from_url(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


def sku_stock(html, sku):
    """Stock flag of the variant whose SKU is `sku`, or None if not found.

    Each variant in the page data looks like
      {"sku":"<uuid>","variantDimensions":...,"buyingOptions":{...
        "availability":{"inStock":true|false,...}}}
    The search is bounded by the next variant so it can't spill over.
    """
    m = re.search(r'"sku"\s*:\s*"' + re.escape(sku) + r'"\s*,\s*"variantDimensions"', html)
    if not m:
        return None
    nxt = re.search(r'"variantDimensions"', html[m.end():])
    chunk = html[m.end():m.end() + nxt.start()] if nxt else html[m.end():m.end() + 30000]
    s = re.search(r'"availability"\s*:\s*\{\s*"inStock"\s*:\s*(true|false)', chunk)
    return s.group(1) == "true" if s else None


def check_all():
    out = {}
    for t in TARGETS:
        try:
            html = fetch(t["url"])
        except Exception as e:
            print(f"fetch failed for {t['url']}: {e}", flush=True)
            out[t["key"]] = None
            continue
        out[t["key"]] = sku_stock(html, sku_from_url(t["url"]))
        if out[t["key"]] is None:
            print(f"stock flag not found for {t['name']} (page layout changed?)", flush=True)
    return out


def discord_post(text):
    """Send a Discord message. Returns True on success."""
    if not WEBHOOK_URL:
        print("[discord] no webhook set; would have sent:", flush=True)
        print("   " + text.replace("\n", " | "), flush=True)
        return True
    data = json.dumps({"content": text}).encode("utf-8")
    req = urllib.request.Request(WEBHOOK_URL, data=data,
                                 headers={"Content-Type": "application/json", **UA})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print(f"[discord] send failed: {e}", flush=True)
        return False
    print("[discord] alert sent", flush=True)
    return True


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    # Older versions stored statuses at the top level; keep them.
    if "status" not in state:
        state = {"status": {t["key"]: state[t["key"]] for t in TARGETS if t["key"] in state},
                 "unknown_streak": {}, "unknown_alerted": {}}
    state.setdefault("unknown_streak", {})
    state.setdefault("unknown_alerted", {})
    return state


def main():
    if os.environ.get("SEND_TEST_MESSAGE", "").lower() == "true":
        ok = discord_post("🧪 **HMT watcher test** - Discord alerts are working. "
                          "You'll get a 🚨 message here when a watch is back in stock.")
        raise SystemExit(0 if ok else 1)

    first_run = not os.path.exists(STATE_FILE)
    state = load_state()
    status, streak, alerted = state["status"], state["unknown_streak"], state["unknown_alerted"]

    cur = check_all()
    print("status:", {k: {True: "in", False: "out", None: "?"}[v] for k, v in cur.items()},
          flush=True)

    if first_run:
        discord_post("👀 **HMT Kohinoor watch is live** - checking every 5 min, "
                     "24/7. I'll ping here the second anything comes in stock.")

    for t in TARGETS:
        key, is_now = t["key"], cur[t["key"]]

        if is_now is None:
            # Couldn't check: keep the previous status, warn once after a streak.
            streak[key] = streak.get(key, 0) + 1
            if streak[key] >= UNKNOWN_ALERT_AFTER and not alerted.get(key):
                if discord_post(f"⚠️ **HMT watcher can't check {t['name']}** - "
                                f"{streak[key]} runs in a row failed. The site may be down, "
                                f"blocking requests, or its page layout changed.\n{t['url']}"):
                    alerted[key] = True
            continue

        if alerted.get(key):
            if discord_post(f"✅ HMT watcher is checking {t['name']} again."):
                alerted[key] = False
        streak[key] = 0

        if is_now and status.get(key) != "in":
            # Only record "in" once the alert is delivered, so a failed send retries next run.
            if discord_post(f"🚨 **HMT RESTOCK!** {t['name']} is **IN STOCK** "
                            f"at {t['price']}!\nBuy now before it sells out: {t['url']}"):
                status[key] = "in"
        elif not is_now:
            status[key] = "out"

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")

    # Daily heartbeat commit keeps the repo "active" so GitHub doesn't disable
    # the workflow after 60 days, without a commit on every run.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with open(LAST_CHECK_FILE, encoding="utf-8") as f:
            last_day = f.read()[:10]
    except OSError:
        last_day = ""
    if last_day != today:
        with open(LAST_CHECK_FILE, "w", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    print("state saved", flush=True)


if __name__ == "__main__":
    main()

"""One-off check: does the watcher's parser read inStock=true correctly?"""
import json, re
import hmt_github_action as w

PAGES = [w.TARGETS[0]["url"], "https://www.hmtwatches.store/"]


def next_data(html):
    nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(nd.group(1)) if nd else None


def avail(o):
    for bo in (o.get("buyingOptions"), (o.get("variantAttributes") or {}).get("buyingOptions")
               if isinstance(o.get("variantAttributes"), dict) else None):
        try:
            return bo["singlePurchase"]["availability"]
        except (KeyError, TypeError):
            pass
    return None


found = {}
links = set()
for url in PAGES:
    try:
        html = w.fetch(url)
    except Exception as e:
        print("fetch failed", url, e)
        continue
    links |= set(re.findall(r'href="(/[^"#?]{2,80})"', html))
    data = next_data(html)
    stack = [data]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            a = avail(o) if isinstance(o.get("sku"), str) else None
            if a is not None:
                name = o.get("name") or (o.get("attributes") or {}).get("name") if isinstance(o.get("attributes"), dict) or o.get("name") else o.get("name")
                found.setdefault(o["sku"], (name, a))
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)

print(f"\n{len(found)} products with a stock flag")
combos = {}
for sku, (name, a) in found.items():
    key = (a.get("inStock"), a.get("isBuyable"))
    combos.setdefault(key, []).append((sku, name, a))
for k, v in combos.items():
    print(f"inStock={k[0]} isBuyable={k[1]}: {len(v)}")
print("non-product links:", sorted(l for l in links if "/product/" not in l)[:60])

# Scan every product page listed in the sitemap until a few in-stock ones turn up.
import time, urllib.request
sm_urls, product_urls = [], []
try:
    robots = w.fetch("https://www.hmtwatches.store/robots.txt")
    print("robots.txt:", robots[:600].replace("\n", " | "))
    sm_urls = re.findall(r"(?im)^sitemap:\s*(\S+)", robots)
except Exception as e:
    print("robots.txt failed:", e)
sm_urls = sm_urls or ["https://www.hmtwatches.store/sitemap.xml"]
seen_sm = set()
while sm_urls and len(seen_sm) < 20:
    sm = sm_urls.pop(0)
    if sm in seen_sm:
        continue
    seen_sm.add(sm)
    try:
        xml = w.fetch(sm)
    except Exception as e:
        print("sitemap failed", sm, e)
        continue
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    print(f"sitemap {sm}: {len(locs)} urls; sample {locs[:3]}")
    for l in locs:
        (sm_urls if l.endswith(".xml") else product_urls).append(l)
product_urls = [u for u in dict.fromkeys(product_urls) if "/product/" in u]
print(f"{len(product_urls)} product urls in sitemap")
checked = 0
for url in product_urls[:250]:
    sku = url.rstrip("/").rsplit("/", 1)[-1]
    if sku in found:
        continue
    try:
        html = urllib.request.urlopen(urllib.request.Request(url, headers=w.UA), timeout=30).read().decode("utf-8", "replace")
    except Exception as e:
        print("  fetch failed", url, e)
        continue
    checked += 1
    data = next_data(html)
    for v in ((data or {}).get("props", {}).get("pageProps", {}).get("catalog") or {}).get("variantsDetails", []):
        a = avail(v)
        if a is not None and v.get("sku") not in found:
            found[v["sku"]] = ((data["props"]["pageProps"]["catalog"].get("name")), a)
            key = (a.get("inStock"), a.get("isBuyable"))
            combos.setdefault(key, []).append((v["sku"], found[v["sku"]][0], a))
    if sum(len(v) for k, v in combos.items() if k[0] or k[1]) >= 4:
        break
    time.sleep(0.3)
print(f"checked {checked} product pages; now {len(found)} variants:")
for k, v in combos.items():
    print(f"inStock={k[0]} isBuyable={k[1]}: {len(v)}")

ins = [x for k, v in combos.items() if k[0] or k[1] for x in v]
print(f"\n{len(ins)} in stock or buyable:")
for sku, name, a in ins[:10]:
    print("  ", sku, name, a)
for sku, name, a in ins[:4]:
    url = f"https://www.hmtwatches.store/product/{sku}"
    html = w.fetch(url)
    print(f"  watcher parser on {name}: sku_stock={w.sku_stock(html, sku)}")
    data = next_data(html)
    for v in (data["props"]["pageProps"].get("catalog") or {}).get("variantsDetails", []):
        if v.get("sku") == sku:
            print("     own page availability:", avail(v))

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

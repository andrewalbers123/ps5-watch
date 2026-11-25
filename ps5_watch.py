#!/usr/bin/env python3
"""PS5 restock watcher for Best Buy stores near a ZIP code.

Setup (environment variables):
  BESTBUY_API_KEY  free key from https://developer.bestbuy.com
  NTFY_TOPIC       any hard-to-guess string, e.g. "ps5-austin-7f3k9x"
                   (subscribe to the same topic in the free ntfy app)
  SKUS             comma-separated Best Buy SKUs to watch
  ZIP              default 78702
  RADIUS_MILES     default 25

Usage:
  python ps5_watch.py --find        # list PS5 SKUs so you can pick yours
  python ps5_watch.py               # check stock once, notify on new stock
  python ps5_watch.py --loop 300    # keep checking every 300 s (computer/Termux)
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API_KEY = os.environ.get("BESTBUY_API_KEY", "")
ZIP = os.environ.get("ZIP", "78702")
RADIUS = os.environ.get("RADIUS_MILES", "25")
SKUS = [s.strip() for s in os.environ.get("SKUS", "").split(",") if s.strip()]
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
BASE = "https://api.bestbuy.com/v1"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ps5-watch/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def find_skus():
    q = "(search=playstation&search=5&search=console)"
    url = (
        f"{BASE}/products{q}?apiKey={API_KEY}"
        "&show=sku,name,salePrice,onlineAvailability"
        "&pageSize=25&format=json"
    )
    for p in get_json(url).get("products", []):
        print(f"{p['sku']}  ${p.get('salePrice')}  {p['name']}")


def store_availability(sku):
    """Stores near ZIP that have this SKU available for pickup."""
    url = (
        f"{BASE}/stores(area({ZIP},{RADIUS}))+products(sku={sku})"
        f"?apiKey={API_KEY}"
        "&show=storeId,name,city,distance,address,phone"
        "&pageSize=25&format=json"
    )
    return get_json(url).get("stores", [])


def online_info(sku):
    url = (
        f"{BASE}/products/{sku}.json?apiKey={API_KEY}"
        "&show=sku,name,salePrice,onlineAvailability,url"
    )
    return get_json(url)


def notify(title, message, click=None):
    print(f"NOTIFY: {title} | {message}")
    if not NTFY_TOPIC:
        return
    headers = {"Title": title, "Priority": "high", "Tags": "video_game"}
    if click:
        headers["Click"] = click
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    urllib.request.urlopen(req, timeout=20).read()


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def check_once():
    state = load_state()
    for sku in SKUS:
        try:
            info = online_info(sku)
            stores = store_availability(sku)
        except Exception as exc:  # network hiccup, bad key, rate limit
            print(f"[{sku}] error: {exc}", file=sys.stderr)
            continue

        name = info.get("name", sku)
        price = info.get("salePrice")
        online = bool(info.get("onlineAvailability"))
        store_ids = sorted(str(s["storeId"]) for s in stores)
        prev = state.get(sku, {"online": False, "stores": []})

        new_stores = [s for s in stores if str(s["storeId"]) not in prev["stores"]]
        went_online = online and not prev["online"]

        if new_stores:
            lines = [
                f"{s['name']} ({s['city']}, {s.get('distance', '?')} mi)"
                for s in new_stores
            ]
            notify(
                f"PS5 in stock near {ZIP}",
                f"{name} ${price}\n" + "\n".join(lines),
                click=info.get("url"),
            )
        if went_online:
            notify(
                "PS5 available online",
                f"{name} ${price} (ships or pickup)",
                click=info.get("url"),
            )
        if not new_stores and not went_online:
            print(f"[{sku}] no new stock ({len(stores)} stores, online={online})")

        state[sku] = {"online": online, "stores": store_ids}
    save_state(state)


def main():
    if not API_KEY:
        sys.exit("Set BESTBUY_API_KEY first.")
    if "--find" in sys.argv:
        find_skus()
        return
    if not SKUS:
        sys.exit("Set SKUS (run with --find to look them up).")
    if "--loop" in sys.argv:
        idx = sys.argv.index("--loop")
        delay = int(sys.argv[idx + 1]) if len(sys.argv) > idx + 1 else 300
        while True:
            check_once()
            time.sleep(max(delay, 60))
    else:
        check_once()


if __name__ == "__main__":
    main()

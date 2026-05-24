import os
import re
import json
import time
import html
import requests
from datetime import datetime, timezone, timedelta

WEBHOOK = os.getenv("DISCORD_WEBHOOK")
SEEN_FILE = "seen_mobile_epic.json"

FREE_PAGE = "https://store.epicgames.com/en-US/free-games"
JINA_FREE_PAGE = "https://r.jina.ai/https://store.epicgames.com/en-US/free-games"

API = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"

FOOTER_TEXT = "Subho's Epic Games Mobile Notifier"
FOOTER_ICON = "https://files.catbox.moe/qttqpy.png"

EPIC_LOGO = "https://cdn2.unrealengine.com/epic-games-store-logo-340x340-340x340-566a0f62ad4f.png"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

MANUAL_FALLBACK = {
    "monument-valley-3": {
        "title": "Monument Valley 3",
        "android": "https://store.epicgames.com/p/monument-valley-3-android-c7433e",
        "ios": "https://store.epicgames.com/p/monument-valley-3-ios-e569e7",
        "image": None,
    }
}


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()

    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)


def clean_title(text):
    text = html.unescape(text or "").strip()
    text = re.sub(r"\s*\|\s*Download.*$", "", text, flags=re.I)
    text = re.sub(r"\s*-\s*Epic Games Store.*$", "", text, flags=re.I)
    return text.strip() or "Unknown Mobile Game"


def slug_to_title(slug):
    slug = re.sub(r"-(android|ios)(-[a-z0-9]+)?$", "", slug, flags=re.I)
    return clean_title(slug.replace("-", " ").title())


def next_epic_thursday():
    now = datetime.now(timezone.utc)
    target = now.replace(hour=15, minute=0, second=0, microsecond=0)

    days = (3 - now.weekday()) % 7
    target += timedelta(days=days)

    if target <= now:
        target += timedelta(days=7)

    return int(target.timestamp())


def unix_time(date_text):
    if not date_text:
        return None

    try:
        return int(datetime.fromisoformat(date_text.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def safe_get(url, timeout=30):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        print(f"GET {url} -> {r.status_code}")
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print(f"Fetch failed: {url} | {e}")

    return ""


def extract_mobile_links(text):
    groups = {}

    patterns = [
        r"https://store\.epicgames\.com/(?:[a-zA-Z-]+/)?p/([a-z0-9-]*(?:android|ios)[a-z0-9-]*)",
        r"/p/([a-z0-9-]*(?:android|ios)[a-z0-9-]*)",
    ]

    for pattern in patterns:
        for slug in re.findall(pattern, text, flags=re.I):
            slug = slug.strip("/").lower()

            if "android" not in slug and "ios" not in slug:
                continue

            base = re.sub(r"-(android|ios)(-[a-z0-9]+)?$", "", slug, flags=re.I)
            platform = "android" if "android" in slug else "ios"

            groups.setdefault(base, {
                "title": slug_to_title(base),
                "android": None,
                "ios": None,
                "image": None,
            })

            groups[base][platform] = f"https://store.epicgames.com/p/{slug}"

    return groups


def get_meta_info(url):
    text = safe_get(url, timeout=25)

    title = None
    image = None

    title_match = re.search(r'<meta property="og:title" content="([^"]+)"', text, re.I)
    if title_match:
        title = clean_title(title_match.group(1))

    image_match = re.search(r'<meta property="og:image" content="([^"]+)"', text, re.I)
    if image_match:
        image = html.unescape(image_match.group(1))

    return title, image


def fetch_from_free_page():
    groups = {}

    direct_html = safe_get(FREE_PAGE)
    groups.update(extract_mobile_links(direct_html))

    if not groups:
        print("Direct free-games page failed or no mobile links found. Trying Jina Reader.")
        jina_text = safe_get(JINA_FREE_PAGE)
        groups.update(extract_mobile_links(jina_text))

    return groups


def fetch_from_epic_api():
    groups = {}

    try:
        r = requests.get(API, headers=HEADERS, timeout=30)
        print(f"GET Epic API -> {r.status_code}")
        r.raise_for_status()

        games = r.json()["data"]["Catalog"]["searchStore"]["elements"]
    except Exception as e:
        print(f"Epic API failed: {e}")
        return groups

    for game in games:
        raw = json.dumps(game).lower()

        if "android" not in raw and "ios" not in raw and "iphone" not in raw and "ipad" not in raw:
            continue

        title = clean_title(game.get("title"))
        image = None

        for img in game.get("keyImages", []):
            if img.get("type") in ["DieselStoreFrontWide", "OfferImageWide", "Thumbnail"]:
                image = img.get("url")
                break

        mappings = game.get("catalogNs", {}).get("mappings") or []
        for m in mappings:
            slug = (m.get("pageSlug") or "").lower()
            if not slug:
                continue

            if "android" not in slug and "ios" not in slug:
                continue

            base = re.sub(r"-(android|ios)(-[a-z0-9]+)?$", "", slug, flags=re.I)
            platform = "android" if "android" in slug else "ios"

            groups.setdefault(base, {
                "title": title,
                "android": None,
                "ios": None,
                "image": image,
            })

            groups[base][platform] = f"https://store.epicgames.com/p/{slug}"

    return groups


def merge_groups(*sources):
    merged = {}

    for source in sources:
        for base, item in source.items():
            merged.setdefault(base, {
                "title": item.get("title") or slug_to_title(base),
                "android": None,
                "ios": None,
                "image": None,
            })

            if item.get("title") and item["title"] != "Unknown Mobile Game":
                merged[base]["title"] = item["title"]

            if item.get("android"):
                merged[base]["android"] = item["android"]

            if item.get("ios"):
                merged[base]["ios"] = item["ios"]

            if item.get("image"):
                merged[base]["image"] = item["image"]

    return merged


def platform_text(item):
    platforms = []

    if item.get("ios"):
        platforms.append("🍎 iOS")

    if item.get("android"):
        platforms.append("🤖 Android")

    return " + ".join(platforms) if platforms else "📱 Mobile"


def claim_links(item):
    links = []

    if item.get("android"):
        links.append(f"[🤖 Claim Android]({item['android']})")

    if item.get("ios"):
        links.append(f"[🍎 Claim iOS]({item['ios']})")

    return "\n".join(links) or "No direct claim link found"


def send_discord(item):
    title = item.get("title") or "Unknown Mobile Game"
    main_link = item.get("android") or item.get("ios") or "https://store.epicgames.com/mobile"
    end_ts = next_epic_thursday()

    embed = {
        "title": "Epic Games - iOS / Android Free Games",
        "url": main_link,
        "color": 0x2F80ED,
        "thumbnail": {"url": EPIC_LOGO},
        "fields": [
            {
                "name": title,
                "value": f"[Open Store Page]({main_link})",
                "inline": False,
            },
            {
                "name": "Platform",
                "value": platform_text(item),
                "inline": True,
            },
            {
                "name": "Discount",
                "value": "-100%",
                "inline": True,
            },
            {
                "name": "End at",
                "value": f"<t:{end_ts}:F>\n<t:{end_ts}:R>",
                "inline": False,
            },
            {
                "name": "Claim Links",
                "value": claim_links(item),
                "inline": False,
            },
        ],
        "footer": {
            "text": FOOTER_TEXT,
            "icon_url": FOOTER_ICON,
        },
    }

    if item.get("image"):
        embed["image"] = {"url": item["image"]}

    r = requests.post(WEBHOOK, json={"embeds": [embed]}, timeout=20)
    print(f"Discord webhook -> {r.status_code}")
    r.raise_for_status()


def enrich_items(items):
    for base, item in items.items():
        if item.get("title") and item.get("image"):
            continue

        url = item.get("android") or item.get("ios")
        if not url:
            continue

        title, image = get_meta_info(url)

        if title and title != "Unknown Mobile Game":
            item["title"] = title

        if image:
            item["image"] = image

        time.sleep(0.5)

    return items


def main():
    if not WEBHOOK:
        raise SystemExit("DISCORD_WEBHOOK secret is missing")

    seen = load_seen()

    page_items = fetch_from_free_page()
    api_items = fetch_from_epic_api()

    items = merge_groups(page_items, api_items)

    if not items:
        print("No mobile freebies found from page/API. Using manual emergency fallback.")
        items = merge_groups(MANUAL_FALLBACK)

    items = enrich_items(items)

    found = 0
    end_ts = next_epic_thursday()

    for base, item in items.items():
        if not item.get("android") and not item.get("ios"):
            continue

        seen_key = f"{base}:{end_ts}:{item.get('android')}:{item.get('ios')}"

        if seen_key in seen:
            print(f"Already posted: {item.get('title')}")
            continue

        print(f"Posting: {item.get('title')} | {platform_text(item)}")
        send_discord(item)

        seen.add(seen_key)
        found += 1
        time.sleep(1)

    save_seen(seen)
    print(f"Done. New mobile freebies posted: {found}")


if __name__ == "__main__":
    main()

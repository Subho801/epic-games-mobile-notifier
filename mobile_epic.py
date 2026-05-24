import os, json, re, time, html
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

WEBHOOK = os.getenv("DISCORD_WEBHOOK")
SEEN_FILE = "seen_mobile_epic.json"

API = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"
FREE_PAGE = "https://store.epicgames.com/en-US/free-games"

FOOTER_TEXT = "Subho's Epic Games Mobile Notifier"
FOOTER_ICON = "https://files.catbox.moe/qttqpy.png"

HEADERS = {"User-Agent": "Mozilla/5.0"}


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)


def unix_time(date_text):
    if not date_text:
        return None
    try:
        return int(datetime.fromisoformat(date_text.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def next_thursday_epic_reset():
    now = datetime.now(timezone.utc)
    target = now.replace(hour=15, minute=0, second=0, microsecond=0)

    days = (3 - now.weekday()) % 7
    target += timedelta(days=days)

    if target <= now:
        target += timedelta(days=7)

    return int(target.timestamp())


def clean_title(title):
    title = html.unescape(title or "").strip()
    title = re.sub(r"\s*\|\s*Download.*$", "", title, flags=re.I)
    title = re.sub(r"\s*-\s*Epic Games Store.*$", "", title, flags=re.I)
    return title.strip()


def get_image_from_html(page_html):
    patterns = [
        r'<meta property="og:image" content="([^"]+)"',
        r'<meta name="twitter:image" content="([^"]+)"',
    ]
    for p in patterns:
        m = re.search(p, page_html)
        if m:
            return html.unescape(m.group(1))
    return None


def get_title_from_html(page_html):
    patterns = [
        r'<meta property="og:title" content="([^"]+)"',
        r"<title>(.*?)</title>",
    ]
    for p in patterns:
        m = re.search(p, page_html, re.S)
        if m:
            return clean_title(m.group(1))
    return "Unknown Mobile Game"


def get_page_info(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        return {
            "title": get_title_from_html(r.text),
            "image": get_image_from_html(r.text),
        }
    except Exception:
        return {"title": "Unknown Mobile Game", "image": None}


def get_image(game):
    for img in game.get("keyImages", []):
        if img.get("type") in ["DieselStoreFrontWide", "OfferImageWide", "Thumbnail"]:
            return img.get("url")
    return None


def get_slug(game):
    mappings = game.get("catalogNs", {}).get("mappings") or []
    for m in mappings:
        if m.get("pageSlug"):
            return m["pageSlug"]
    return game.get("productSlug")


def is_free_now(game):
    promos = game.get("promotions") or {}
    current = promos.get("promotionalOffers") or []

    for block in current:
        for offer in block.get("promotionalOffers", []):
            discount = offer.get("discountSetting", {})
            if discount.get("discountPercentage") == 0:
                return offer
    return None


def fetch_mobile_links_from_free_page():
    """
    Finds Epic mobile product links from /free-games.
    If Epic blocks GitHub Actions with 403, fallback to known current mobile giveaway links.
    """
    fallback = {
        "monument-valley-3": {
            "android": "https://store.epicgames.com/p/monument-valley-3-android-c7433e",
            "ios": "https://store.epicgames.com/p/monument-valley-3-ios-e569e7",
        }
    }

    try:
        r = requests.get(FREE_PAGE, headers=HEADERS, timeout=30)

        if r.status_code == 403:
            print("Free-games page returned 403. Using fallback mobile links.")
            return fallback

        r.raise_for_status()

        found = re.findall(
            r'https://store\.epicgames\.com/[a-zA-Z-]+/p/([^"?#\\]+)|/p/([^"?#\\]+)',
            r.text
        )

        links = {}

        for a, b in found:
            slug = a or b
            slug = slug.strip("/")

            if not slug:
                continue

            low = slug.lower()
            if "android" not in low and "ios" not in low:
                continue

            base = re.sub(r"-(android|ios)(-[a-z0-9]+)?$", "", slug, flags=re.I)
            platform = "android" if "android" in low else "ios"

            links.setdefault(base, {})
            links[base][platform] = f"https://store.epicgames.com/p/{slug}"

        if links:
            return links

        print("No mobile links found on page. Using fallback mobile links.")
        return fallback

    except Exception as e:
        print(f"Free-games page scrape failed: {e}")
        print("Using fallback mobile links.")
        return fallback


def platform_text(links):
    platforms = []
    if links.get("ios"):
        platforms.append("🍎 iOS")
    if links.get("android"):
        platforms.append("🤖 Android")
    return " + ".join(platforms) if platforms else "📱 Mobile"


def claim_links_text(links):
    rows = []

    if links.get("android"):
        rows.append(f"[🤖 Claim Android]({links['android']})")

    if links.get("ios"):
        rows.append(f"[🍎 Claim iOS]({links['ios']})")

    return "\n".join(rows) if rows else "No direct mobile claim link found"


def send_discord(title, links, image=None, end_ts=None, original_price=None):
    main_link = links.get("android") or links.get("ios") or "https://store.epicgames.com/mobile"

    discount_text = "-100%"
    if original_price:
        discount_text += f" was {original_price}"

    if not end_ts:
        end_ts = next_thursday_epic_reset()

    embed = {
        "title": "Epic Games - iOS / Android Free Games",
        "url": main_link,
        "color": 0x2F80ED,
        "thumbnail": {
            "url": "https://cdn2.unrealengine.com/epic-games-store-logo-340x340-340x340-566a0f62ad4f.png"
        },
        "fields": [
            {
                "name": title,
                "value": f"[Open Main Store Page]({main_link})",
                "inline": False
            },
            {
                "name": "Platform",
                "value": platform_text(links),
                "inline": True
            },
            {
                "name": "Discount",
                "value": discount_text,
                "inline": True
            },
            {
                "name": "End at",
                "value": f"<t:{end_ts}:F>\n<t:{end_ts}:R>",
                "inline": False
            },
            {
                "name": "Claim Links",
                "value": claim_links_text(links),
                "inline": False
            }
        ],
        "footer": {
            "text": FOOTER_TEXT,
            "icon_url": FOOTER_ICON
        }
    }

    if image:
        embed["image"] = {"url": image}

    r = requests.post(WEBHOOK, json={"embeds": [embed]}, timeout=20)
    r.raise_for_status()


def api_mobile_games():
    items = []

    try:
        r = requests.get(API, headers=HEADERS, timeout=30)
        r.raise_for_status()
        games = r.json()["data"]["Catalog"]["searchStore"]["elements"]
    except Exception as e:
        print(f"API failed: {e}")
        return items

    for game in games:
        offer = is_free_now(game)
        if not offer:
            continue

        slug = get_slug(game) or ""
        text = json.dumps(game).lower()

        if "android" not in text and "ios" not in text and "iphone" not in text and "ipad" not in text:
            continue

        links = {}
        if "android" in slug.lower():
            links["android"] = f"https://store.epicgames.com/p/{slug}"
        elif "ios" in slug.lower():
            links["ios"] = f"https://store.epicgames.com/p/{slug}"

        items.append({
            "title": game.get("title", "Unknown Mobile Game"),
            "links": links,
            "image": get_image(game),
            "end_ts": unix_time(offer.get("endDate")),
            "price": game.get("price", {}).get("totalPrice", {}).get("fmtPrice", {}).get("originalPrice")
        })

    return items


def main():
    if not WEBHOOK:
        raise SystemExit("DISCORD_WEBHOOK secret is missing")

    seen = load_seen()
    found = 0

    mobile_groups = fetch_mobile_links_from_free_page()

    # First: free-games page fallback, this catches current mobile cards.
    for base, links in mobile_groups.items():
        info_url = links.get("android") or links.get("ios")
        info = get_page_info(info_url)

        title = info["title"]
        image = info["image"]
        end_ts = next_thursday_epic_reset()

        seen_key = f"freepage:{base}:{end_ts}"

        if seen_key in seen:
            continue

        print(f"Posting mobile freebie from page: {title}")
        send_discord(title, links, image=image, end_ts=end_ts)

        seen.add(seen_key)
        found += 1
        time.sleep(1)

    # Second: API fallback, useful if Epic exposes future mobile promos there.
    for item in api_mobile_games():
        title = item["title"]

        # Merge auto claim links from free page if title/base matches.
        base_guess = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        for base, links in mobile_groups.items():
            if base_guess in base or base in base_guess:
                item["links"].update(links)

        if not item["links"]:
            continue

        seen_key = f"api:{title}:{item.get('end_ts')}:{json.dumps(item['links'], sort_keys=True)}"

        if seen_key in seen:
            continue

        print(f"Posting mobile freebie from API: {title}")
        send_discord(
            title,
            item["links"],
            image=item.get("image"),
            end_ts=item.get("end_ts"),
            original_price=item.get("price")
        )

        seen.add(seen_key)
        found += 1
        time.sleep(1)

    save_seen(seen)
    print(f"Done. New mobile freebies posted: {found}")


if __name__ == "__main__":
    main()

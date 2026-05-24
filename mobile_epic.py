import os, json, time, requests
from datetime import datetime, timezone

WEBHOOK = os.getenv("DISCORD_WEBHOOK")
SEEN_FILE = "seen_mobile_epic.json"

API = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"

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
        dt = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return None


def get_image(game):
    for img in game.get("keyImages", []):
        if img.get("type") in ["DieselStoreFrontWide", "OfferImageWide", "Thumbnail"]:
            return img.get("url")
    return None


def get_slug(game):
    mappings = game.get("catalogNs", {}).get("mappings") or []
    for m in mappings:
        slug = m.get("pageSlug")
        if slug:
            return slug
    return game.get("productSlug")


def detect_platform(game):
    text = json.dumps(game).lower()
    platforms = []

    if "ios" in text or "iphone" in text or "ipad" in text:
        platforms.append("🍎 iOS")

    if "android" in text:
        platforms.append("🤖 Android")

    slug = get_slug(game) or ""
    if "android" in slug.lower() and "🤖 Android" not in platforms:
        platforms.append("🤖 Android")
    if "ios" in slug.lower() and "🍎 iOS" not in platforms:
        platforms.append("🍎 iOS")

    return " + ".join(platforms) if platforms else None


def is_free_now(game):
    promos = game.get("promotions") or {}
    current = promos.get("promotionalOffers") or []

    for block in current:
        for offer in block.get("promotionalOffers", []):
            discount = offer.get("discountSetting", {})
            if discount.get("discountPercentage") == 0:
                return offer

    return None


def send_discord(game, offer, platform):
    title = game.get("title", "Unknown Game")
    slug = get_slug(game)
    link = f"https://store.epicgames.com/p/{slug}" if slug else "https://store.epicgames.com/mobile"

    image = get_image(game)
    end_ts = unix_time(offer.get("endDate"))

    original_price = game.get("price", {}).get("totalPrice", {}).get("fmtPrice", {}).get("originalPrice")
    discount_text = "-100%"
    if original_price:
        discount_text += f" was {original_price}"

    end_text = f"<t:{end_ts}:F>\n<t:{end_ts}:R>" if end_ts else "Unknown"

    embed = {
        "title": "Epic Games - Mobile Free Games",
        "url": link,
        "color": 0x2f80ed,
        "thumbnail": {
            "url": "https://cdn2.unrealengine.com/epic-games-store-logo-340x340-340x340-566a0f62ad4f.png"
        },
        "fields": [
            {
                "name": title,
                "value": f"[Open Store Page]({link})",
                "inline": False
            },
            {
                "name": "Platform",
                "value": platform,
                "inline": True
            },
            {
                "name": "Discount",
                "value": discount_text,
                "inline": True
            },
            {
                "name": "End at",
                "value": end_text,
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

    payload = {"embeds": [embed]}
    r = requests.post(WEBHOOK, json=payload, timeout=20)
    r.raise_for_status()


def main():
    if not WEBHOOK:
        raise SystemExit("DISCORD_WEBHOOK secret is missing")

    seen = load_seen()

    r = requests.get(API, headers=HEADERS, timeout=30)
    r.raise_for_status()

    data = r.json()
    games = data["data"]["Catalog"]["searchStore"]["elements"]

    found = 0

    for game in games:
        offer = is_free_now(game)
        if not offer:
            continue

        platform = detect_platform(game)
        if not platform:
            continue

        game_id = game.get("id") or game.get("namespace") or game.get("title")
        end_date = offer.get("endDate", "")
        seen_key = f"{game_id}:{end_date}:{platform}"

        if seen_key in seen:
            continue

        print(f"Posting mobile freebie: {game.get('title')} | {platform}")
        send_discord(game, offer, platform)

        seen.add(seen_key)
        found += 1
        time.sleep(1)

    save_seen(seen)
    print(f"Done. New mobile freebies posted: {found}")


if __name__ == "__main__":
    main()

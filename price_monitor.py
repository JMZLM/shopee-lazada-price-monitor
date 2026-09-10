import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


CONFIG_FILE = Path("config/products.json")
STATE_FILE = Path("data/prices.json")

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"


def load_json(path, default):
    if not path.exists():
        return default

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def extract_price_from_text(text):
    """
    Find Philippine peso prices such as:
    ₱499
    ₱499.00
    ₱ 499
    ₱1,299.00
    """

    patterns = [
        r"₱\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        r"PHP\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)

        for value in matches:
            try:
                value = value.replace(",", "")
                price = float(value)

                # Ignore obviously unrelated tiny/huge numbers.
                if 1 <= price <= 1_000_000:
                    return price

            except ValueError:
                pass

    return None


def extract_price(page):
    # 1. Try itemprop="price"
    try:
        locator = page.locator('meta[itemprop="price"]').first

        if locator.count() > 0:
            value = locator.get_attribute("content")

            if value:
                price = float(value.replace(",", ""))
                if price > 0:
                    return price
    except Exception:
        pass

    # 2. Try JSON-LD Product/Offer data
    try:
        scripts = page.locator('script[type="application/ld+json"]').all_text_contents()

        for raw in scripts:
            try:
                data = json.loads(raw)

                objects = data if isinstance(data, list) else [data]

                for obj in objects:
                    if not isinstance(obj, dict):
                        continue

                    offers = obj.get("offers")

                    if isinstance(offers, dict):
                        price = offers.get("price")

                        if price:
                            price = float(str(price).replace(",", ""))
                            if price > 0:
                                return price

                    if isinstance(offers, list):
                        for offer in offers:
                            if isinstance(offer, dict) and offer.get("price"):
                                price = float(
                                    str(offer["price"]).replace(",", "")
                                )

                                if price > 0:
                                    return price

            except Exception:
                continue

    except Exception:
        pass

    # 3. Fall back to rendered page text
    try:
        text = page.locator("body").inner_text(timeout=10000)
        return extract_price_from_text(text)
    except Exception:
        return None


def get_product(page, product):
    url = product["url"]

    print(f"\nChecking: {product['name']}")
    print(f"Store: {product['store']}")
    print(f"URL: {url}")

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        # Give client-side JavaScript time to render.
        page.wait_for_timeout(5000)

        title = page.title()

        price = extract_price(page)

        if price is None:
            return {
                "success": False,
                "error": "Price could not be detected",
                "title": title,
            }

        return {
            "success": True,
            "title": title,
            "price": price,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def send_ntfy(message):
    response = requests.post(
        NTFY_URL,
        data=message.encode("utf-8"),
        headers={
            "Title": "Shopee/Lazada Price Monitor",
            "Priority": "default",
            "Tags": "shopping_cart",
        },
        timeout=30,
    )

    response.raise_for_status()


def main():
    config = load_json(CONFIG_FILE, {"products": []})
    state = load_json(STATE_FILE, {"products": {}})

    state.setdefault("products", {})

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True
        )

        context = browser.new_context(
            locale="en-PH",
            timezone_id="Asia/Manila",
            viewport={
                "width": 1366,
                "height": 768
            },
        )

        page = context.new_page()

        for product in config["products"]:
            result = get_product(page, product)

            product_id = product["id"]

            now = datetime.now(timezone.utc).isoformat()

            if result["success"]:
                price = result["price"]

                print(
                    f"FOUND PRICE: ₱{price:,.2f}"
                )

                product_state = state["products"].setdefault(
                    product_id,
                    {
                        "history": []
                    }
                )

                product_state.setdefault(
                    "history",
                    []
                )

                product_state["history"].append(
                    {
                        "timestamp": now,
                        "price": price
                    }
                )

                # Keep the last 100 price records.
                product_state["history"] = (
                    product_state["history"][-100:]
                )

                product_state["last_price"] = price
                product_state["last_checked"] = now

                results.append(
                    f"🛒 {product['name']}\n"
                    f"Store: {product['store'].title()}\n"
                    f"Price: ₱{price:,.2f}"
                )

            else:
                print(
                    f"FAILED: {result.get('error')}"
                )

                results.append(
                    f"❌ {product['name']}\n"
                    f"Store: {product['store'].title()}\n"
                    f"Unable to retrieve price.\n"
                    f"Reason: {result.get('error', 'Unknown error')}"
                )

        browser.close()

    save_json(STATE_FILE, state)

    message = (
        "🛒 PRICE CHECK TEST\n\n"
        + "\n\n".join(results)
    )

    print("\nSending ntfy notification...")
    print(message)

    send_ntfy(message)

    print("Done.")


if __name__ == "__main__":
    main()

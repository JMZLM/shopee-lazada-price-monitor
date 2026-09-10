import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


CONFIG_FILE = Path("config/products.json")
STATE_FILE = Path("data/prices.json")
DEBUG_DIR = Path("debug")

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


def debug_page(page, product_id):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    print("\n========== DEBUG INFORMATION ==========")
    print(f"Final URL: {page.url}")
    print(f"Page title: {page.title()}")

    # Save screenshot
    screenshot_file = DEBUG_DIR / f"{product_id}.png"

    page.screenshot(
        path=str(screenshot_file),
        full_page=True
    )

    print(f"Screenshot saved: {screenshot_file}")

    # Save HTML
    html_file = DEBUG_DIR / f"{product_id}.html"

    html = page.content()

    html_file.write_text(
        html,
        encoding="utf-8"
    )

    print(f"HTML saved: {html_file}")

    # Get visible text
    try:
        text = page.locator("body").inner_text(
            timeout=10000
        )

        text_file = DEBUG_DIR / f"{product_id}.txt"

        text_file.write_text(
            text,
            encoding="utf-8"
        )

        print(f"Text saved: {text_file}")

        print("\n----- PAGE TEXT PREVIEW -----")
        print(text[:5000])
        print("----- END PAGE TEXT PREVIEW -----")

    except Exception as e:
        print(f"Could not retrieve page text: {e}")

    print("=======================================\n")


def get_product(page, product):
    product_id = product["id"]
    url = product["url"]

    print("\n")
    print("=======================================")
    print(f"Checking: {product['name']}")
    print(f"Store: {product['store']}")
    print(f"URL: {url}")
    print("=======================================")

    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        print("Initial page loaded.")

        # Allow JavaScript and redirects to finish.
        page.wait_for_timeout(10000)

        debug_page(
            page,
            product_id
        )

        return {
            "success": False,
            "error": "Debug run - price extraction disabled",
            "title": page.title(),
            "url": page.url
        }

    except Exception as e:

        print(f"ERROR: {e}")

        return {
            "success": False,
            "error": str(e)
        }


def send_ntfy(message):
    response = requests.post(
        NTFY_URL,
        data=message.encode("utf-8"),
        headers={
            "Title": "Price Monitor Debug",
            "Priority": "default",
            "Tags": "mag",
        },
        timeout=30,
    )

    response.raise_for_status()


def main():

    config = load_json(
        CONFIG_FILE,
        {"products": []}
    )

    state = load_json(
        STATE_FILE,
        {"products": {}}
    )

    state.setdefault(
        "products",
        {}
    )

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
            user_agent=(
                "Mozilla/5.0 "
                "(X11; Linux x86_64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/140.0.0.0 "
                "Safari/537.36"
            )
        )

        page = context.new_page()

        for product in config["products"]:

            result = get_product(
                page,
                product
            )

            results.append(
                f"🛒 {product['name']}\n"
                f"Store: {product['store'].title()}\n"
                f"Final URL: {result.get('url', 'N/A')}\n"
                f"Page title: {result.get('title', 'N/A')}\n"
                f"Status: Debug information collected"
            )

        browser.close()

    save_json(
        STATE_FILE,
        state
    )

    message = (
        "🔎 PRICE MONITOR DEBUG\n\n"
        + "\n\n".join(results)
    )

    print("\nSending debug notification...")

    send_ntfy(message)

    print("Debug run completed.")


if __name__ == "__main__":
    main()

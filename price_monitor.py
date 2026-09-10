import json
import re
from pathlib import Path

from cloakbrowser import launch


PRODUCTS_FILE = Path("config/products.json")
DEBUG_DIR = Path("debug")


def save_text(product_id, name, content):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    path = DEBUG_DIR / f"{product_id}_{name}.txt"

    path.write_text(
        content,
        encoding="utf-8",
        errors="ignore"
    )


def save_html(product_id, html):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    path = DEBUG_DIR / f"{product_id}.html"

    path.write_text(
        html,
        encoding="utf-8",
        errors="ignore"
    )


def extract_price(text):

    patterns = [
        r"₱\s?([\d,]+(?:\.\d{1,2})?)",
        r"PHP\s?([\d,]+(?:\.\d{1,2})?)",
    ]

    prices = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        for value in matches:

            try:
                price = float(
                    value.replace(",", "")
                )

                prices.append(price)

            except ValueError:
                pass

    if not prices:
        return None

    # Remove obviously unrealistic values.
    prices = [
        p for p in prices
        if 1 <= p <= 1_000_000
    ]

    if not prices:
        return None

    return min(prices)


def main():

    print("==========================================")
    print(" CloakBrowser Marketplace Test")
    print("==========================================")

    products = json.loads(
        PRODUCTS_FILE.read_text(
            encoding="utf-8"
        )
    )["products"]

    browser = launch(
        browser_version="146.0.7680.177.5",
        headless=True,
        humanize=True
    )

    try:

        for product in products:

            product_id = product["id"]
            name = product["name"]
            url = product["url"]

            print()
            print("------------------------------------------")
            print(f"Product: {name}")
            print(f"Store:   {product['store']}")
            print(f"URL:     {url}")
            print("------------------------------------------")

            try:

                page = browser.new_page()

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60_000
                )

                print(
                    f"Final URL: {page.url}"
                )

                # Give marketplace JavaScript
                # time to render.
                page.wait_for_timeout(
                    10_000
                )

                title = page.title()

                print(
                    f"Page title: {title}"
                )

                text = page.locator(
                    "body"
                ).inner_text(
                    timeout=30_000
                )

                html = page.content()

                save_text(
                    product_id,
                    "text",
                    text
                )

                save_html(
                    product_id,
                    html
                )

                price = extract_price(
                    text
                )

                if price is not None:

                    print()
                    print(
                        f"FOUND PRICE: "
                        f"₱{price:,.2f}"
                    )

                else:

                    print()
                    print(
                        "NO PRICE FOUND"
                    )

                print()
                print(
                    "First 2,000 characters "
                    "of page text:"
                )

                print(
                    text[:2000]
                )

                page.close()

            except Exception as e:

                print()
                print(
                    f"ERROR checking "
                    f"{name}:"
                )

                print(
                    str(e)
                )

    finally:

        browser.close()

    print()
    print("==========================================")
    print("CloakBrowser test finished.")
    print("==========================================")


if __name__ == "__main__":
    main()

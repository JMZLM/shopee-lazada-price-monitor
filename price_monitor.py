import json
import re
from pathlib import Path

from cloakbrowser import launch


PRODUCTS_FILE = Path("config/products.json")
DEBUG_DIR = Path("debug")


def save_text(product_id, name, content):
    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    path = DEBUG_DIR / f"{product_id}_{name}.txt"

    path.write_text(
        content,
        encoding="utf-8",
        errors="ignore"
    )


def save_html(product_id, html):
    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    path = DEBUG_DIR / f"{product_id}.html"

    path.write_text(
        html,
        encoding="utf-8",
        errors="ignore"
    )


def extract_prices(text):

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

                if 1 <= price <= 1_000_000:
                    prices.append(price)

            except ValueError:
                pass

    return prices


def main():

    print(
        "=========================================="
    )

    print(
        " CloakBrowser Marketplace Test"
    )

    print(
        "=========================================="
    )

    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    config = json.loads(
        PRODUCTS_FILE.read_text(
            encoding="utf-8"
        )
    )

    products = config.get(
        "products",
        []
    )

    if not products:

        print(
            "No products found."
        )

        return

    print()
    print(
        "Launching CloakBrowser..."
    )

    # IMPORTANT:
    # Do not specify browser_version here.
    # The installed CloakBrowser version
    # selects the browser automatically.

    browser = launch(
        headless=True,
        humanize=True
    )

    try:

        for product in products:

            product_id = product["id"]

            name = product["name"]

            store = product["store"]

            url = product["url"]

            print()
            print(
                "------------------------------------------"
            )

            print(
                f"Product: {name}"
            )

            print(
                f"Store:   {store}"
            )

            print(
                f"URL:     {url}"
            )

            print(
                "------------------------------------------"
            )

            page = None

            try:

                # -----------------------------------------
                # OPEN PAGE
                # -----------------------------------------

                print(
                    "Opening marketplace page..."
                )

                page = browser.new_page()

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60_000
                )

                print(
                    f"Final URL: {page.url}"
                )

                # -----------------------------------------
                # WAIT FOR JAVASCRIPT
                # -----------------------------------------

                print(
                    "Waiting for page to render..."
                )

                page.wait_for_timeout(
                    10_000
                )

                # -----------------------------------------
                # PAGE TITLE
                # -----------------------------------------

                title = page.title()

                print(
                    f"Page title: {title}"
                )

                # -----------------------------------------
                # BODY TEXT
                # -----------------------------------------

                print(
                    "Reading page text..."
                )

                text = page.locator(
                    "body"
                ).inner_text(
                    timeout=30_000
                )

                # -----------------------------------------
                # HTML
                # -----------------------------------------

                print(
                    "Saving debug HTML..."
                )

                html = page.content()

                save_html(
                    product_id,
                    html
                )

                save_text(
                    product_id,
                    "text",
                    text
                )

                # -----------------------------------------
                # FIND PRICES
                # -----------------------------------------

                prices = extract_prices(
                    text
                )

                print()

                if prices:

                    print(
                        "Prices found on page:"
                    )

                    for price in prices:

                        print(
                            f"  ₱{price:,.2f}"
                        )

                    # For this TEST only,
                    # use the lowest price found.
                    lowest_price = min(
                        prices
                    )

                    print()
                    print(
                        f"LOWEST PRICE FOUND: "
                        f"₱{lowest_price:,.2f}"
                    )

                else:

                    print(
                        "NO PRICE FOUND"
                    )

                # -----------------------------------------
                # SHOW PAGE TEXT
                # -----------------------------------------

                print()
                print(
                    "First 3,000 characters "
                    "of page text:"
                )

                print(
                    "------------------------------------------"
                )

                print(
                    text[:3000]
                )

                print(
                    "------------------------------------------"
                )

            except Exception as e:

                print()
                print(
                    f"ERROR checking {name}:"
                )

                print(
                    str(e)
                )

                error_file = (
                    DEBUG_DIR
                    / f"{product_id}_error.txt"
                )

                error_file.write_text(
                    f"Product: {name}\n"
                    f"Store: {store}\n"
                    f"URL: {url}\n\n"
                    f"ERROR:\n{e}\n",
                    encoding="utf-8"
                )

            finally:

                if page is not None:

                    try:
                        page.close()
                    except Exception:
                        pass

    finally:

        print()
        print(
            "Closing CloakBrowser..."
        )

        browser.close()

    print()
    print(
        "=========================================="
    )

    print(
        "CloakBrowser test finished."
    )

    print(
        "=========================================="
    )


if __name__ == "__main__":

    main()

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

PRODUCTS_FILE = Path("config/products.json")
STATE_FILE = Path("data/prices.json")
DEBUG_DIR = Path("debug")

PRICEWATCHA_BASE = "https://pricewatcha.com/api/v1"
NTFY_URL = "https://ntfy.sh"

POLL_INTERVAL = 5
MAX_POLLS = 8


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def safe_filename(value):
    return "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in value
    )


def send_ntfy(title, message, priority="default", tags="shopping_cart"):
    topic = os.getenv("NTFY_TOPIC")

    if not topic:
        print("NTFY_TOPIC is not configured.")
        return

    url = f"{NTFY_URL}/{topic}"

    response = requests.post(
        url,
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": tags,
        },
        data=message.encode("utf-8"),
        timeout=30,
    )

    print(f"ntfy response: {response.status_code}")

    response.raise_for_status()


# ---------------------------------------------------------
# PRICEWATCHA
# ---------------------------------------------------------

def track_product(url):
    print(f"Sending product to Pricewatcha:")
    print(url)

    response = requests.post(
        f"{PRICEWATCHA_BASE}/track",
        json={
            "url": url
        },
        timeout=40,
    )

    print(f"Track response: {response.status_code}")
    print(response.text)

    response.raise_for_status()

    return response.json()


def get_job(job_id):
    response = requests.get(
        f"{PRICEWATCHA_BASE}/jobs/{job_id}",
        timeout=30,
    )

    print(f"Job response: {response.status_code}")
    print(response.text)

    response.raise_for_status()

    return response.json()


def get_product(product_id):
    response = requests.get(
        f"{PRICEWATCHA_BASE}/products/{product_id}",
        timeout=30,
    )

    print(f"Product response: {response.status_code}")
    print(response.text)

    response.raise_for_status()

    return response.json()


def get_price_from_result(result):
    product = result.get("product")

    if not product:
        return None

    price = product.get("current_price")

    if price is None:
        return None

    try:
        return float(price)
    except (TypeError, ValueError):
        return None


def get_price(product):
    """
    Send the marketplace URL to Pricewatcha and retrieve
    the current price.
    """

    url = product["url"]

    result = track_product(url)

    status = result.get("status")

    # Fast result
    if status == "completed":
        price = get_price_from_result(result)

        if price is not None:
            return {
                "price": price,
                "product_id": result["product"]["product_id"],
                "product": result["product"],
            }

    # Slow result
    if status == "running":
        job_id = result.get("job_id")

        if not job_id:
            raise RuntimeError(
                "Pricewatcha returned running status without job_id."
            )

        print(f"Pricewatcha job started: {job_id}")

        for attempt in range(MAX_POLLS):
            print(
                f"Waiting for Pricewatcha job "
                f"({attempt + 1}/{MAX_POLLS})..."
            )

            time.sleep(POLL_INTERVAL)

            job = get_job(job_id)

            job_status = job.get("status")

            if job_status == "completed":
                price = get_price_from_result(job)

                if price is None:
                    raise RuntimeError(
                        "Pricewatcha completed the job but no price was returned."
                    )

                product_data = job.get("product", {})

                return {
                    "price": price,
                    "product_id": product_data.get("product_id"),
                    "product": product_data,
                }

            if job_status == "failed":
                raise RuntimeError(
                    f"Pricewatcha job failed: {job}"
                )

        raise RuntimeError(
            "Pricewatcha job did not finish within the allowed time."
        )

    raise RuntimeError(
        f"Unexpected Pricewatcha response: {result}"
    )


# ---------------------------------------------------------
# MAIN MONITOR
# ---------------------------------------------------------

def main():

    print("==========================================")
    print(" Shopee / Lazada Price Monitor")
    print("==========================================")

    PRODUCTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    config = load_json(PRODUCTS_FILE)

    if STATE_FILE.exists():
        state = load_json(STATE_FILE)
    else:
        state = {"products": {}}

    products = config.get("products", [])

    if not products:
        print("No products configured.")
        return

    for product in products:

        product_id = product["id"]
        name = product["name"]
        store = product["store"]
        url = product["url"]
        target_price = product.get("target_price")

        print()
        print("------------------------------------------")
        print(f"Product: {name}")
        print(f"Store:   {store}")
        print(f"URL:     {url}")
        print("------------------------------------------")

        try:

            result = get_price(product)

            current_price = result["price"]
            pricewatcha_product = result.get("product", {})

            print(f"CURRENT PRICE: ₱{current_price:,.2f}")

            # Save raw result for troubleshooting
            debug_file = (
                DEBUG_DIR /
                f"{safe_filename(product_id)}.json"
            )

            save_json(
                debug_file,
                {
                    "checked_at": now_iso(),
                    "config": product,
                    "pricewatcha": pricewatcha_product,
                },
            )

            old_data = state["products"].get(product_id, {})

            previous_price = old_data.get("current_price")

            # ------------------------------------------
            # PRICE HISTORY
            # ------------------------------------------

            history = old_data.get("history", [])

            history.append(
                {
                    "timestamp": now_iso(),
                    "price": current_price,
                }
            )

            # Keep last 500 price records
            history = history[-500:]

            # ------------------------------------------
            # UPDATE STATE
            # ------------------------------------------

            state["products"][product_id] = {
                "name": name,
                "store": store,
                "url": url,
                "current_price": current_price,
                "previous_price": previous_price,
                "target_price": target_price,
                "pricewatcha_product_id": result.get("product_id"),
                "last_checked": now_iso(),
                "history": history,
            }

            # ------------------------------------------
            # PRICE DROP ALERT
            # ------------------------------------------

            if (
                previous_price is not None
                and current_price < previous_price
            ):

                drop = previous_price - current_price

                message = (
                    f"{name}\n\n"
                    f"Store: {store}\n"
                    f"Previous price: ₱{previous_price:,.2f}\n"
                    f"New price: ₱{current_price:,.2f}\n"
                    f"Drop: ₱{drop:,.2f}\n\n"
                    f"{url}"
                )

                send_ntfy(
                    title=f"Price Drop: {name}",
                    message=message,
                    priority="high",
                    tags="chart_with_downwards_trend,shopping_cart",
                )

                print("PRICE DROP NOTIFICATION SENT.")

            # ------------------------------------------
            # TARGET PRICE ALERT
            # ------------------------------------------

            if (
                target_price is not None
                and current_price <= float(target_price)
            ):

                was_already_below_target = (
                    previous_price is not None
                    and previous_price <= float(target_price)
                )

                if not was_already_below_target:

                    message = (
                        f"{name}\n\n"
                        f"Store: {store}\n"
                        f"Current price: ₱{current_price:,.2f}\n"
                        f"Target price: ₱{float(target_price):,.2f}\n\n"
                        f"Target price has been reached!\n\n"
                        f"{url}"
                    )

                    send_ntfy(
                        title=f"Target Price Reached: {name}",
                        message=message,
                        priority="high",
                        tags="tada,shopping_cart",
                    )

                    print("TARGET PRICE NOTIFICATION SENT.")

        except Exception as e:

            print()
            print(f"ERROR checking {name}:")
            print(str(e))

            error_file = (
                DEBUG_DIR /
                f"{safe_filename(product_id)}_error.txt"
            )

            error_file.write_text(
                f"Time: {now_iso()}\n"
                f"Product: {name}\n"
                f"Store: {store}\n"
                f"URL: {url}\n\n"
                f"ERROR:\n{e}\n",
                encoding="utf-8",
            )

            # Don't stop the other products
            continue

    # ------------------------------------------
    # SAVE STATE
    # ------------------------------------------

    save_json(STATE_FILE, state)

    print()
    print("==========================================")
    print("Price monitor finished.")
    print("==========================================")


if __name__ == "__main__":
    main()

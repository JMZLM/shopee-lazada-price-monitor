import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


# =========================================================
# CONFIGURATION
# =========================================================

PRODUCTS_FILE = Path("config/products.json")
STATE_FILE = Path("data/prices.json")
DEBUG_DIR = Path("debug")

PRICEWATCHA_BASE = "https://pricewatcha.com/api/v1"
NTFY_URL = "https://ntfy.sh"

# Pricewatcha can take several minutes for slow marketplace pages.
MAX_WAIT_SECONDS = 600

# Polling interval starts at 5 seconds and gradually increases.
INITIAL_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 30


# =========================================================
# HELPERS
# =========================================================

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


# =========================================================
# PRICEWATCHA
# =========================================================

def track_product(url):

    print("Sending product to Pricewatcha:")
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


def wait_for_job(job_id):

    print()
    print(f"Waiting for Pricewatcha job: {job_id}")

    start_time = time.time()
    poll_interval = INITIAL_POLL_INTERVAL
    attempt = 0

    while True:

        elapsed = time.time() - start_time

        if elapsed >= MAX_WAIT_SECONDS:
            raise RuntimeError(
                f"Pricewatcha job exceeded "
                f"{MAX_WAIT_SECONDS} seconds."
            )

        attempt += 1

        print(
            f"Checking job "
            f"(attempt {attempt}, "
            f"elapsed {int(elapsed)}s)..."
        )

        job = get_job(job_id)

        status = job.get("status")

        print(f"Job status: {status}")

        # -----------------------------------------
        # COMPLETED
        # -----------------------------------------

        if status == "completed":

            product_data = job.get("product")

            if not product_data:
                raise RuntimeError(
                    "Pricewatcha job completed "
                    "but returned no product data."
                )

            return product_data

        # -----------------------------------------
        # FAILED
        # -----------------------------------------

        if status == "failed":

            error = job.get("error")

            raise RuntimeError(
                f"Pricewatcha scraper failed: {error}"
            )

        # -----------------------------------------
        # STILL RUNNING
        # -----------------------------------------

        if status in ("queued", "running"):

            print(
                f"Job still {status}. "
                f"Waiting {poll_interval} seconds..."
            )

            time.sleep(poll_interval)

            # Gradually increase polling interval.
            poll_interval = min(
                poll_interval + 5,
                MAX_POLL_INTERVAL
            )

            continue

        # -----------------------------------------
        # UNKNOWN STATUS
        # -----------------------------------------

        raise RuntimeError(
            f"Unknown Pricewatcha job status: {status}\n"
            f"Full response: {job}"
        )


def get_price(product):

    url = product["url"]

    result = track_product(url)

    status = result.get("status")

    # ---------------------------------------------
    # COMPLETED IMMEDIATELY
    # ---------------------------------------------

    if status == "completed":

        product_data = result.get("product")

        if not product_data:
            raise RuntimeError(
                "Pricewatcha returned completed status "
                "but no product data."
            )

        return product_data

    # ---------------------------------------------
    # ASYNC JOB
    # ---------------------------------------------

    if status in ("running", "queued"):

        job_id = result.get("job_id")

        if not job_id:
            raise RuntimeError(
                "Pricewatcha returned an async status "
                "but no job_id."
            )

        return wait_for_job(job_id)

    # ---------------------------------------------
    # UNEXPECTED
    # ---------------------------------------------

    raise RuntimeError(
        f"Unexpected Pricewatcha response: {result}"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print("==========================================")
    print(" Shopee / Lazada Price Monitor")
    print("==========================================")

    PRODUCTS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    config = load_json(PRODUCTS_FILE)

    if STATE_FILE.exists():
        state = load_json(STATE_FILE)
    else:
        state = {
            "products": {}
        }

    products = config.get("products", [])

    if not products:

        print("No products configured.")

        return

    # =====================================================
    # CHECK EACH PRODUCT
    # =====================================================

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

            # ---------------------------------------------
            # GET PRICE
            # ---------------------------------------------

            product_data = get_price(product)

            current_price = product_data.get(
                "current_price"
            )

            if current_price is None:

                raise RuntimeError(
                    "Pricewatcha returned product data "
                    "but no current_price."
                )

            current_price = float(current_price)

            print()
            print(
                f"CURRENT PRICE: "
                f"₱{current_price:,.2f}"
            )

            # ---------------------------------------------
            # SAVE DEBUG DATA
            # ---------------------------------------------

            debug_file = (
                DEBUG_DIR /
                f"{safe_filename(product_id)}.json"
            )

            save_json(
                debug_file,
                {
                    "checked_at": now_iso(),
                    "config": product,
                    "pricewatcha": product_data,
                }
            )

            # ---------------------------------------------
            # PREVIOUS STATE
            # ---------------------------------------------

            old_data = state["products"].get(
                product_id,
                {}
            )

            previous_price = old_data.get(
                "current_price"
            )

            # ---------------------------------------------
            # PRICE HISTORY
            # ---------------------------------------------

            history = old_data.get(
                "history",
                []
            )

            history.append(
                {
                    "timestamp": now_iso(),
                    "price": current_price
                }
            )

            # Keep latest 500 records.
            history = history[-500:]

            # ---------------------------------------------
            # SAVE CURRENT STATE
            # ---------------------------------------------

            state["products"][product_id] = {

                "name": name,

                "store": store,

                "url": url,

                "current_price": current_price,

                "previous_price": previous_price,

                "target_price": target_price,

                "pricewatcha_product_id":
                    product_data.get("product_id"),

                "last_checked": now_iso(),

                "history": history
            }

            # ---------------------------------------------
            # PRICE DROP
            # ---------------------------------------------

            if (
                previous_price is not None
                and current_price < float(previous_price)
            ):

                drop = (
                    float(previous_price)
                    - current_price
                )

                message = (
                    f"{name}\n\n"
                    f"Store: {store}\n"
                    f"Previous price: "
                    f"₱{float(previous_price):,.2f}\n"
                    f"New price: "
                    f"₱{current_price:,.2f}\n"
                    f"Drop: ₱{drop:,.2f}\n\n"
                    f"{url}"
                )

                send_ntfy(
                    title=f"Price Drop: {name}",
                    message=message,
                    priority="high",
                    tags="chart_with_downwards_trend,shopping_cart"
                )

                print(
                    "PRICE DROP NOTIFICATION SENT."
                )

            # ---------------------------------------------
            # TARGET PRICE
            # ---------------------------------------------

            if target_price is not None:

                target_price = float(
                    target_price
                )

                if current_price <= target_price:

                    was_already_below = (
                        previous_price is not None
                        and float(previous_price)
                        <= target_price
                    )

                    if not was_already_below:

                        message = (
                            f"{name}\n\n"
                            f"Store: {store}\n"
                            f"Current price: "
                            f"₱{current_price:,.2f}\n"
                            f"Target price: "
                            f"₱{target_price:,.2f}\n\n"
                            f"Target price has been reached!\n\n"
                            f"{url}"
                        )

                        send_ntfy(
                            title=(
                                f"Target Price Reached: "
                                f"{name}"
                            ),
                            message=message,
                            priority="high",
                            tags="tada,shopping_cart"
                        )

                        print(
                            "TARGET PRICE "
                            "NOTIFICATION SENT."
                        )

        except Exception as e:

            print()
            print(
                f"ERROR checking {name}:"
            )

            print(str(e))

            # ---------------------------------------------
            # SAVE ERROR
            # ---------------------------------------------

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
                encoding="utf-8"
            )

            # Don't stop other products.
            continue

    # =====================================================
    # SAVE STATE
    # =====================================================

    save_json(
        STATE_FILE,
        state
    )

    print()
    print("==========================================")
    print("Price monitor finished.")
    print("==========================================")


if __name__ == "__main__":
    main()

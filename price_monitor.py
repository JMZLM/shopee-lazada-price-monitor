import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse, parse_qs

import requests


# =========================================================
# FILES
# =========================================================

PRODUCTS_FILE = Path("config/products.json")
STATE_FILE = Path("data/prices.json")
DEBUG_DIR = Path("debug")


# =========================================================
# BIGGO
# =========================================================

BIGGO_REGION = "ph"
BIGGO_DOMAIN = "ph.biggo.com"

BIGGO_STORE_LOOKUP = (
    "https://extension.biggo.com/api/store.php"
)

BIGGO_ECLIST = (
    "https://extension.biggo.com/api/eclist.php"
)

BIGGO_PRICE_HISTORY = (
    "https://extension.biggo.com/api/product_price_history.php"
)

BIGGO_SEARCH = (
    "https://api.biggo.com/api/v1/spa/search"
)


# =========================================================
# NTFY
# =========================================================

NTFY_URL = "https://ntfy.sh"


# =========================================================
# HTTP SESSION
# =========================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140.0 Safari/537.36"
        )
    }
)


# =========================================================
# HELPERS
# =========================================================

def load_json(path):

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def save_json(path, data):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )


def now_iso():

    return datetime.now(
        timezone.utc
    ).isoformat()


def safe_filename(value):

    return "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in value
    )


# =========================================================
# NTFY
# =========================================================

def send_ntfy(
    title,
    message,
    priority="default",
    tags="shopping_cart"
):

    topic = os.getenv("NTFY_TOPIC")

    if not topic:

        print(
            "NTFY_TOPIC is not configured."
        )

        return

    response = SESSION.post(

        f"{NTFY_URL}/{topic}",

        headers={
            "Title": title,
            "Priority": priority,
            "Tags": tags,
        },

        data=message.encode(
            "utf-8"
        ),

        timeout=30
    )

    print(
        f"ntfy response: "
        f"{response.status_code}"
    )

    response.raise_for_status()


# =========================================================
# BIGGO URL RESOLUTION
# =========================================================

def get_biggo_store(url):

    response = SESSION.get(

        BIGGO_STORE_LOOKUP,

        params={
            "method": "domain_lookup",
            "domain": url,
        },

        timeout=30
    )

    print(
        "BigGo store lookup:",
        response.status_code
    )

    response.raise_for_status()

    data = response.json()

    biggo_items = data.get(
        "biggo",
        []
    )

    if not biggo_items:

        raise RuntimeError(
            "BigGo could not identify "
            f"this marketplace URL:\n{url}"
        )

    # Prefer PH result.
    for item in biggo_items:

        if item.get("region") == "ph":

            return item["id"]

    # Otherwise use first result.
    return biggo_items[0]["id"]


# =========================================================
# BIGGO EC LIST
# =========================================================

def get_ec_list():

    response = SESSION.get(
        BIGGO_ECLIST,
        timeout=30
    )

    print(
        "BigGo EC list:",
        response.status_code
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("data"):

        raise RuntimeError(
            "BigGo returned an empty "
            "e-commerce configuration list."
        )

    return data["data"]


# =========================================================
# URL PARSING
# =========================================================

def get_query_variable(
    url,
    field
):

    try:

        parsed = urlparse(url)

        params = parse_qs(
            parsed.query
        )

        values = params.get(
            field,
            []
        )

        if values:

            return values[0]

    except Exception:

        pass

    return None


def extract_id(
    url,
    pattern,
    template="%1",
    config=None
):

    match = re.search(
        pattern,
        url
    )

    if not match:

        return None

    groups = match.groups()

    if not groups:

        return None

    pid = template

    for index, value in enumerate(
        groups,
        start=1
    ):

        pid = pid.replace(
            f"%{index}",
            value
        )

    # Padding support used by BigGo.
    if (
        config
        and config.get("len")
        and "%p" in pid
    ):

        desired_length = config["len"]

        current_length = (
            len(pid.replace("%p", ""))
        )

        padding_length = (
            desired_length
            - current_length
            + 2
        )

        if padding_length > 0:

            pad = config.get(
                "pad",
                ""
            )

            pid = pid.replace(
                "%p",
                str(pad) * padding_length
            )

    if (
        config
        and config.get("uppercase")
    ):

        pid = pid.upper()

    if (
        config
        and config.get("lowercase")
    ):

        pid = pid.lower()

    return pid


def parse_product_id(
    url,
    nindex,
    ec_list
):

    region = nindex.split(
        "_"
    )[0]

    region_config = ec_list.get(
        region
    )

    if not region_config:

        raise RuntimeError(
            f"BigGo has no URL rules "
            f"for region: {region}"
        )

    config = region_config.get(
        nindex
    )

    if not config:

        raise RuntimeError(
            f"BigGo has no URL rules "
            f"for store: {nindex}"
        )

    patterns = config.get(
        "match",
        ""
    )

    templates = config.get(
        "template",
        "%1"
    )

    if not isinstance(
        patterns,
        list
    ):

        patterns = [patterns]

    if not isinstance(
        templates,
        list
    ):

        templates = [templates]

    # Try regex patterns.
    for index, pattern in enumerate(
        patterns
    ):

        if not pattern:

            continue

        template = (
            templates[index]
            if index < len(templates)
            else templates[0]
        )

        pid = extract_id(
            url,
            pattern,
            template,
            config
        )

        if pid:

            return pid

    # Try query-string ID.
    query_name = config.get(
        "query",
        ""
    )

    if query_name:

        pid = get_query_variable(
            url,
            query_name
        )

        if pid:

            return pid

    raise RuntimeError(
        "BigGo could not extract "
        f"the product ID from:\n{url}"
    )


# =========================================================
# BIGGO PRICE HISTORY
# =========================================================

def get_price_history(
    nindex,
    product_id
):

    history_id = (
        f"{nindex}-{product_id}"
    )

    print(
        f"BigGo history ID: "
        f"{history_id}"
    )

    response = SESSION.post(

        BIGGO_PRICE_HISTORY,

        json={
            "item": [
                history_id
            ],
            "days": 180
        },

        timeout=30
    )

    print(
        "BigGo price history:",
        response.status_code
    )

    response.raise_for_status()

    data = response.json()

    if data.get("result") is False:

        return None

    return data


def extract_current_price(
    data,
    history_id
):

    if not data:

        return None

    # BigGo returns the history data
    # keyed by history ID.
    item = data.get(
        history_id
    )

    if not item:

        # Sometimes the API may return
        # another key. Try the first item.
        values = list(
            data.values()
        )

        if not values:

            return None

        item = values[0]

    price = item.get(
        "current_price"
    )

    if price is None:

        return None

    try:

        return float(price)

    except (
        TypeError,
        ValueError
    ):

        return None


# =========================================================
# GET PRICE FROM BIGGO
# =========================================================

def get_price(
    product
):

    url = product["url"]

    print()
    print(
        "Resolving URL through BigGo:"
    )

    print(url)

    # -----------------------------------------------------
    # Identify marketplace
    # -----------------------------------------------------

    nindex = get_biggo_store(
        url
    )

    print(
        f"BigGo store: {nindex}"
    )

    # -----------------------------------------------------
    # Get BigGo marketplace rules
    # -----------------------------------------------------

    ec_list = get_ec_list()

    # -----------------------------------------------------
    # Extract marketplace product ID
    # -----------------------------------------------------

    product_id = parse_product_id(
        url,
        nindex,
        ec_list
    )

    print(
        f"BigGo product ID: "
        f"{product_id}"
    )

    # -----------------------------------------------------
    # Get price history
    # -----------------------------------------------------

    history_id = (
        f"{nindex}-{product_id}"
    )

    data = get_price_history(
        nindex,
        product_id
    )

    current_price = (
        extract_current_price(
            data,
            history_id
        )
    )

    if current_price is None:

        raise RuntimeError(
            "BigGo recognized the product "
            "but did not return a current price."
        )

    return {
        "price": current_price,
        "nindex": nindex,
        "product_id": product_id,
        "history_id": history_id,
        "raw": data,
    }


# =========================================================
# MAIN MONITOR
# =========================================================

def main():

    print(
        "=========================================="
    )

    print(
        " Shopee / Lazada Price Monitor"
    )

    print(
        " BigGo Price Source"
    )

    print(
        "=========================================="
    )

    DEBUG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    state = (
        load_json(STATE_FILE)
        if STATE_FILE.exists()
        else {
            "products": {}
        }
    )

    config = load_json(
        PRODUCTS_FILE
    )

    products = config.get(
        "products",
        []
    )

    if not products:

        print(
            "No products configured."
        )

        return

    # =====================================================
    # CHECK PRODUCTS
    # =====================================================

    for product in products:

        product_id = product["id"]

        name = product["name"]

        store = product["store"]

        url = product["url"]

        target_price = (
            product.get(
                "target_price"
            )
        )

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

        try:

            # -------------------------------------------------
            # GET PRICE
            # -------------------------------------------------

            result = get_price(
                product
            )

            current_price = (
                result["price"]
            )

            print()
            print(
                f"CURRENT PRICE: "
                f"₱{current_price:,.2f}"
            )

            # -------------------------------------------------
            # DEBUG
            # -------------------------------------------------

            debug_file = (
                DEBUG_DIR
                / f"{safe_filename(product_id)}.json"
            )

            save_json(
                debug_file,
                {
                    "checked_at": now_iso(),
                    "config": product,
                    "biggo": result,
                }
            )

            # -------------------------------------------------
            # OLD STATE
            # -------------------------------------------------

            old_data = (
                state["products"].get(
                    product_id,
                    {}
                )
            )

            previous_price = (
                old_data.get(
                    "current_price"
                )
            )

            # -------------------------------------------------
            # HISTORY
            # -------------------------------------------------

            history = (
                old_data.get(
                    "history",
                    []
                )
            )

            history.append(
                {
                    "timestamp": now_iso(),
                    "price": current_price
                }
            )

            # Keep last 500 records.
            history = history[-500:]

            # -------------------------------------------------
            # SAVE STATE
            # -------------------------------------------------

            state["products"][product_id] = {

                "name": name,

                "store": store,

                "url": url,

                "current_price":
                    current_price,

                "previous_price":
                    previous_price,

                "target_price":
                    target_price,

                "biggo_nindex":
                    result["nindex"],

                "biggo_product_id":
                    result["product_id"],

                "last_checked":
                    now_iso(),

                "history":
                    history
            }

            # -------------------------------------------------
            # PRICE DROP ALERT
            # -------------------------------------------------

            if (
                previous_price is not None
                and current_price
                < float(previous_price)
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
                    f"Drop: "
                    f"₱{drop:,.2f}\n\n"
                    f"{url}"
                )

                send_ntfy(
                    title=(
                        f"Price Drop: {name}"
                    ),
                    message=message,
                    priority="high",
                    tags=(
                        "chart_with_downwards_trend,"
                        "shopping_cart"
                    )
                )

                print(
                    "PRICE DROP "
                    "NOTIFICATION SENT."
                )

            # -------------------------------------------------
            # TARGET PRICE ALERT
            # -------------------------------------------------

            if target_price is not None:

                target_price = float(
                    target_price
                )

                if (
                    current_price
                    <= target_price
                ):

                    was_already_below = (
                        previous_price
                        is not None
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
                            f"Target price "
                            f"has been reached!\n\n"
                            f"{url}"
                        )

                        send_ntfy(
                            title=(
                                "Target Price Reached: "
                                f"{name}"
                            ),
                            message=message,
                            priority="high",
                            tags=(
                                "tada,"
                                "shopping_cart"
                            )
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

            print(
                str(e)
            )

            error_file = (
                DEBUG_DIR
                / f"{safe_filename(product_id)}_error.txt"
            )

            error_file.write_text(
                f"Time: {now_iso()}\n"
                f"Product: {name}\n"
                f"Store: {store}\n"
                f"URL: {url}\n\n"
                f"ERROR:\n{e}\n",
                encoding="utf-8"
            )

            # Continue to next product.
            continue

    # =====================================================
    # SAVE STATE
    # =====================================================

    save_json(
        STATE_FILE,
        state
    )

    print()
    print(
        "=========================================="
    )

    print(
        "Price monitor finished."
    )

    print(
        "=========================================="
    )


if __name__ == "__main__":

    main()

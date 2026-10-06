import os
import re
import csv
import json
import time
import string
import subprocess
from datetime import datetime

import requests
import urllib3
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

SEARCH_URL = (
    "https://drugeye.pharorg.com/"
    "drugeyeapp/android-search/"
    "drugeye-android-live-go.aspx"
)

DETAIL_URL = (
    "https://drugeye.pharorg.com/"
    "drugeyeapp/android-search/apiforus/gi.aspx"
)

OUTPUT_DIR = "drug_eye_output"

PRODUCTS_FILE = os.path.join(
    OUTPUT_DIR,
    "products.json"
)

DETAILS_FILE = os.path.join(
    OUTPUT_DIR,
    "drug_details.json"
)

CSV_FILE = os.path.join(
    OUTPUT_DIR,
    "drug_details.csv"
)

PRICE_HISTORY_FILE = os.path.join(
    OUTPUT_DIR,
    "price_history.csv"
)

NEW_PRODUCTS_FILE = os.path.join(
    OUTPUT_DIR,
    "new_products.csv"
)

CHANGED_PRODUCTS_FILE = os.path.join(
    OUTPUT_DIR,
    "changed_products.csv"
)

REMOVED_PRODUCTS_FILE = os.path.join(
    OUTPUT_DIR,
    "removed_products.csv"
)

UPDATE_STATE_FILE = os.path.join(
    OUTPUT_DIR,
    "update_state.json"
)


# Maximum results returned by DrugEye for one search.
MAX_RESULTS = 100

# Characters for prefix expansion.
SEARCH_CHARS = (
    string.ascii_uppercase +
    string.digits
)

REQUEST_DELAY = 0.4
DETAIL_DELAY = 0.4

MAX_REQUEST_RETRIES = 5

# Prefix length safety limit.
MAX_PREFIX_LENGTH = 8


# ============================================================
# HTTP
# ============================================================

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),

    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,"
        "*/*;q=0.8"
    ),

    "Accept-Language": "en-US,en;q=0.9",

    "Connection": "keep-alive",
})


# ============================================================
# GENERAL HELPERS
# ============================================================

def now_string():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def date_string():

    return datetime.now().strftime(
        "%Y-%m-%d"
    )


def clean_text(value):

    if value is None:
        return ""

    value = value.replace(
        "\xa0",
        " "
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


# ============================================================
# WINDOWS SAFE JSON SAVE
# ============================================================

def save_json(path, data):

    directory = os.path.dirname(path)

    if directory:
        os.makedirs(
            directory,
            exist_ok=True
        )

    temp_path = (
        path +
        ".tmp"
    )

    with open(
        temp_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

        f.flush()

        try:
            os.fsync(
                f.fileno()
            )
        except Exception:
            pass

    for attempt in range(10):

        try:

            if os.path.exists(path):

                try:
                    os.chmod(
                        path,
                        0o666
                    )
                except Exception:
                    pass

            os.replace(
                temp_path,
                path
            )

            return

        except PermissionError:

            if attempt < 9:

                time.sleep(
                    0.5
                )

                continue

            # Final fallback.
            with open(
                path,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    data,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            if os.path.exists(
                temp_path
            ):

                try:
                    os.remove(
                        temp_path
                    )
                except Exception:
                    pass

            return

        except OSError:

            if attempt < 9:

                time.sleep(
                    0.5
                )

                continue

            raise


def load_json(
    path,
    default
):

    if not os.path.exists(path):

        return default

    try:

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception as e:

        print(
            f"WARNING: Could not load "
            f"{path}: {e}"
        )

        return default


# ============================================================
# HTTP RETRIES
# ============================================================

def http_get(
    url,
    params=None,
    timeout=60
):

    last_error = None

    for attempt in range(
        1,
        MAX_REQUEST_RETRIES + 1
    ):

        try:

            response = session.get(
                url,
                params=params,
                timeout=timeout,
                verify=False
            )

            response.raise_for_status()

            return response

        except Exception as e:

            last_error = e

            print(
                f"  GET retry "
                f"{attempt}/{MAX_REQUEST_RETRIES}: "
                f"{e}"
            )

            if attempt < MAX_REQUEST_RETRIES:

                time.sleep(
                    attempt * 2
                )

    raise last_error


def http_post(
    url,
    data,
    timeout=60
):

    last_error = None

    for attempt in range(
        1,
        MAX_REQUEST_RETRIES + 1
    ):

        try:

            response = session.post(
                url,
                data=data,
                timeout=timeout,
                verify=False
            )

            response.raise_for_status()

            return response

        except Exception as e:

            last_error = e

            print(
                f"  POST retry "
                f"{attempt}/{MAX_REQUEST_RETRIES}: "
                f"{e}"
            )

            if attempt < MAX_REQUEST_RETRIES:

                time.sleep(
                    attempt * 2
                )

    raise last_error


# ============================================================
# LOAD DATABASE
# ============================================================

def load_database():

    products = load_json(
        PRODUCTS_FILE,
        {}
    )

    details = load_json(
        DETAILS_FILE,
        {}
    )

    return products, details


# ============================================================
# GET FRESH SEARCH FORM
# ============================================================

def get_fresh_form():

    response = http_get(
        SEARCH_URL,
        timeout=30
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    form = soup.find(
        "form",
        attrs={
            "id": "form1"
        }
    )

    if form is None:

        form = soup.find(
            "form"
        )

    if form is None:

        raise RuntimeError(
            "DrugEye search form was not found."
        )

    data = {}

    # Inputs.
    for inp in form.find_all(
        "input"
    ):

        name = inp.get(
            "name"
        )

        if not name:
            continue

        input_type = (
            inp.get(
                "type"
            )
            or "text"
        ).lower()

        if input_type in (
            "hidden",
            "text",
            "password"
        ):

            data[name] = inp.get(
                "value",
                ""
            )

    # Textareas.
    for textarea in form.find_all(
        "textarea"
    ):

        name = textarea.get(
            "name"
        )

        if name:

            data[name] = (
                textarea.get_text()
            )

    # Selects.
    for select in form.find_all(
        "select"
    ):

        name = select.get(
            "name"
        )

        if not name:
            continue

        selected = select.find(
            "option",
            selected=True
        )

        if selected is None:

            selected = select.find(
                "option"
            )

        if selected:

            data[name] = selected.get(
                "value",
                ""
            )

        else:

            data[name] = ""

    return data


# ============================================================
# PARSE SEARCH RESULTS
# ============================================================

def parse_search_products(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    table = soup.select_one(
        "#MyTable"
    )

    if table is None:

        return []

    products = []

    rows = table.find_all(
        "tr",
        recursive=False
    )

    for row in rows:

        cells = row.find_all(
            "td",
            recursive=False
        )

        if len(cells) != 2:
            continue

        first = cells[0]
        second = cells[1]

        classes = first.get(
            "class",
            []
        )

        if "mitrfont" not in classes:
            continue

        name = clean_text(
            first.get_text(
                " ",
                strip=True
            )
        )

        price = clean_text(
            second.get_text(
                " ",
                strip=True
            )
        )

        if not name:
            continue

        if not re.fullmatch(
            r"\d+(?:\.\d+)?",
            price
        ):
            continue

        products.append({
            "name": name,
            "price": price
        })

    return products


# ============================================================
# SEARCH PREFIX
# ============================================================

def search_prefix(
    prefix
):

    form_data = get_fresh_form()

    form_data[
        "ttt"
    ] = prefix

    form_data[
        "b1"
    ] = "wait..."

    form_data[
        "TttHelper"
    ] = "drug eye welcome you"

    form_data[
        "Passgenericname"
    ] = ""

    response = http_post(
        SEARCH_URL,
        form_data,
        timeout=60
    )

    products = parse_search_products(
        response.text
    )

    return (
        products,
        len(response.text)
    )


# ============================================================
# DETAIL PAGE
# ============================================================

def get_drug_detail(
    drug_name
):

    params = {
        "passed": drug_name
    }

    response = http_get(
        DETAIL_URL,
        params=params,
        timeout=60
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    table = soup.select_one(
        "#MyTable"
    )

    data = {

        "search_name":
            drug_name,

        "name":
            "",

        "price":
            "",

        "information":
            "",

        "category":
            ""
    }

    if table is None:

        return data

    rows = table.find_all(
        "tr",
        recursive=False
    )

    if len(rows) >= 1:

        cells = rows[0].find_all(
            "td",
            recursive=False
        )

        if len(cells) >= 2:

            data["name"] = clean_text(
                cells[0].get_text(
                    " ",
                    strip=True
                )
            )

            data["price"] = clean_text(
                cells[1].get_text(
                    " ",
                    strip=True
                )
            )

    if len(rows) >= 2:

        cells = rows[1].find_all(
            "td",
            recursive=False
        )

        if cells:

            data["information"] = clean_text(
                cells[0].get_text(
                    " ",
                    strip=True
                )
            )

    if len(rows) >= 3:

        cells = rows[2].find_all(
            "td",
            recursive=False
        )

        if cells:

            data["category"] = clean_text(
                cells[0].get_text(
                    " ",
                    strip=True
                )
            )

    return data


# ============================================================
# CSV HELPERS
# ============================================================

def append_csv_row(
    path,
    fieldnames,
    row
):

    file_exists = os.path.exists(
        path
    )

    with open(
        path,
        "a",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames
        )

        if not file_exists:

            writer.writeheader()

        writer.writerow({
            field:
                row.get(
                    field,
                    ""
                )
            for field in fieldnames
        })


def export_details_csv(
    details
):

    fieldnames = [
        "search_name",
        "name",
        "price",
        "information",
        "category"
    ]

    with open(
        CSV_FILE,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames
        )

        writer.writeheader()

        for key in sorted(details):

            row = details[key]

            writer.writerow({
                field:
                    row.get(
                        field,
                        ""
                    )
                for field in fieldnames
            })

    print(
        f"CSV exported: "
        f"{os.path.abspath(CSV_FILE)}"
    )


# ============================================================
# UPDATE PRICE HISTORY
# ============================================================

def record_price_change(
    product,
    old_price,
    new_price
):

    append_csv_row(
        PRICE_HISTORY_FILE,

        [
            "date",
            "timestamp",
            "product",
            "old_price",
            "new_price"
        ],

        {
            "date":
                date_string(),

            "timestamp":
                now_string(),

            "product":
                product,

            "old_price":
                old_price,

            "new_price":
                new_price
        }
    )


# ============================================================
# PRICE UPDATE
# ============================================================

def update_prices():

    products, details = load_database()

    if not products:

        print(
            "No products.json found."
        )

        return

    names = sorted(
        products.keys()
    )

    total = len(names)

    checked = 0
    changed = 0
    information_changed = 0
    unchanged = 0
    errors = 0

    print()
    print("=" * 70)
    print("PRICE / DETAIL UPDATE")
    print("=" * 70)

    print(
        f"Products to check: {total}"
    )

    print()

    for index, name in enumerate(
        names,
        start=1
    ):

        print(
            f"[{index}/{total}] {name}"
        )

        try:

            new_data = get_drug_detail(
                name
            )

            old_data = details.get(
                name,
                {}
            )

            old_price = clean_text(
                old_data.get(
                    "price",
                    products[name].get(
                        "price",
                        ""
                    )
                )
            )

            new_price = clean_text(
                new_data.get(
                    "price",
                    ""
                )
            )

            old_information = clean_text(
                old_data.get(
                    "information",
                    ""
                )
            )

            new_information = clean_text(
                new_data.get(
                    "information",
                    ""
                )
            )

            old_category = clean_text(
                old_data.get(
                    "category",
                    ""
                )
            )

            new_category = clean_text(
                new_data.get(
                    "category",
                    ""
                )
            )

            price_changed = (
                old_price != new_price
            )

            info_changed = (
                old_information !=
                new_information
            )

            category_changed = (
                old_category !=
                new_category
            )

            # ----------------------------------------------
            # PRICE CHANGE
            # ----------------------------------------------

            if price_changed:

                changed += 1

                print(
                    f"  PRICE: "
                    f"{old_price} "
                    f"-> "
                    f"{new_price}"
                )

                record_price_change(
                    name,
                    old_price,
                    new_price
                )

                append_csv_row(
                    CHANGED_PRODUCTS_FILE,

                    [
                        "date",
                        "timestamp",
                        "product",
                        "old_price",
                        "new_price",
                        "old_information",
                        "new_information",
                        "old_category",
                        "new_category"
                    ],

                    {
                        "date":
                            date_string(),

                        "timestamp":
                            now_string(),

                        "product":
                            name,

                        "old_price":
                            old_price,

                        "new_price":
                            new_price,

                        "old_information":
                            old_information,

                        "new_information":
                            new_information,

                        "old_category":
                            old_category,

                        "new_category":
                            new_category
                    }
                )

            # ----------------------------------------------
            # INFORMATION CHANGE
            # ----------------------------------------------

            if (
                info_changed or
                category_changed
            ):

                information_changed += 1

                print(
                    "  Other details changed."
                )

            # ----------------------------------------------
            # NO CHANGE
            # ----------------------------------------------

            if not (
                price_changed or
                info_changed or
                category_changed
            ):

                unchanged += 1

            # ----------------------------------------------
            # Update stored data
            # ----------------------------------------------

            details[name] = new_data

            products[name]["price"] = (
                new_price
            )

            checked += 1

            # ----------------------------------------------
            # Save periodically
            # ----------------------------------------------

            if (
                checked % 25 == 0
                or index == total
            ):

                save_json(
                    PRODUCTS_FILE,
                    products
                )

                save_json(
                    DETAILS_FILE,
                    details
                )

            time.sleep(
                DETAIL_DELAY
            )

        except KeyboardInterrupt:

            print()
            print(
                "Interrupted."
            )

            save_json(
                PRODUCTS_FILE,
                products
            )

            save_json(
                DETAILS_FILE,
                details
            )

            raise

        except Exception as e:

            errors += 1

            print(
                f"  ERROR: {e}"
            )

            time.sleep(
                1
            )

    # Final save.
    save_json(
        PRODUCTS_FILE,
        products
    )

    save_json(
        DETAILS_FILE,
        details
    )

    export_details_csv(
        details
    )

    print()
    print("=" * 70)
    print("PRICE UPDATE COMPLETE")
    print("=" * 70)

    print(
        f"Checked              : {checked}"
    )

    print(
        f"Price changes        : {changed}"
    )

    print(
        f"Other changes        : "
        f"{information_changed}"
    )

    print(
        f"Unchanged            : {unchanged}"
    )

    print(
        f"Errors               : {errors}"
    )


# ============================================================
# NEW PRODUCT DISCOVERY
# ============================================================

def generate_initial_prefixes():

    return [
        first + second
        for first in SEARCH_CHARS
        for second in SEARCH_CHARS
    ]


def discover_new_products():

    products, details = load_database()

    if not products:

        print(
            "No existing database found."
        )

        return

    print()
    print("=" * 70)
    print("NEW PRODUCT DISCOVERY")
    print("=" * 70)

    print(
        f"Existing products: "
        f"{len(products)}"
    )

    print()

    # --------------------------------------------------------
    # We use the same recursive search logic as the original
    # crawler, but do NOT erase the existing database.
    # --------------------------------------------------------

    pending = generate_initial_prefixes()

    completed = set()

    discovered_names = set(
        products.keys()
    )

    new_products = {}

    searches = 0

    while pending:

        prefix = pending.pop(0)

        if prefix in completed:

            continue

        print(
            f"SEARCH [{prefix}]"
        )

        try:

            found, html_size = (
                search_prefix(prefix)
            )

            searches += 1

            count = len(found)

            print(
                f"  Results: {count}"
            )

            # ------------------------------------------------
            # Empty
            # ------------------------------------------------

            if count == 0:

                completed.add(
                    prefix
                )

            # ------------------------------------------------
            # Less than limit
            # ------------------------------------------------

            elif count < MAX_RESULTS:

                completed.add(
                    prefix
                )

                for item in found:

                    name = item["name"]

                    if name not in discovered_names:

                        discovered_names.add(
                            name
                        )

                        new_products[name] = item

            # ------------------------------------------------
            # Limit
            # ------------------------------------------------

            else:

                if len(prefix) >= MAX_PREFIX_LENGTH:

                    completed.add(
                        prefix
                    )

                    for item in found:

                        name = item["name"]

                        if name not in discovered_names:

                            discovered_names.add(
                                name
                            )

                            new_products[name] = item

                else:

                    children = [
                        prefix + c
                        for c in SEARCH_CHARS
                    ]

                    pending = (
                        children +
                        pending
                    )

            if searches % 25 == 0:

                print(
                    f"  New products found: "
                    f"{len(new_products)}"
                )

            time.sleep(
                REQUEST_DELAY
            )

        except KeyboardInterrupt:

            print()
            print(
                "Discovery interrupted."
            )

            raise

        except Exception as e:

            print(
                f"  ERROR: {e}"
            )

            # Put failed prefix back.
            pending.insert(
                0,
                prefix
            )

            raise

    # --------------------------------------------------------
    # No new products
    # --------------------------------------------------------

    if not new_products:

        print()
        print(
            "No new products found."
        )

        return

    print()
    print(
        f"NEW PRODUCTS FOUND: "
        f"{len(new_products)}"
    )

    # --------------------------------------------------------
    # Add products
    # --------------------------------------------------------

    for name, item in new_products.items():

        products[name] = item

    # --------------------------------------------------------
    # Download their details
    # --------------------------------------------------------

    print()
    print(
        "Downloading details for "
        "new products..."
    )

    for index, name in enumerate(
        sorted(new_products),
        start=1
    ):

        print(
            f"[{index}/{len(new_products)}] "
            f"{name}"
        )

        try:

            data = get_drug_detail(
                name
            )

            details[name] = data

            append_csv_row(
                NEW_PRODUCTS_FILE,

                [
                    "date",
                    "timestamp",
                    "product",
                    "price",
                    "information",
                    "category"
                ],

                {
                    "date":
                        date_string(),

                    "timestamp":
                        now_string(),

                    "product":
                        name,

                    "price":
                        data["price"],

                    "information":
                        data["information"],

                    "category":
                        data["category"]
                }
            )

            time.sleep(
                DETAIL_DELAY
            )

        except Exception as e:

            print(
                f"  ERROR: {e}"
            )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    save_json(
        PRODUCTS_FILE,
        products
    )

    save_json(
        DETAILS_FILE,
        details
    )

    export_details_csv(
        details
    )

    print()
    print("=" * 70)
    print("NEW PRODUCT DISCOVERY COMPLETE")
    print("=" * 70)

    print(
        f"New products: "
        f"{len(new_products)}"
    )

    print(
        f"Total products now: "
        f"{len(products)}"
    )


# ============================================================
# NEW PRODUCTS + PRICE UPDATE
# ============================================================

def full_incremental_update():

    print()
    print("=" * 70)
    print("FULL INCREMENTAL UPDATE")
    print("=" * 70)

    print()
    print(
        "STEP 1/2: Checking existing prices..."
    )

    update_prices()

    print()
    print(
        "STEP 2/2: Searching for new products..."
    )

    discover_new_products()

    print()
    print("=" * 70)
    print("FULL INCREMENTAL UPDATE COMPLETE")
    print("=" * 70)


# ============================================================
# STATISTICS
# ============================================================

def show_statistics():

    products, details = load_database()

    print()
    print("=" * 70)
    print("DATABASE STATISTICS")
    print("=" * 70)

    print(
        f"Products database : "
        f"{len(products):,}"
    )

    print(
        f"Details database  : "
        f"{len(details):,}"
    )

    # --------------------------------------------------------
    # Count missing details
    # --------------------------------------------------------

    missing_details = [
        name
        for name in products
        if name not in details
    ]

    print(
        f"Missing details   : "
        f"{len(missing_details):,}"
    )

    # --------------------------------------------------------
    # Price history
    # --------------------------------------------------------

    if os.path.exists(
        PRICE_HISTORY_FILE
    ):

        try:

            with open(
                PRICE_HISTORY_FILE,
                "r",
                encoding="utf-8-sig"
            ) as f:

                count = sum(
                    1
                    for _ in f
                ) - 1

                print(
                    f"Price changes recorded: "
                    f"{max(count, 0):,}"
                )

        except Exception:
            pass

    # --------------------------------------------------------
    # New products
    # --------------------------------------------------------

    if os.path.exists(
        NEW_PRODUCTS_FILE
    ):

        try:

            with open(
                NEW_PRODUCTS_FILE,
                "r",
                encoding="utf-8-sig"
            ) as f:

                count = sum(
                    1
                    for _ in f
                ) - 1

                print(
                    f"New products recorded: "
                    f"{max(count, 0):,}"
                )

        except Exception:
            pass

    print(
        "=" * 70
    )


# ============================================================
# SHOW RECENT PRICE CHANGES
# ============================================================

def show_price_changes():

    if not os.path.exists(
        PRICE_HISTORY_FILE
    ):

        print(
            "No price history found."
        )

        return

    rows = []

    with open(
        PRICE_HISTORY_FILE,
        "r",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            rows.append(row)

    print()
    print("=" * 70)
    print("RECENT PRICE CHANGES")
    print("=" * 70)

    if not rows:

        print(
            "No price changes recorded."
        )

        return

    # Last 30.
    rows = rows[-30:]

    for row in rows:

        print(
            f"{row.get('date','')} | "
            f"{row.get('product','')} | "
            f"{row.get('old_price','')} "
            f"-> "
            f"{row.get('new_price','')}"
        )

    print(
        f"\nShowing last {len(rows)} changes."
    )


# ============================================================
# SHOW NEW PRODUCTS
# ============================================================

def show_new_products():

    if not os.path.exists(
        NEW_PRODUCTS_FILE
    ):

        print(
            "No new-product history found."
        )

        return

    rows = []

    with open(
        NEW_PRODUCTS_FILE,
        "r",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            rows.append(row)

    print()
    print("=" * 70)
    print("RECENTLY DISCOVERED PRODUCTS")
    print("=" * 70)

    if not rows:

        print(
            "No new products recorded."
        )

        return

    rows = rows[-30:]

    for row in rows:

        print(
            f"{row.get('date','')} | "
            f"{row.get('product','')} | "
            f"{row.get('price','')}"
        )

    print(
        f"\nShowing last {len(rows)} products."
    )


# ============================================================
# EXPORT CURRENT DATABASE
# ============================================================

def export_database():

    _, details = load_database()

    if not details:

        print(
            "No details database found."
        )

        return

    export_details_csv(
        details
    )


# ============================================================
# WINDOWS TASK SCHEDULER
# ============================================================

def create_windows_task():

    script_path = os.path.abspath(
        __file__
    )

    python_path = os.path.abspath(
        os.sys.executable
    )

    task_name = (
        "DrugEye Daily Incremental Update"
    )

    # --------------------------------------------------------
    # Ask user for time
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("CREATE AUTOMATIC UPDATE TASK")
    print("=" * 70)

    print()
    print(
        "The task will run the full incremental "
        "update automatically."
    )

    print()
    print(
        "Example time: 08:00"
    )

    run_time = input(
        "Enter daily time [08:00]: "
    ).strip()

    if not run_time:

        run_time = "08:00"

    if not re.fullmatch(
        r"\d{2}:\d{2}",
        run_time
    ):

        print(
            "Invalid time."
        )

        return

    # --------------------------------------------------------
    # Create command
    # --------------------------------------------------------

    command = (
        f'schtasks /Create '
        f'/TN "{task_name}" '
        f'/TR "\\"{python_path}\\" '
        f'\\"{script_path}\\" --auto" '
        f'/SC DAILY '
        f'/ST {run_time} '
        f'/F'
    )

    print()
    print(
        "Creating Windows Task Scheduler task..."
    )

    try:

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True
        )

        if result.returncode == 0:

            print()
            print(
                "SUCCESS."
            )

            print(
                f"Task: {task_name}"
            )

            print(
                f"Daily time: {run_time}"
            )

        else:

            print()
            print(
                "Could not create task."
            )

            print(
                result.stdout
            )

            print(
                result.stderr
            )

    except Exception as e:

        print(
            f"ERROR: {e}"
        )


# ============================================================
# AUTOMATIC MODE
# ============================================================

def automatic_mode():

    print()
    print("=" * 70)
    print("DRUGEYE AUTOMATIC UPDATE")
    print("=" * 70)

    print()

    full_incremental_update()


# ============================================================
# MENU
# ============================================================

def show_menu():

    print()

    print(
        "=" * 70
    )

    print(
        "DRUGEYE DATABASE MANAGER"
    )

    print(
        "=" * 70
    )

    products, details = load_database()

    print()

    print(
        f"Current products: "
        f"{len(products):,}"
    )

    print(
        f"Current details : "
        f"{len(details):,}"
    )

    print()

    print(
        "1. Full incremental update"
    )

    print(
        "   → Update prices/details"
    )

    print(
        "   → Search for new products"
    )

    print()

    print(
        "2. Update prices/details only"
    )

    print(
        "   → Check existing products"
    )

    print(
        "   → Record price changes"
    )

    print()

    print(
        "3. Find new products only"
    )

    print(
        "   → Search DrugEye"
    )

    print(
        "   → Add newly discovered products"
    )

    print()

    print(
        "4. Update prices + find new products"
    )

    print(
        "   → Same as option 1"
    )

    print()

    print(
        "5. Show database statistics"
    )

    print()

    print(
        "6. Export current database to CSV"
    )

    print()

    print(
        "7. Show recent price changes"
    )

    print()

    print(
        "8. Show recently discovered products"
    )

    print()

    print(
        "9. Create automatic daily update"
    )

    print()

    print(
        "0. Exit"
    )

    print(
        "=" * 70
    )


# ============================================================
# INTERACTIVE MENU
# ============================================================

def interactive_menu():

    while True:

        show_menu()

        choice = input(
            "\nChoose an option: "
        ).strip()

        if choice == "1":

            full_incremental_update()

        elif choice == "2":

            update_prices()

        elif choice == "3":

            discover_new_products()

        elif choice == "4":

            full_incremental_update()

        elif choice == "5":

            show_statistics()

        elif choice == "6":

            export_database()

        elif choice == "7":

            show_price_changes()

        elif choice == "8":

            show_new_products()

        elif choice == "9":

            create_windows_task()

        elif choice == "0":

            print()
            print(
                "Goodbye."
            )

            break

        else:

            print()
            print(
                "Invalid choice."
            )

        input(
            "\nPress ENTER to return to menu..."
        )


# ============================================================
# MAIN
# ============================================================

def main():

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Automatic Task Scheduler mode.
    # --------------------------------------------------------

    if (
        len(os.sys.argv) > 1
        and os.sys.argv[1] == "--auto"
    ):

        automatic_mode()

        return

    # --------------------------------------------------------
    # Interactive mode.
    # --------------------------------------------------------

    interactive_menu()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print()
        print()
        print(
            "Stopped by user."
        )

    except Exception as e:

        print()
        print(
            "=" * 70
        )

        print(
            "ERROR"
        )

        print(
            "=" * 70
        )

        print(
            e
        )

        print()
        print(
            "Your existing database files "
            "were not intentionally deleted."
        )

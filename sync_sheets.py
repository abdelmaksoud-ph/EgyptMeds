"""Push drug_eye_output data into a Google Sheet. Run after drugeye.py --auto."""
import csv
import json
import os
from datetime import datetime, timezone

import gspread
from google.oauth2.service_account import Credentials

OUT = "eg_drugs_data"
HEADER = ["search_name", "name", "price", "information", "category"]


def push(sh, title, rows):
    if not rows:
        return
    cols = max(len(rows[0]), 5)
    try:
        ws = sh.worksheet(title)
        ws.clear()
        ws.resize(rows=len(rows) + 100, cols=cols)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title, rows=len(rows) + 100, cols=cols)
    for i in range(0, len(rows), 5000):
        ws.update(values=rows[i:i + 5000], range_name=f"A{i + 1}")
    print(f"{title}: {len(rows) - 1} rows")


def main():
    info = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    sh = gspread.authorize(creds).open_by_key(os.environ["SHEET_ID"])

    with open(f"{OUT}/drug_details.json", encoding="utf-8") as f:
        details = json.load(f)
    rows = [HEADER] + [
        [details[k].get(h, "") for h in HEADER] for k in sorted(details)
    ]
    push(sh, "products", rows)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    push(sh, "meta", [["key", "value"], ["last_update", now]])

    for tab in ("price_history", "new_products", "changed_products"):
        path = f"{OUT}/{tab}.csv"
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig", newline="") as f:
                push(sh, tab, list(csv.reader(f)))


if __name__ == "__main__":
    main()

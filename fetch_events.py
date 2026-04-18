"""
fetch_events.py
================
Fetches Events.csv directly from the main Google Sheet (Sheet1).
Extracts: AI Title, Blog Draft, Event Date, URL — no Code.gs changes needed.

Run: python fetch_events.py
"""

import os
import csv
import pickle
import base64
from datetime import datetime

# Load .env
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "")
CSV_FILE       = os.getenv("CSV_FILE", "Events.csv")

if not SPREADSHEET_ID:
    print("❌ SPREADSHEET_ID not set in .env")
    exit(1)

# Load credentials
try:
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_b64 = os.getenv("TOKEN_PICKLE_B64", "")
    creds = None

    if token_b64:
        creds = pickle.loads(base64.b64decode(token_b64))
    elif os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as f:
            creds = pickle.load(f)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    svc = build("sheets", "v4", credentials=creds, cache_discovery=False)

except Exception as e:
    print(f"❌ Auth error: {e}")
    exit(1)

# Fetch the main sheet (Sheet1) — all columns
try:
    result = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range="Sheet1!A:M"
    ).execute()
    rows = result.get("values", [])
except Exception as e:
    print(f"❌ Failed to fetch Sheet1: {e}")
    exit(1)

if len(rows) < 2:
    print("❌ Sheet1 is empty!")
    exit(1)

# Map headers
headers = [h.strip().lower() for h in rows[0]]
print(f"Sheet headers: {headers}")

def col(name):
    try:
        return headers.index(name)
    except ValueError:
        return -1

col_url       = col("url")
col_status    = col("status")
col_ai_title  = col("ai title")
col_blog      = col("generated blog draft")
col_date      = col("event date")
col_flag      = col("upcoming flag")
col_qa        = col("qa notes")

print(f"URL col: {col_url}, Status col: {col_status}, AI Title col: {col_ai_title}, Blog col: {col_blog}")

# Filter rows
exported = []
skipped_past = 0
skipped_dead = 0

for i, row in enumerate(rows[1:], 1):
    def get(c):
        return row[c].strip() if c >= 0 and c < len(row) else ""

    if get(col_status) != "Processed":
        continue

    flag = get(col_flag).lower()
    if "past event" in flag:
        skipped_past += 1
        continue

    qa = get(col_qa)
    if qa == "❌ Dead link":
        skipped_dead += 1
        continue

    title      = get(col_ai_title)
    blog       = get(col_blog)
    source_url = get(col_url)
    raw_date   = get(col_date)

    if not title or not blog:
        continue

    # Parse date
    date_str = ""
    if raw_date:
        for fmt in ("%B %d, %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                d = datetime.strptime(raw_date.strip(), fmt)
                date_str = d.strftime("%Y-%m-%d %H:%M:%S")
                break
            except ValueError:
                pass

    exported.append({
        "name":              title,
        "content":           blog,
        "website_published": "False",
        "post_date":         date_str,
        "source_url":        source_url,
    })

# Write CSV
with open(CSV_FILE, "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["name","content","website_published","post_date","source_url"],
                            quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(exported)

print(f"\n✅ Events.csv written with {len(exported)} posts")
print(f"   Skipped: {skipped_past} past events, {skipped_dead} dead links")
print(f"   Columns: name, content, website_published, post_date, source_url")

# Quick verify
if exported:
    first = exported[0]
    print(f"\nFirst post:")
    print(f"  Title      : {first['name'][:60]}")
    print(f"  source_url : {first['source_url'][:80] or '(empty)'}")

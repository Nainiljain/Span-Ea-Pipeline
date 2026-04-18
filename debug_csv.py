import csv, os

if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

CSV_FILE = os.getenv("CSV_FILE", "Events.csv")

with open(CSV_FILE, "r", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

print(f"Columns: {list(rows[0].keys())}")
print()
row = rows[0]
print(f"name       : {row.get('name','')[:60]}")
print(f"content    : {row.get('content','')[:200]}")
print(f"source_url : {row.get('source_url','')[:80]}")

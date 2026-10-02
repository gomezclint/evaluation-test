import csv, os
from datetime import date
from pathlib import Path
import requests

DATASET = "RicardoRei/wmt-mqm-human-evaluation"
BATCH = 100  # the API's max rows per request
offset = (date.today().toordinal() * BATCH) % 140_000  # new batch each day

resp = requests.get(
    "https://datasets-server.huggingface.co/rows",
    params={"dataset": DATASET, "config": "default", "split": "train",
            "offset": offset, "length": BATCH},
    headers={"Authorization": f"Bearer {os.environ['HF_TOKEN']}"},
    timeout=30,
)
resp.raise_for_status()
rows = [r["row"] for r in resp.json()["rows"]]

out = Path("exports") / f"{date.today()}_mqm_batch.csv"
out.parent.mkdir(exist_ok=True)
with out.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(f"Saved {len(rows)} rows to {out}")

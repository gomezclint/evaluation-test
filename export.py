import csv, json, os
from datetime import date
from pathlib import Path
import requests

URL = "https://huggingface.co/datasets/RicardoRei/wmt-mqm-error-spans/resolve/main/train.jsonl"
LANG_PAIR = "en-de"   # English source, German translation
BATCH = 50           # translations per day
start = (date.today().toordinal() * BATCH) % 10_000  # different batch each day

rows, seen = [], 0
headers = {"Authorization": f"Bearer {os.environ['HF_TOKEN']}"}
with requests.get(URL, headers=headers, stream=True, timeout=120) as resp:
    resp.raise_for_status()
    for line in resp.iter_lines():
        if not line:
            continue
        item = json.loads(line)
        if item["lp"] != LANG_PAIR:
            continue
        seen += 1
        if seen <= start:
            continue
        errors = item["annotations"] or [{"text": "", "severity": "no error"}]
        for err in errors:
            rows.append({
                "lang_pair": item["lp"],
                "source_en": item["src"],
                "translation_de": item["mt"],
                "error_text": err.get("text", ""),
                "severity": err.get("severity", ""),
            })
        if seen >= start + BATCH:
            break

out = Path("exports") / f"{date.today()}_mqm_error_spans.csv"
out.parent.mkdir(exist_ok=True)
with out.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(f"Saved {len(rows)} rows from {BATCH} translations to {out}")

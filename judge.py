"""Step 2: LLM judge. Reads today's export and labels each translation with Gemini.
The judge never sees the human annotations. Output: exports/<date>_judge_labels.csv"""
import csv, json, os, sys, time
from datetime import date
from pathlib import Path
import requests

MODEL = "gemini-flash-latest"  # if this errors, copy a current Flash model name from AI Studio
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
GROUP_SIZE = 10  # translations sent to the judge in one request
LABELS = ["no error", "minor", "major"]
RANK = {label: i for i, label in enumerate(LABELS)}
today = date.today()

PROMPT = """You are an expert English-to-German translation reviewer using the MQM framework.
For each numbered item below, identify errors in the German translation
(accuracy, fluency, terminology, style, locale conventions).
Judge each item independently.
Severity: "major" = changes the meaning or would confuse or mislead a reader;
"minor" = noticeable but does not affect understanding.
Return only JSON with one entry per item, using the item's id:
{{"results": [{{"id": 1, "errors": [{{"text": "<exact erroneous text from the translation>", "severity": "minor" or "major"}}]}}]}}
Use "errors": [] for a translation with no errors.

{items}"""


def worst(severities):
    """Overall label for a translation = its most severe error."""
    w = "no error"
    for s in severities:
        s = "major" if s == "critical" else s
        if RANK.get(s, 0) > RANK[w]:
            w = s
    return w


RETRY_WAIT = 30  # seconds to wait once after a rate-limit error before giving up


class RateLimitError(Exception):
    pass


def judge(group):
    """Send a group of (src, mt) pairs in one request; return {id: errors}."""
    items = "\n\n".join(
        f"Item {i}\nSource (English): {src}\nTranslation (German): {mt}"
        for i, (src, mt) in enumerate(group, start=1)
    )
    body = {"contents": [{"parts": [{"text": PROMPT.format(items=items)}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    for attempt in range(2):
        r = requests.post(API_URL, json=body, timeout=180,
                          headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
        if r.status_code == 429:
            if "PerDay" in r.text:  # daily limit used up: retrying won't help
                raise RateLimitError("DAILY limit reached (resets at midnight Pacific time).\n" + r.text[:800])
            if attempt == 0:
                print(f"Rate limited. Waiting {RETRY_WAIT}s and trying once more...")
                time.sleep(RETRY_WAIT)
                continue
            raise RateLimitError(f"still rate limited after waiting {RETRY_WAIT}s.\n" + r.text[:800])
        if r.status_code != 200:
            raise RuntimeError(f"Gemini returned {r.status_code}: {r.text[:500]}")
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return {int(x["id"]): x.get("errors", []) for x in json.loads(text).get("results", [])}


# 1. Read the unique translations from today's export (the human labels are ignored)
translations = []
with (Path("exports") / f"{today}_mqm_error_spans.csv").open(encoding="utf-8") as f:
    for row in csv.DictReader(f):
        pair = (row["source_en"], row["translation_de"])
        if pair not in translations:
            translations.append(pair)

# 2. Ask the judge, several translations per request
labels = []
for start in range(0, len(translations), GROUP_SIZE):
    group = translations[start:start + GROUP_SIZE]
    try:
        answers = judge(group)
    except RateLimitError as err:
        sys.exit(f"Stopped: Gemini rate limit. {err}")
    except Exception as err:
        print(f"Skipped {len(group)} translations: {err}")
        continue
    for i, (src, mt) in enumerate(group, start=1):
        if i not in answers:
            print("Skipped one translation: the judge returned no answer for it")
            continue
        errors = answers[i]
        labels.append({
            "source_en": src, "translation_de": mt,
            "llm_severity": worst(str(e.get("severity", "")).lower() for e in errors),
            "llm_errors": "; ".join(f'{e.get("text", "")} ({e.get("severity", "")})' for e in errors),
        })
    time.sleep(7)  # stay under the free-tier rate limit

if not labels:
    sys.exit("The judge labeled no translations. Check the errors above.")

# 3. Save the judge's labels
out = Path("exports") / f"{today}_judge_labels.csv"
with out.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=labels[0].keys())
    writer.writeheader()
    writer.writerows(labels)
print(f"Judge labeled {len(labels)} of {len(translations)} translations -> {out}")

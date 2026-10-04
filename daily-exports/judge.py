"""Step 2: LLM judge. Reads today's export and labels each translation with an LLM judge (via Groq).
The judge never sees the human annotations. Output: judge_labels/<date>_judge_labels.csv"""
import csv, json, os, sys, time
from datetime import date
from pathlib import Path
import requests

MODEL = "openai/gpt-oss-120b"  # any current Groq model ID (see console.groq.com/docs/models)
API_URL = "https://api.groq.com/openai/v1/chat/completions"
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


RETRY_WAIT = 30  # seconds to wait once after a rate-limit or overload error before giving up


class LLMUnavailable(Exception):
    pass


def call_llm(prompt_text):
    """Send one prompt to Groq and return the parsed JSON reply."""
    body = {"model": MODEL,
            "messages": [{"role": "user", "content": prompt_text}],
            "temperature": 0,
            "response_format": {"type": "json_object"}}
    for attempt in range(2):
        r = requests.post(API_URL, json=body, timeout=180,
                          headers={"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"})
        if r.status_code == 429 and "per day" in r.text.lower():  # daily limit used up: retrying won't help
            raise LLMUnavailable("DAILY limit reached for this model.\n" + r.text[:800])
        if r.status_code in (429, 500, 502, 503, 504):  # rate limited, or Groq overloaded / temporarily down
            problem = "rate limited" if r.status_code == 429 else f"overloaded or unavailable (HTTP {r.status_code})"
            if attempt == 0:
                print(f"Groq is {problem}. Waiting {RETRY_WAIT}s and trying once more...")
                time.sleep(RETRY_WAIT)
                continue
            raise LLMUnavailable(f"Groq is still {problem} after waiting {RETRY_WAIT}s. "
                                 f"Try again later.\n" + r.text[:800])
        if r.status_code != 200:
            raise RuntimeError(f"Groq returned {r.status_code}: {r.text[:500]}")
        return json.loads(r.json()["choices"][0]["message"]["content"])


def judge(group):
    """Send a group of (src, mt) pairs in one request; return {id: errors}."""
    items = "\n\n".join(
        f"Item {i}\nSource (English): {src}\nTranslation (German): {mt}"
        for i, (src, mt) in enumerate(group, start=1)
    )
    reply = call_llm(PROMPT.format(items=items))
    return {int(x["id"]): x.get("errors", []) for x in reply.get("results", [])}


# 1. Read the unique translations from today's export (the human labels are ignored)
translations = []
with (Path("human-labeled") / f"{today}_mqm_error_spans.csv").open(encoding="utf-8") as f:
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
    except LLMUnavailable as err:
        sys.exit(f"Stopped: {err}")
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
out = Path("judge_labels") / f"{today}_judge_labels.csv"
out.parent.mkdir(exist_ok=True)
with out.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=labels[0].keys())
    writer.writeheader()
    writer.writerows(labels)
print(f"Judge labeled {len(labels)} of {len(translations)} translations -> {out}")

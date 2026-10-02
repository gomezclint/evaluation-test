import csv, json, os, sys, time
from datetime import date
from pathlib import Path
import requests

MODEL = "gemini-flash-latest"  # if this errors, copy a current Flash model name from AI Studio
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
LABELS = ["no error", "minor", "major"]
RANK = {label: i for i, label in enumerate(LABELS)}
today = date.today()

PROMPT = """You are an expert English-to-German translation reviewer using the MQM framework.
Identify errors in the German translation (accuracy, fluency, terminology, style, locale conventions).
Severity: "major" = changes the meaning or would confuse or mislead a reader;
"minor" = noticeable but does not affect understanding.
Return only JSON: {{"errors": [{{"text": "<exact erroneous text from the translation>", "severity": "minor" or "major"}}]}}
Return {{"errors": []}} if the translation has no errors.

Source (English): {src}
Translation (German): {mt}"""


def worst(severities):
    """Overall label for a translation = its most severe error."""
    w = "no error"
    for s in severities:
        s = "major" if s == "critical" else s
        if RANK.get(s, 0) > RANK[w]:
            w = s
    return w


def judge(src, mt):
    body = {"contents": [{"parts": [{"text": PROMPT.format(src=src, mt=mt)}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    for _ in range(3):
        r = requests.post(API_URL, json=body, timeout=60,
                          headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
        if r.status_code == 429:  # rate limited: wait and retry
            time.sleep(30)
            continue
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text).get("errors", [])
    raise RuntimeError("still rate limited after retries")


def safe_div(a, b):
    return a / b if b else 0.0


# 1. Group the human annotations by translation
segments = {}
with (Path("exports") / f"{today}_mqm_error_spans.csv").open(encoding="utf-8") as f:
    for row in csv.DictReader(f):
        seg = segments.setdefault((row["source_en"], row["translation_de"]), [])
        if row["severity"] != "no error":
            seg.append((row["error_text"], row["severity"].lower()))

# 2. Ask the LLM judge about each translation
results = []
for (src, mt), human_errors in segments.items():
    try:
        llm_errors = judge(src, mt)
    except Exception as err:
        print(f"Skipped one translation: {err}")
        continue
    human_sev = worst(s for _, s in human_errors)
    llm_sev = worst(str(e.get("severity", "")).lower() for e in llm_errors)
    results.append({
        "source_en": src, "translation_de": mt,
        "human_severity": human_sev, "llm_severity": llm_sev,
        "agree": human_sev == llm_sev,
        "human_errors": "; ".join(f"{t} ({s})" for t, s in human_errors),
        "llm_errors": "; ".join(f'{e.get("text", "")} ({e.get("severity", "")})' for e in llm_errors),
    })
    time.sleep(7)  # stay under the free-tier rate limit

n = len(results)
if n == 0:
    sys.exit("No translations were judged, so there is nothing to compare. Check the errors above.")

# 3. Metrics, treating the human labels as ground truth
accuracy = sum(r["agree"] for r in results) / n

per_label = {}
for label in LABELS:
    tp = sum(r["human_severity"] == label and r["llm_severity"] == label for r in results)
    fp = sum(r["human_severity"] != label and r["llm_severity"] == label for r in results)
    fn = sum(r["human_severity"] == label and r["llm_severity"] != label for r in results)
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = safe_div(2 * precision * recall, precision + recall)
    support = sum(r["human_severity"] == label for r in results)
    per_label[label] = {"precision": precision, "recall": recall, "f1": f1, "support": support}

macro_f1 = sum(m["f1"] for m in per_label.values()) / len(LABELS)

# 4. Save the side-by-side comparison
out = Path("exports") / f"{today}_judge_comparison.csv"
with out.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

# 5. Append today's metrics to a running history
history = Path("metrics_history.csv")
new_file = not history.exists()
with history.open("a", newline="") as f:
    writer = csv.writer(f)
    if new_file:
        header = ["date", "segments", "accuracy", "macro_f1"]
        for label in LABELS:
            key = label.replace(" ", "_")
            header += [f"{key}_precision", f"{key}_recall", f"{key}_f1"]
        writer.writerow(header)
    row = [today, n, f"{accuracy:.2f}", f"{macro_f1:.2f}"]
    for label in LABELS:
        m = per_label[label]
        row += [f"{m['precision']:.2f}", f"{m['recall']:.2f}", f"{m['f1']:.2f}"]
    writer.writerow(row)

# 6. Summary page: overall metrics, per-label metrics, confusion matrix
lines = [f"## LLM judge vs. human MQM annotations ({today})", "",
         f"Translations compared: **{n}**", "",
         "| Overall | Value |", "|---|---|",
         f"| Accuracy | {accuracy:.0%} |",
         f"| Macro-F1 | {macro_f1:.2f} |", "",
         "**Per-label metrics** (human labels = ground truth)", "",
         "| Label | Precision | Recall | F1 | Human count |", "|---|---|---|---|---|"]
for label in LABELS:
    m = per_label[label]
    lines.append(f"| {label} | {m['precision']:.0%} | {m['recall']:.0%} | {m['f1']:.2f} | {m['support']} |")
lines += ["", "**Confusion matrix** (rows = human, columns = LLM)", "",
          "| | " + " | ".join(LABELS) + " |", "|---" * 4 + "|"]
for h in LABELS:
    counts = [sum(r["human_severity"] == h and r["llm_severity"] == l for r in results) for l in LABELS]
    lines.append(f"| **{h}** | " + " | ".join(map(str, counts)) + " |")

summary = "\n".join(lines)
print(summary)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
        f.write(summary)

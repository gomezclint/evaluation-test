"""Step 3: Compare the LLM judge's labels with the human annotations and calculate metrics.
Outputs: comparisons/<date>_judge_comparison.csv, comparisons/metrics_history.csv, and the run's summary page."""
import csv, os, sys
from datetime import date
from pathlib import Path

LABELS = ["no error", "minor", "major"]
RANK = {label: i for i, label in enumerate(LABELS)}
# Date to compare: RUN_DATE (YYYY-MM-DD) if set, otherwise today
today = os.environ.get("RUN_DATE") or str(date.today())


def worst(severities):
    """Overall label for a translation = its most severe error."""
    w = "no error"
    for s in severities:
        s = "major" if s == "critical" else s
        if RANK.get(s, 0) > RANK[w]:
            w = s
    return w


def safe_div(a, b):
    return a / b if b else 0.0


HUMAN_FILE = Path("human-labeled") / f"{today}_mqm_error_spans.csv"
JUDGE_FILE = Path("judge_labels") / f"{today}_judge_labels.csv"
OUT_DIR = Path("comparisons")
for path in (HUMAN_FILE, JUDGE_FILE):
    if not path.exists():
        sys.exit(f"Missing {path}. Run the daily export first, or pick a date that has both files.")

# 1. Load the human annotations, grouped by translation
human = {}
with HUMAN_FILE.open(encoding="utf-8") as f:
    for row in csv.DictReader(f):
        errs = human.setdefault((row["source_en"], row["translation_de"]), [])
        if row["severity"] != "no error":
            errs.append((row["error_text"], row["severity"].lower()))

# 2. Load the judge's labels
with JUDGE_FILE.open(encoding="utf-8") as f:
    judge = {(r["source_en"], r["translation_de"]): r for r in csv.DictReader(f)}

# 3. Match them up (only translations both sides labeled)
results = []
for key, j in judge.items():
    if key not in human:
        continue
    human_sev = worst(s for _, s in human[key])
    results.append({
        "source_en": key[0], "translation_de": key[1],
        "human_severity": human_sev, "llm_severity": j["llm_severity"],
        "agree": human_sev == j["llm_severity"],
        "human_errors": "; ".join(f"{t} ({s})" for t, s in human[key]),
        "llm_errors": j["llm_errors"],
    })

n = len(results)
if n == 0:
    sys.exit(f"No translations to compare. Check that both files exist for {today}.")

# 4. Metrics, treating the human labels as ground truth
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
    llm_count = sum(r["llm_severity"] == label for r in results)
    per_label[label] = {"precision": precision, "recall": recall, "f1": f1,
                        "support": support, "llm_count": llm_count}
macro_f1 = sum(m["f1"] for m in per_label.values()) / len(LABELS)

# 5. Save the side-by-side comparison
OUT_DIR.mkdir(exist_ok=True)
out = OUT_DIR / f"{today}_judge_comparison.csv"
with out.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

# 6. Save this date's metrics to the running history (replacing any earlier row for the same date)
header = ["date", "segments", "accuracy", "macro_f1"]
for label in LABELS:
    key = label.replace(" ", "_")
    header += [f"{key}_precision", f"{key}_recall", f"{key}_f1"]
row = [today, n, f"{accuracy:.2f}", f"{macro_f1:.2f}"]
for label in LABELS:
    m = per_label[label]
    row += [f"{m['precision']:.2f}", f"{m['recall']:.2f}", f"{m['f1']:.2f}"]

history = OUT_DIR / "metrics_history.csv"
old_rows = []
if history.exists():
    with history.open(newline="") as f:
        old_rows = [r for r in list(csv.reader(f))[1:] if r and r[0] != today]
all_rows = sorted(old_rows + [[str(x) for x in row]], key=lambda r: r[0])
with history.open("w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(header)
    writer.writerows(all_rows)

# 7. Summary page: overall metrics, per-label metrics, confusion matrix
lines = [f"## LLM judge vs. human MQM annotations ({today})", "",
         f"Translations compared: **{n}**", "",
         "| Overall | Value |", "|---|---|",
         f"| Accuracy | {accuracy:.0%} |",
         f"| Macro-F1 | {macro_f1:.2f} |", "",
         "**Per-label metrics** (human labels = ground truth)", "",
         "| Label | Precision | Recall | F1 | Human count | LLM count |", "|---|---|---|---|---|---|"]
for label in LABELS:
    m = per_label[label]
    lines.append(f"| {label} | {m['precision']:.0%} | {m['recall']:.0%} | {m['f1']:.2f} | {m['support']} | {m['llm_count']} |")
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

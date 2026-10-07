"""Step 3: Compare the LLM judge's labels with the human annotations and calculate metrics.
Outputs: comparisons/results/<date>_judge_comparison.csv, comparisons/metrics_history.csv, and the run's summary page."""
import csv, math, os, random, sys
from datetime import date, datetime, timezone
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


def wilson(k, n, z=1.96):
    """95% Wilson confidence interval for a proportion k/n."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def kappa(pairs, weighted=False):
    """Cohen's kappa for (human, llm) label pairs. weighted=True uses quadratic
    weights, so confusing labels further apart on the scale counts more."""
    k, n = len(LABELS), len(pairs)
    observed = [[0] * k for _ in range(k)]
    for h, l in pairs:
        observed[RANK[h]][RANK[l]] += 1
    rows = [sum(observed[i]) for i in range(k)]
    cols = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    disagree_obs = disagree_exp = 0.0
    for i in range(k):
        for j in range(k):
            w = ((i - j) / (k - 1)) ** 2 if weighted else float(i != j)
            disagree_obs += w * observed[i][j]
            disagree_exp += w * rows[i] * cols[j] / n
    if disagree_exp == 0:
        return None  # undefined when both sides use a single label
    return 1 - disagree_obs / disagree_exp


def macro_f1_of(rows):
    """Average F1 over the labels that appear in the data, from either the linguists or the judge.
    A label nobody used that day is left out, instead of counting as an F1 of 0."""
    present = [label for label in LABELS
               if any(r["human_severity"] == label or r["llm_severity"] == label for r in rows)]
    if not present:
        return None
    total = 0.0
    for label in present:
        tp = sum(r["human_severity"] == label and r["llm_severity"] == label for r in rows)
        fp = sum(r["human_severity"] != label and r["llm_severity"] == label for r in rows)
        fn = sum(r["human_severity"] == label and r["llm_severity"] != label for r in rows)
        p, rc = safe_div(tp, tp + fp), safe_div(tp, tp + fn)
        total += safe_div(2 * p * rc, p + rc)
    return total / len(present)


def bootstrap_ci(rows, stat, resamples=2000, seed=42):
    """95% bootstrap confidence interval: re-score random resamples of the translations."""
    rng = random.Random(seed)  # fixed seed so the same data always gives the same interval
    values = []
    for _ in range(resamples):
        sample = [rows[rng.randrange(len(rows))] for _ in rows]
        v = stat(sample)
        if v is not None:
            values.append(v)
    if not values:
        return None
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


def fmt(value, ci=None, pct=False):
    """Format a metric with its confidence interval, e.g. '72% (58–83%)'."""
    if value is None:
        return "n/a"
    f = (lambda x: f"{x:.0%}") if pct else (lambda x: f"{x:.2f}")
    return f"{f(value)} ({f(ci[0])}–{f(ci[1])})" if ci else f(value)


HUMAN_FILE = Path("human-labeled") / f"{today}_mqm_error_spans.csv"
JUDGE_FILE = Path("judge_labels") / f"{today}_judge_labels.csv"
OUT_DIR = Path("comparisons")
# Manual runs are kept separately and never replace the daily results or the history
MANUAL = os.environ.get("RUN_MODE") == "manual"
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
correct = sum(r["agree"] for r in results)
accuracy = correct / n
accuracy_ci = wilson(correct, n)
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
                        "precision_ci": wilson(tp, tp + fp), "recall_ci": wilson(tp, tp + fn),
                        "support": support, "llm_count": llm_count}
macro_f1 = macro_f1_of(results)
macro_f1_ci = bootstrap_ci(results, macro_f1_of)

# Agreement corrected for chance (human vs. LLM)
to_pairs = lambda rows: [(r["human_severity"], r["llm_severity"]) for r in rows]
cohen = kappa(to_pairs(results))
cohen_ci = bootstrap_ci(results, lambda rows: kappa(to_pairs(rows)))
weighted = kappa(to_pairs(results), weighted=True)
weighted_ci = bootstrap_ci(results, lambda rows: kappa(to_pairs(rows), weighted=True))

# 5. Save the side-by-side comparison
if MANUAL:
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    RESULTS_DIR = OUT_DIR / "manual-runs"
    out = RESULTS_DIR / f"{today}_run-{run_stamp}_judge_comparison.csv"
else:
    RESULTS_DIR = OUT_DIR / "results"
    out = RESULTS_DIR / f"{today}_judge_comparison.csv"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
with out.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

# 6. Save this date's metrics to the running history (replacing any earlier row for the same date)
header = ["date", "segments", "accuracy", "macro_f1"]
for label in LABELS:
    key = label.replace(" ", "_")
    header += [f"{key}_precision", f"{key}_recall", f"{key}_f1"]
header += ["cohen_kappa", "weighted_kappa"]  # added later, so they go at the end
row = [today, n, f"{accuracy:.2f}", f"{macro_f1:.2f}"]
for label in LABELS:
    m = per_label[label]
    row += [f"{m['precision']:.2f}", f"{m['recall']:.2f}", f"{m['f1']:.2f}"]
row += ["" if cohen is None else f"{cohen:.2f}", "" if weighted is None else f"{weighted:.2f}"]

if not MANUAL:
    history = OUT_DIR / "metrics_history.csv"
    old_rows = []
    if history.exists():
        with history.open(newline="") as f:
            old_rows = [r for r in list(csv.reader(f))[1:] if r and r[0] != today]
    # rows saved before a column existed get blank values for it
    old_rows = [r + [""] * (len(header) - len(r)) for r in old_rows]
    all_rows = sorted(old_rows + [[str(x) for x in row]], key=lambda r: r[0])
    with history.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(all_rows)

# 7. Summary page: overall metrics, per-label metrics, confusion matrix
lines = [f"## LLM judge vs. human MQM annotations ({today})", "",
         f"Translations compared: **{n}**", "",
         *([f"_Manual run: saved to {out}. The daily results and metrics history were not changed._", ""] if MANUAL else []),
         "Values in brackets are 95% confidence intervals.", "",
         "| Overall | Value |", "|---|---|",
         f"| Accuracy | {fmt(accuracy, accuracy_ci, pct=True)} |",
         f"| Macro-F1 | {fmt(macro_f1, macro_f1_ci)} |",
         f"| Cohen's kappa | {fmt(cohen, cohen_ci)} |",
         f"| Weighted kappa (quadratic) | {fmt(weighted, weighted_ci)} |", "",
         "**Per-label metrics** (human labels = ground truth)", "",
         "| Label | Precision | Recall | F1 | Human count | LLM count |", "|---|---|---|---|---|---|"]
for label in LABELS:
    m = per_label[label]
    if m["support"] == 0 and m["llm_count"] == 0:  # nobody used this label: nothing to score
        lines.append(f"| {label} | n/a | n/a | n/a | 0 | 0 |")
        continue
    lines.append(f"| {label} | {fmt(m['precision'], m['precision_ci'], pct=True)} "
                 f"| {fmt(m['recall'], m['recall_ci'], pct=True)} | {m['f1']:.2f} "
                 f"| {m['support']} | {m['llm_count']} |")
lines += ["", "_Macro-F1 averages only the labels that appear in the data that day._"]
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

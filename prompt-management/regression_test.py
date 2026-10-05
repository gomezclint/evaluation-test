"""Regression test for the business-risk judge prompt.

Modes:
  python regression_test.py              test the candidate prompt only (never promotes)
  python regression_test.py --promote    test the candidate and promote it if every check passes
  python regression_test.py --rebaseline re-score the current PRODUCTION prompt and save it as the
                                         new baseline (use after changing the model or golden set)

A candidate is promoted only if it:
  1. answers every golden item,
  2. meets the thresholds in eval_config.json,
  3. scores no more than max_drop_vs_production below the production baseline, and
  4. (if block_new_misses is on) catches every critical item the production prompt caught.
"""
import csv, hashlib, json, math, os, random, shutil, sys, time
from datetime import datetime, timezone
from pathlib import Path
import requests

CONFIG = json.loads(Path("eval_config.json").read_text(encoding="utf-8"))
MODEL = CONFIG["model"]
API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROUP_SIZE = 10   # golden items sent to the judge per request
RETRY_WAIT = 30   # seconds to wait once after a rate-limit or overload error before giving up
RESULTS_DIR = Path("regression_results")
BASELINE_METRICS = Path(CONFIG["production_metrics"])
BASELINE_ITEMS = BASELINE_METRICS.with_name("production_items.json")
BLOCK_NEW_MISSES = CONFIG.get("block_new_misses", True)

promote = "--promote" in sys.argv
rebaseline = "--rebaseline" in sys.argv
now = datetime.now(timezone.utc)
stamp = now.strftime("%Y-%m-%d_%H%M%S")


# ---------------------------------------------------------------- calling the judge
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


def build_prompt(template, style_guide, group):
    items = "\n\n".join(
        f"Item {i}\nSource (English): {row['source_en']}\nTranslation (German): {row['translation_de']}"
        for i, row in enumerate(group, start=1)
    )
    return template.replace("{{STYLE_GUIDE}}", style_guide).replace("{{ITEMS}}", items)


def run_judge(template, style_guide, golden):
    """Return {golden id: judge answer} for every item the judge answered."""
    predictions = {}
    for start in range(0, len(golden), GROUP_SIZE):
        group = golden[start:start + GROUP_SIZE]
        answers = {}
        for a in call_llm(build_prompt(template, style_guide, group)).get("results", []):
            try:
                answers[int(a["id"])] = a
            except (KeyError, TypeError, ValueError):
                pass
        for i, row in enumerate(group, start=1):
            if i in answers:
                predictions[row["id"]] = answers[i]
        if start + GROUP_SIZE < len(golden):
            time.sleep(7)  # stay under the free-tier rate limit
    return predictions


# ---------------------------------------------------------------- statistics
def is_true(value):
    return str(value).strip().lower() in ("true", "yes", "1")


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


def counts(rows):
    c = {"TP": 0, "FP": 0, "FN": 0, "TN": 0}
    for r in rows:
        if r["outcome"] in c:
            c[r["outcome"]] += 1
    return c


def f1_of(rows):
    c = counts(rows)
    p, r = safe_div(c["TP"], c["TP"] + c["FP"]), safe_div(c["TP"], c["TP"] + c["FN"])
    return safe_div(2 * p * r, p + r)


def kappa_of(rows):
    """Cohen's kappa between the golden labels and the judge (critical vs. not)."""
    c = counts(rows)
    n = sum(c.values())
    if n == 0:
        return None
    observed = (c["TP"] + c["TN"]) / n
    gold_yes, judge_yes = (c["TP"] + c["FN"]) / n, (c["TP"] + c["FP"]) / n
    expected = gold_yes * judge_yes + (1 - gold_yes) * (1 - judge_yes)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def bootstrap_ci(rows, stat, resamples=2000, seed=42):
    """95% bootstrap confidence interval: re-score random resamples of the golden items."""
    rng = random.Random(seed)  # fixed seed so the same results always give the same interval
    values = []
    for _ in range(resamples):
        v = stat([rows[rng.randrange(len(rows))] for _ in rows])
        if v is not None:
            values.append(v)
    if not values:
        return None
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


def fmt(value, ci=None):
    if value is None:
        return "n/a"
    return f"{value:.2f} ({ci[0]:.2f}–{ci[1]:.2f})" if ci else f"{value:.2f}"


# ---------------------------------------------------------------- scoring
def score(predictions, golden):
    rows, category_hits = [], 0
    for g in golden:
        gold = is_true(g["critical"])
        p = predictions.get(g["id"])
        if p is None:
            outcome, pred, pred_cat, evidence, reason = "NO ANSWER", None, "", "", ""
        else:
            pred = is_true(p.get("critical"))
            pred_cat = str(p.get("category", ""))
            evidence, reason = str(p.get("evidence", "")), str(p.get("reason", ""))
            outcome = ("TP" if pred else "FN") if gold else ("FP" if pred else "TN")
            if outcome == "TP" and pred_cat == g["category"]:
                category_hits += 1
        rows.append({"id": g["id"], "source_en": g["source_en"], "translation_de": g["translation_de"],
                     "gold_critical": g["critical"], "gold_category": g["category"],
                     "judge_critical": "" if pred is None else ("yes" if pred else "no"),
                     "judge_category": pred_cat, "outcome": outcome,
                     "evidence": evidence, "reason": reason})
    c = counts(rows)
    precision = safe_div(c["TP"], c["TP"] + c["FP"])
    recall = safe_div(c["TP"], c["TP"] + c["FN"])
    answered = sum(c.values())
    kappa = kappa_of(rows)
    metrics = {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1_of(rows), 4),
        "accuracy": round(safe_div(c["TP"] + c["TN"], answered), 4),
        "kappa": None if kappa is None else round(kappa, 4),
        "category_accuracy": round(safe_div(category_hits, c["TP"]), 4),
    }
    scored = [r for r in rows if r["outcome"] != "NO ANSWER"]
    cis = {
        "precision": wilson(c["TP"], c["TP"] + c["FP"]),
        "recall": wilson(c["TP"], c["TP"] + c["FN"]),
        "accuracy": wilson(c["TP"] + c["TN"], answered),
        "f1": bootstrap_ci(scored, f1_of) if scored else None,
        "kappa": bootstrap_ci(scored, kappa_of) if scored else None,
    }
    return rows, c, metrics, cis


def save_baseline(metrics, rows, prompt_hash, source):
    BASELINE_METRICS.write_text(json.dumps(
        {"created_at": now.isoformat(timespec="seconds"), "source": source,
         "prompt_hash": prompt_hash, "model": MODEL, "metrics": metrics}, indent=2), encoding="utf-8")
    BASELINE_ITEMS.write_text(json.dumps(
        {"created_at": now.isoformat(timespec="seconds"), "prompt_hash": prompt_hash, "model": MODEL,
         "items": {r["id"]: r["outcome"] for r in rows}}, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- main
prompt_file = CONFIG["production_prompt"] if rebaseline else CONFIG["candidate_prompt"]
template = Path(prompt_file).read_text(encoding="utf-8")
style_guide = Path(CONFIG["style_guide"]).read_text(encoding="utf-8")
with open(CONFIG["golden_set"], encoding="utf-8") as f:
    golden = list(csv.DictReader(f))
for placeholder in ("{{STYLE_GUIDE}}", "{{ITEMS}}"):
    if placeholder not in template:
        sys.exit(f"{prompt_file} is missing the {placeholder} placeholder.")
prompt_hash = hashlib.sha256((template + style_guide).encode("utf-8")).hexdigest()[:8]
label = "production prompt (rebaseline)" if rebaseline else "candidate prompt"
print(f"Testing {label} {prompt_hash} with {MODEL} on {len(golden)} golden items...")

try:
    predictions = run_judge(template, style_guide, golden)
except (LLMUnavailable, RuntimeError) as err:
    sys.exit(f"Could not finish the evaluation, so nothing was promoted or changed. {err}")

rows, c, metrics, cis = score(predictions, golden)
missing = sum(r["outcome"] == "NO ANSWER" for r in rows)

baseline = json.loads(BASELINE_METRICS.read_text(encoding="utf-8")) if BASELINE_METRICS.exists() else None
baseline_items = json.loads(BASELINE_ITEMS.read_text(encoding="utf-8"))["items"] if BASELINE_ITEMS.exists() else None
notes = []
checks = []          # (description, passed, actual)
newly_missed, newly_caught, new_false_alarms = [], [], []

if rebaseline:
    if missing:
        sys.exit(f"The judge didn't answer {missing} golden items, so the baseline was not changed. Try again.")
    decision = "REBASELINED"
    save_baseline(metrics, rows, prompt_hash, "rebaseline")
    notes.append("The production prompt was re-scored and saved as the new baseline. Nothing was promoted.")
else:
    # 1. Completeness
    if missing:
        checks.append(("Judge answered every golden item", False, f"{missing} unanswered"))
    # 2. Thresholds
    for name, threshold in CONFIG["thresholds"].items():
        checks.append((f"{name} ≥ {threshold:.2f}", metrics[name] >= threshold, f"{metrics[name]:.2f}"))
    # 3. Aggregate regression vs. the production baseline
    max_drop = CONFIG["max_drop_vs_production"]
    if baseline:
        for name in CONFIG["thresholds"]:
            base = baseline["metrics"].get(name)
            if base is not None:
                checks.append((f"{name} no more than {max_drop:.2f} below production ({base:.2f})",
                               metrics[name] >= round(base - max_drop, 4), f"{metrics[name]:.2f}"))
        if baseline.get("model") and baseline["model"] != MODEL:
            notes.append(f"⚠️ The baseline was scored with `{baseline['model']}`, but this run used `{MODEL}`. "
                         "Differences may come from the model change, not the prompt. "
                         "Consider running the workflow in **rebaseline** mode.")
    else:
        notes.append("No production baseline yet, so only the thresholds were checked.")
    # 4. Item-level regression: critical items production caught that the candidate now misses
    if baseline_items:
        for r in rows:
            before = baseline_items.get(r["id"])
            if before == "TP" and r["outcome"] in ("FN", "NO ANSWER"):
                newly_missed.append(r)
            elif before == "FN" and r["outcome"] == "TP":
                newly_caught.append(r)
            elif before == "TN" and r["outcome"] == "FP":
                new_false_alarms.append(r)
        if BLOCK_NEW_MISSES:
            checks.append(("No critical item newly missed (vs. production)", not newly_missed,
                           ", ".join(r["id"] for r in newly_missed) or "none"))
    else:
        notes.append("Item-level comparison unavailable: production has no per-item baseline yet. "
                     "It is created automatically at the next promotion, or by running the workflow "
                     "in **rebaseline** mode.")

    passed = all(ok for _, ok, _ in checks)
    if not passed:
        decision = "REJECTED"
    elif promote:
        decision = "PROMOTED"
    else:
        decision = "PASSED (test only, not promoted)"

# ---------------------------------------------------------------- save results
RESULTS_DIR.mkdir(exist_ok=True)
with (RESULTS_DIR / f"{stamp}_{prompt_hash}.csv").open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

history = RESULTS_DIR / "regression_history.csv"
header = ["timestamp", "prompt_hash", "golden_items", "precision", "recall", "f1",
          "accuracy", "category_accuracy", "decision", "model", "kappa"]
old_rows = []
if history.exists():
    with history.open(newline="", encoding="utf-8") as f:
        old_rows = list(csv.reader(f))[1:]
old_rows = [r + [""] * (len(header) - len(r)) for r in old_rows if r]  # older rows lack newer columns
new_row = [now.isoformat(timespec="seconds"), prompt_hash, len(golden),
           *(f"{metrics[k]:.2f}" for k in ["precision", "recall", "f1", "accuracy", "category_accuracy"]),
           decision, MODEL, "" if metrics["kappa"] is None else f"{metrics['kappa']:.2f}"]
with history.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(header)
    writer.writerows(old_rows + [[str(x) for x in new_row]])

if decision == "PROMOTED":
    shutil.copyfile(CONFIG["candidate_prompt"], CONFIG["production_prompt"])
    save_baseline(metrics, rows, prompt_hash, "promotion")
    log = Path("prompts/promotion_log.csv")
    log_new = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if log_new:
            writer.writerow(["promoted_at", "prompt_hash", "precision", "recall", "f1"])
        writer.writerow([now.isoformat(timespec="seconds"), prompt_hash,
                         *(f"{metrics[k]:.2f}" for k in ["precision", "recall", "f1"])])

# ---------------------------------------------------------------- summary page
icon = {"PROMOTED": "✅", "REJECTED": "❌", "REBASELINED": "🔄"}.get(decision, "☑️")
lines = [f"## {icon} Prompt {prompt_hash}: {decision}", "",
         f"Model: `{MODEL}` · Golden items: **{len(golden)}** · "
         f"TP {c['TP']} · FP {c['FP']} · FN {c['FN']} · TN {c['TN']}", ""]
for note in notes:
    lines += [note, ""]
lines += ["Values in brackets are 95% confidence intervals. With a small golden set they are wide, "
          "so read small score differences with caution.", "",
          "| Metric | This run | Production baseline |", "|---|---|---|"]
for name in ["precision", "recall", "f1", "accuracy", "kappa", "category_accuracy"]:
    base = baseline["metrics"].get(name) if baseline and not rebaseline else None
    lines.append(f"| {name} | {fmt(metrics[name], cis.get(name))} | {fmt(base) if base is not None else 'n/a'} |")
if checks:
    lines += ["", "| Check | Result | Actual |", "|---|---|---|"]
    for desc, ok, actual in checks:
        lines.append(f"| {desc} | {'✅ pass' if ok else '❌ fail'} | {actual} |")


def item_table(title, items):
    if not items:
        return []
    out = ["", f"### {title}", "", "| ID | Translation | Gold category | Judge's reason |", "|---|---|---|---|"]
    out += [f"| {r['id']} | {r['translation_de']} | {r['gold_category']} | {r['reason']} |" for r in items]
    return out


lines += item_table("❌ Critical items newly missed (production caught these)", newly_missed)
lines += item_table("✅ Critical items newly caught (production missed these)", newly_caught)
lines += item_table("⚠️ New false alarms", new_false_alarms)
lines += item_table("All items the judge got wrong in this run",
                    [r for r in rows if r["outcome"] in ("FN", "FP", "NO ANSWER")])

summary = "\n".join(lines)
print(summary)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
        f.write(summary)

if decision == "REJECTED":
    sys.exit(1)  # a failed check marks the workflow run as failed
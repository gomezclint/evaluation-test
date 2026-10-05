"""Regression test for the business-risk judge prompt.

Runs the candidate prompt against the golden dataset and checks the scores
against the thresholds in eval_config.json and against the current production
prompt's scores. With --promote, a candidate that passes every check is
promoted automatically: it replaces the production prompt and becomes the new
baseline. A candidate that fails anything is rejected and production is untouched.
"""
import csv, hashlib, json, os, shutil, sys, time
from datetime import datetime, timezone
from pathlib import Path
import requests

CONFIG = json.loads(Path("eval_config.json").read_text(encoding="utf-8"))
MODEL = CONFIG["model"]
API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROUP_SIZE = 10   # golden items sent to the judge per request
RETRY_WAIT = 30   # seconds to wait once after a rate-limit or overload error before giving up
RESULTS_DIR = Path("regression_results")
promote = "--promote" in sys.argv
now = datetime.now(timezone.utc)
stamp = now.strftime("%Y-%m-%d_%H%M%S")


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


def is_true(value):
    return str(value).strip().lower() in ("true", "yes", "1")


def safe_div(a, b):
    return a / b if b else 0.0


# 1. Load everything
template = Path(CONFIG["candidate_prompt"]).read_text(encoding="utf-8")
style_guide = Path(CONFIG["style_guide"]).read_text(encoding="utf-8")
with open(CONFIG["golden_set"], encoding="utf-8") as f:
    golden = list(csv.DictReader(f))
for placeholder in ("{{STYLE_GUIDE}}", "{{ITEMS}}"):
    if placeholder not in template:
        sys.exit(f"The candidate prompt is missing the {placeholder} placeholder.")
prompt_hash = hashlib.sha256((template + style_guide).encode("utf-8")).hexdigest()[:8]
print(f"Testing candidate prompt {prompt_hash} on {len(golden)} golden items...")

# 2. Run the candidate prompt on the golden set
try:
    predictions = run_judge(template, style_guide, golden)
except (LLMUnavailable, RuntimeError) as err:
    sys.exit(f"Could not finish the evaluation, so nothing was promoted. {err}")

# 3. Score it (golden labels = ground truth; "positive" = critical business risk)
rows, tp, fp, fn, tn, missing, category_hits = [], 0, 0, 0, 0, 0, 0
for g in golden:
    gold = is_true(g["critical"])
    p = predictions.get(g["id"])
    if p is None:
        missing += 1
        outcome, pred, pred_cat, evidence, reason = "NO ANSWER", "", "", "", ""
    else:
        pred = is_true(p.get("critical"))
        pred_cat = str(p.get("category", ""))
        evidence, reason = str(p.get("evidence", "")), str(p.get("reason", ""))
        if gold and pred:
            tp += 1
            outcome = "TP"
            category_hits += pred_cat == g["category"]
        elif pred:
            fp += 1
            outcome = "FP"
        elif gold:
            fn += 1
            outcome = "FN"
        else:
            tn += 1
            outcome = "TN"
    rows.append({"id": g["id"], "source_en": g["source_en"], "translation_de": g["translation_de"],
                 "gold_critical": g["critical"], "gold_category": g["category"],
                 "judge_critical": "yes" if pred is True else ("no" if pred is False else ""),
                 "judge_category": pred_cat, "outcome": outcome,
                 "evidence": evidence, "reason": reason})

precision = safe_div(tp, tp + fp)
recall = safe_div(tp, tp + fn)
metrics = {
    "precision": round(precision, 4),
    "recall": round(recall, 4),
    "f1": round(safe_div(2 * precision * recall, precision + recall), 4),
    "accuracy": round(safe_div(tp + tn, tp + fp + fn + tn), 4),
    "category_accuracy": round(safe_div(category_hits, tp), 4),
}

# 4. Promotion checks
checks = []  # (description, passed, actual)
if missing:
    checks.append(("Judge answered every golden item", False, f"{missing} unanswered"))
for name, threshold in CONFIG["thresholds"].items():
    checks.append((f"{name} ≥ {threshold:.2f}", metrics[name] >= threshold, f"{metrics[name]:.2f}"))

baseline_path = Path(CONFIG["production_metrics"])
baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else None
max_drop = CONFIG["max_drop_vs_production"]
if baseline:
    for name in CONFIG["thresholds"]:
        base = baseline["metrics"].get(name)
        if base is not None:
            checks.append((f"{name} no more than {max_drop:.2f} below production ({base:.2f})",
                           metrics[name] >= round(base - max_drop, 4), f"{metrics[name]:.2f}"))

passed = all(ok for _, ok, _ in checks)
if not passed:
    decision = "REJECTED"
elif promote:
    decision = "PROMOTED"
else:
    decision = "PASSED (not promoted: run with --promote)"

# 5. Save the per-item results and the evaluation history
RESULTS_DIR.mkdir(exist_ok=True)
with (RESULTS_DIR / f"{stamp}_{prompt_hash}.csv").open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

history = RESULTS_DIR / "regression_history.csv"
new_file = not history.exists()
with history.open("a", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    if new_file:
        writer.writerow(["timestamp", "prompt_hash", "golden_items", "precision", "recall", "f1",
                         "accuracy", "category_accuracy", "decision"])
    writer.writerow([now.isoformat(timespec="seconds"), prompt_hash, len(golden),
                     *(f"{metrics[k]:.2f}" for k in ["precision", "recall", "f1", "accuracy", "category_accuracy"]),
                     decision])

# 6. Promote
if decision == "PROMOTED":
    shutil.copyfile(CONFIG["candidate_prompt"], CONFIG["production_prompt"])
    baseline_path.write_text(json.dumps({"promoted_at": now.isoformat(timespec="seconds"),
                                         "prompt_hash": prompt_hash, "metrics": metrics}, indent=2),
                             encoding="utf-8")
    log = Path("prompts/promotion_log.csv")
    log_new = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if log_new:
            writer.writerow(["promoted_at", "prompt_hash", "precision", "recall", "f1"])
        writer.writerow([now.isoformat(timespec="seconds"), prompt_hash,
                         *(f"{metrics[k]:.2f}" for k in ["precision", "recall", "f1"])])

# 7. Summary page
icon = {"PROMOTED": "✅", "REJECTED": "❌"}.get(decision, "☑️")
lines = [f"## {icon} Prompt {prompt_hash}: {decision}", "",
         f"Golden items: **{len(golden)}** · TP {tp} · FP {fp} · FN {fn} · TN {tn}", "",
         "| Metric | Candidate | Production |", "|---|---|---|"]
for name in ["precision", "recall", "f1", "accuracy", "category_accuracy"]:
    base = f"{baseline['metrics'][name]:.2f}" if baseline and name in baseline["metrics"] else "n/a"
    lines.append(f"| {name} | {metrics[name]:.2f} | {base} |")
lines += ["", "| Check | Result | Actual |", "|---|---|---|"]
for desc, ok, actual in checks:
    lines.append(f"| {desc} | {'✅ pass' if ok else '❌ fail'} | {actual} |")
if not baseline:
    lines += ["", "_No production baseline yet, so only the thresholds were checked._"]

misses = [r for r in rows if r["outcome"] in ("FN", "FP", "NO ANSWER")]
if misses:
    lines += ["", "### Items the judge got wrong", "",
              "| ID | Outcome | Translation | Gold category | Judge's reason |", "|---|---|---|---|---|"]
    for r in misses:
        lines.append(f"| {r['id']} | {r['outcome']} | {r['translation_de']} | {r['gold_category']} | {r['reason']} |")

summary = "\n".join(lines)
print(summary)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
        f.write(summary)

if not passed:
    sys.exit(1)  # a failed check marks the workflow run as failed

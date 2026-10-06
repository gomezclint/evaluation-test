"""Check the daily evaluation results against alert rules, and open, update, or close
GitHub issues labeled "eval-alert".

Usage (from the repository root):
  python analysis/check_alerts.py              quality rules + freshness (run after the daily comparison)
  python analysis/check_alerts.py --freshness  freshness only (run on its own schedule, to catch a pipeline that never ran)
  add --dry-run to print what would happen without touching GitHub issues

Each run also saves the status of every rule to analysis/reports/alerts.json, which the dashboard reads.

Rules (thresholds in analysis/alerts_config.json):
  kappa_floor   latest weighted kappa below the floor
  major_recall  latest share of linguist-marked major errors the judge also called major, below the floor
                (only checked when the day has enough major errors to be meaningful)
  kappa_drop    latest weighted kappa more than kappa_drop_max below the median of the previous 7 days
                (same SQL as analysis/queries/03_rolling_baseline.sql)
  freshness     no results for today
"""
import json, os, subprocess, sys
from datetime import datetime, timezone, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "alerts_config.json").read_text(encoding="utf-8"))
LABEL = "eval-alert"
STATUS_FILE = HERE / "reports" / "alerts.json"
freshness_only = "--freshness" in sys.argv
dry_run = "--dry-run" in sys.argv or not os.environ.get("GH_TOKEN")
today = datetime.now(timezone.utc).date()

repo = os.environ.get("GITHUB_REPOSITORY")
run_url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
           if repo and os.environ.get("GITHUB_RUN_ID") else None)

con, loaded = connect()


def one(sql, params=()):
    cur = con.execute(sql, params)
    row = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], row)) if row else None


# ---------------------------------------------------------------- rules
# Each rule returns (firing, detail). firing is None when there isn't enough data to judge.
def rule_freshness():
    if "daily_history" not in loaded:
        return True, "There are no daily results in the repository at all."
    latest = date.fromisoformat(one("SELECT MAX(date) AS d FROM daily_history")["d"])
    age = (today - latest).days
    if age > CONFIG["max_data_age_days"]:
        return True, (f"The latest daily results are from {latest}, {age} day(s) old. The daily export "
                      "or the comparison probably failed or didn't run. Check the Actions tab.")
    return False, f"Latest daily results are from {latest}."


def latest_history():
    return one("SELECT * FROM daily_history ORDER BY date DESC LIMIT 1") if "daily_history" in loaded else None


def rule_kappa_floor():
    h = latest_history()
    if not h or h.get("weighted_kappa") is None:
        return None, "No weighted kappa recorded for the latest day."
    k, floor = h["weighted_kappa"], CONFIG["weighted_kappa_floor"]
    if k < floor:
        return True, f"On {h['date']}, weighted kappa was {k:.2f}, below the floor of {floor:.2f}."
    return False, f"On {h['date']}, weighted kappa was {k:.2f} (floor {floor:.2f})."


def rule_major_recall():
    if "daily_results" not in loaded:
        return None, "No daily comparison files."
    r = one("""
        SELECT date,
               SUM(human_severity = 'major') AS majors,
               SUM(human_severity = 'major' AND llm_severity = 'major') AS caught
        FROM daily_results
        WHERE date = (SELECT MAX(date) FROM daily_results)
        GROUP BY date""")
    need = CONFIG["major_recall_min_examples"]
    if not r or r["majors"] < need:
        n = r["majors"] if r else 0
        return None, f"Only {n} major error(s) on the latest day; at least {need} are needed for a meaningful recall."
    recall, floor = r["caught"] / r["majors"], CONFIG["major_recall_floor"]
    detail = (f"On {r['date']}, the judge called {r['caught']} of {r['majors']} linguist-marked major errors major "
              f"(recall {recall:.2f}, floor {floor:.2f}).")
    return recall < floor, detail


def rule_kappa_drop():
    if "daily_history" not in loaded:
        return None, "No daily history."
    sql = (HERE / "queries" / "03_rolling_baseline.sql").read_text(encoding="utf-8")
    r = one(sql)  # first row = latest day
    if not r or r["median_prior_7_days"] is None or (r["days_in_window"] or 0) < CONFIG["kappa_drop_min_days"]:
        return None, f"Fewer than {CONFIG['kappa_drop_min_days']} earlier days in the 7-day window."
    drop, limit = -r["difference"], CONFIG["kappa_drop_max"]
    detail = (f"On {r['date']}, weighted kappa was {r['weighted_kappa']:.2f}, compared with a 7-day median of "
              f"{r['median_prior_7_days']:.2f} ({int(r['days_in_window'])} days).")
    return drop > limit, detail + (f" That's a drop of {drop:.2f}, more than the allowed {limit:.2f}." if drop > limit else "")


RULES = {"freshness": ("No fresh daily results", rule_freshness)}
if not freshness_only:
    RULES.update({
        "kappa_floor": ("Weighted kappa below floor", rule_kappa_floor),
        "major_recall": ("Major errors under-called", rule_major_recall),
        "kappa_drop": ("Sudden drop in agreement", rule_kappa_drop),
    })


# ---------------------------------------------------------------- GitHub issues
def gh(*args):
    cmd = ["gh", *args] + (["--repo", repo] if repo and args[0] in ("issue", "label") else [])
    if dry_run:
        print("[dry run] would run:", " ".join(cmd[:4]), "...")
        return "[]" if args[:2] == ("issue", "list") else ""
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def title_for(rule_id, name):
    return f"Eval alert: {name} [{rule_id}]"


gh("label", "create", LABEL, "--color", "D93F0B", "--description", "Automated evaluation alert", "--force")
open_issues = json.loads(gh("issue", "list", "--label", LABEL, "--state", "open",
                            "--json", "number,title", "--limit", "100") or "[]")


def find_open(rule_id):
    return next((i["number"] for i in open_issues if i["title"].endswith(f"[{rule_id}]")), None)


def issue_url(number):
    return f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/issues/{number}" if repo and number else None


# Keep the saved status of rules not checked in this run (the freshness-only run checks one rule)
status_doc = {"rules": {}}
if STATUS_FILE.exists():
    try:
        status_doc = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except ValueError:
        pass


footer = f"\n\nRun: {run_url}" if run_url else ""
summary = ["## Evaluation alerts", "", "| Rule | Status | Detail |", "|---|---|---|"]
for rule_id, (name, check) in RULES.items():
    firing, detail = check()
    existing = find_open(rule_id)
    issue, url = existing, issue_url(existing)
    if firing is None:
        status = "⏸️ not enough data"
    elif firing and existing:
        gh("issue", "comment", str(existing), "--body", f"Still firing on {today}.\n\n{detail}{footer}")
        status = f"🔴 firing (updated issue #{existing})"
    elif firing:
        body = (f"{detail}\n\nThis issue was opened automatically by `analysis/check_alerts.py`. "
                f"It closes itself once the rule passes again.{footer}")
        created = gh("issue", "create", "--title", title_for(rule_id, name), "--label", LABEL, "--body", body).strip()
        url = created if created.startswith("http") else None  # gh prints the new issue's URL
        status = "🔴 firing (new issue)"
    elif existing:
        gh("issue", "comment", str(existing), "--body", f"Recovered on {today}.\n\n{detail}{footer}")
        gh("issue", "close", str(existing))
        issue, url = None, None
        status = f"🟢 passing (closed issue #{existing})"
    else:
        status = "🟢 passing"
    status_doc["rules"][rule_id] = {
        "name": name, "detail": detail,
        "state": "no_data" if firing is None else ("firing" if firing else "passing"),
        "issue_url": url if firing else None,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    summary.append(f"| {rule_id} | {status} | {detail} |")

status_doc["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
STATUS_FILE.parent.mkdir(exist_ok=True)
STATUS_FILE.write_text(json.dumps(status_doc, indent=2), encoding="utf-8")

text = "\n".join(summary)
print(text)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
        f.write("\n" + text + "\n")

"""Run every SQL file in analysis/queries against the result files and write a report.

Usage (from the repository root):  python analysis/run_queries.py
Output: analysis/reports/latest.md (report), analysis/reports/latest.json (read by the dashboard),
plus the workflow run's summary page when run on GitHub.
"""
import json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect  # noqa: E402

HERE = Path(__file__).resolve().parent
QUERIES = sorted((HERE / "queries").glob("*.sql"))
REPORT = HERE / "reports" / "latest.md"
REPORT_JSON = HERE / "reports" / "latest.json"


def header(sql, key):
    m = re.search(rf"^--\s*{key}:\s*(.+)$", sql, flags=re.M)
    return m.group(1).strip() if m else ""


def markdown_table(columns, rows):
    def cell(v):
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:g}"
        return str(v).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    out += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


con, loaded = connect()
generated = datetime.now(timezone.utc)
now = generated.strftime("%Y-%m-%d %H:%M UTC")
results = []  # one entry per query, saved as JSON for the dashboard
lines = ["# SQL analysis report", "",
         f"Generated {now} from the repository's result files. "
         "Each section is one query in `analysis/queries/`.", "",
         "Tables loaded: " + (", ".join(f"`{t}` ({n} rows)" for t, n in loaded.items()) or "none"), ""]

for path in QUERIES:
    sql = path.read_text(encoding="utf-8")
    title = header(sql, "Title") or path.stem
    question = header(sql, "Question")
    entry = {"file": path.name, "title": title, "question": question, "status": "ok",
             "columns": [], "rows": [], "message": ""}
    results.append(entry)
    lines += [f"## {title}", "", f"*{question}*", "", f"Query: `{path.name}`", ""]
    required = [t.strip() for t in header(sql, "Requires").split(",") if t.strip()]
    missing = [t for t in required if t not in loaded]
    if missing:
        entry.update(status="no_data", message=f"No data yet: this query needs {', '.join(missing)}.")
        lines += [entry["message"], ""]
        continue
    try:
        cur = con.execute(sql)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description]
        entry.update(columns=columns, rows=[list(r) for r in rows])
        lines += [markdown_table(columns, rows) if rows else "The query returned no rows.", ""]
    except Exception as err:  # report the problem, keep running the other queries
        entry.update(status="error", message=f"This query failed: {err}")
        lines += [f"This query failed: `{err}`", ""]
        print(f"{path.name} failed: {err}")

report = "\n".join(lines)
REPORT.parent.mkdir(exist_ok=True)
REPORT.write_text(report, encoding="utf-8")
REPORT_JSON.write_text(json.dumps({"generated_at": generated.isoformat(timespec="seconds"),
                                   "tables_loaded": loaded, "queries": results}, indent=2), encoding="utf-8")
print(report)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
        f.write("\n" + report)

"""Load the repository's result files into an in-memory SQLite database, so they
can be queried with SQL. SQLite is built into Python, so nothing extra is installed.

Tables:
  daily_history       one row per day     (daily-exports/comparisons/metrics_history.csv)
  daily_results       one row per translation per day (daily-exports/comparisons/results/*.csv)
  regression_history  one row per regression run (prompt-management/regression_results/regression_history.csv)
  regression_items    one row per golden item per run (prompt-management/regression_results/<run>.csv)
"""
import csv, re, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    "daily_history": ROOT / "daily-exports/comparisons/metrics_history.csv",
    "daily_results": ROOT / "daily-exports/comparisons/results",
    "regression_history": ROOT / "prompt-management/regression_results/regression_history.csv",
    "regression_items": ROOT / "prompt-management/regression_results",
}


def _read(path, extra=None):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if extra:
        for r in rows:
            r.update(extra)
    return rows


def _is_number(v):
    try:
        float(v)
        return True
    except ValueError:
        return False


def _create(con, table, rows):
    if not rows:
        return 0
    columns = list(dict.fromkeys(k for r in rows for k in r))  # keep order, union of all files' columns
    numeric = {c for c in columns
               if all(_is_number(r.get(c, "")) for r in rows if r.get(c, "") not in ("", None))
               and any(r.get(c, "") not in ("", None) for r in rows)}
    col_defs = ", ".join('"%s" %s' % (c, "REAL" if c in numeric else "TEXT") for c in columns)
    con.execute(f"CREATE TABLE {table} ({col_defs})")

    def value(r, c):
        v = r.get(c, "")
        if v in ("", None):
            return None
        return float(v) if c in numeric else v

    con.executemany(f'INSERT INTO {table} VALUES ({", ".join("?" * len(columns))})',
                    [[value(r, c) for c in columns] for r in rows])
    return len(rows)


def connect():
    """Return (connection, {table: row count}) for every table that has data."""
    con = sqlite3.connect(":memory:")
    loaded = {}

    if SOURCES["daily_history"].exists():
        loaded["daily_history"] = _create(con, "daily_history", _read(SOURCES["daily_history"]))

    rows = []
    for p in sorted(SOURCES["daily_results"].glob("*_judge_comparison.csv")):
        rows += _read(p, {"date": p.name[:10]})
    loaded["daily_results"] = _create(con, "daily_results", rows)

    if SOURCES["regression_history"].exists():
        loaded["regression_history"] = _create(con, "regression_history", _read(SOURCES["regression_history"]))

    rows = []
    for p in sorted(SOURCES["regression_items"].glob("*.csv")):
        m = re.match(r"(\d{4}-\d{2}-\d{2}_\d{6})_([0-9a-f]+)\.csv$", p.name)  # <date>_<time>_<prompt hash>.csv
        if m:
            rows += _read(p, {"run": m.group(1), "prompt_hash": m.group(2)})
    loaded["regression_items"] = _create(con, "regression_items", rows)

    return con, {t: n for t, n in loaded.items() if n}

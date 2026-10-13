# SQL analysis report

Generated 2026-10-13 04:21 UTC from the repository's result files. Each section is one query in `analysis/queries/`.

Tables loaded: `daily_history` (11 rows), `daily_results` (209 rows), `regression_history` (6 rows), `regression_items` (156 rows)

## Judge bias

*When the judge disagrees with linguists, does it under-call or over-call severity?*

Query: `01_judge_bias.sql`

| outcome | translations | percent | of_which_missed_majors |
|---|---|---|---|
| Agreed | 103 | 49.3 | 0 |
| Judge over-called severity | 68 | 32.5 | 0 |
| Judge under-called severity | 38 | 18.2 | 12 |

## Weekly trend

*How do accuracy and agreement change week to week?*

Query: `02_weekly_trend.sql`

| week_starting | days | avg_accuracy | avg_macro_f1 | avg_weighted_kappa | lowest_weighted_kappa |
|---|---|---|---|---|---|
| 2026-10-12 | 2 | 0.57 | 0.45 | 0.43 | 0.35 |
| 2026-10-05 | 7 | 0.47 | 0.39 | 0.35 | -0.08 |
| 2026-09-28 | 2 | 0.45 | 0.35 |  |  |

## Kappa vs. 7-day median

*Is each day's agreement in line with the week before? The drop alert uses this.*

Query: `03_rolling_baseline.sql`

| date | weighted_kappa | median_prior_7_days | difference | days_in_window |
|---|---|---|---|---|
| 2026-10-13 | 0.52 | 0.43 | 0.09 | 7 |
| 2026-10-12 | 0.35 | 0.45 | -0.1 | 6 |
| 2026-10-11 | 0.47 | 0.43 | 0.04 | 5 |
| 2026-10-10 | 0.43 | 0.36 | 0.07 | 4 |
| 2026-10-09 | 0.26 | 0.46 | -0.2 | 3 |
| 2026-10-08 | 0.46 | 0.25 | 0.21 | 2 |
| 2026-10-07 | -0.08 | 0.58 | -0.66 | 1 |
| 2026-10-06 | 0.58 |  |  |  |

## Hardest golden items

*Which golden items do prompt versions get wrong most often?*

Query: `04_hardest_golden_items.sql`

Good news: no golden item has been missed in any run so far.

## Recall by risk category

*Which risk categories does the judge miss, and did the latest prompt help?*

Query: `05_recall_by_category.sql`

| category | items | caught_latest | recall_latest_percent | recall_previous_percent | recall_all_runs_percent |
|---|---|---|---|---|---|
| brand | 1 | 1 | 100 | 100 | 100 |
| financial_numeric | 3 | 3 | 100 | 100 | 100 |
| legal_privacy | 3 | 3 | 100 | 100 | 100 |
| offensive | 1 | 1 | 100 | 100 | 100 |
| safety | 5 | 5 | 100 | 100 | 100 |

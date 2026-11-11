# SQL analysis report

Generated 2026-11-11 11:48 UTC from the repository's result files. Each section is one query in `analysis/queries/`.

Tables loaded: `daily_history` (40 rows), `daily_results` (787 rows), `regression_history` (6 rows), `regression_items` (156 rows)

## Judge bias

*When the judge disagrees with linguists, does it under-call or over-call severity?*

Query: `01_judge_bias.sql`

| outcome | translations | percent | of_which_missed_majors |
|---|---|---|---|
| Agreed | 436 | 55.4 | 0 |
| Judge over-called severity | 236 | 30 | 0 |
| Judge under-called severity | 115 | 14.6 | 45 |

## Weekly trend

*How do accuracy and agreement change week to week?*

Query: `02_weekly_trend.sql`

| week_starting | days | avg_accuracy | avg_macro_f1 | avg_weighted_kappa | lowest_weighted_kappa |
|---|---|---|---|---|---|
| 2026-11-09 | 3 | 0.52 | 0.49 | 0.37 | 0.09 |
| 2026-11-02 | 7 | 0.59 | 0.43 | 0.36 | 0.15 |
| 2026-10-26 | 7 | 0.63 | 0.54 | 0.46 | 0.27 |
| 2026-10-19 | 7 | 0.54 | 0.35 | 0.32 | 0.2 |
| 2026-10-12 | 7 | 0.56 | 0.46 | 0.27 | -0.13 |
| 2026-10-05 | 7 | 0.47 | 0.39 | 0.35 | -0.08 |
| 2026-09-28 | 2 | 0.45 | 0.35 |  |  |

## Kappa vs. 7-day median

*Is each day's agreement in line with the week before? The drop alert uses this.*

Query: `03_rolling_baseline.sql`

| date | weighted_kappa | median_prior_7_days | difference | days_in_window |
|---|---|---|---|---|
| 2026-11-11 | 0.09 | 0.29 | -0.2 | 7 |
| 2026-11-10 | 0.73 | 0.29 | 0.44 | 7 |
| 2026-11-09 | 0.29 | 0.36 | -0.07 | 7 |
| 2026-11-08 | 0.25 | 0.37 | -0.12 | 7 |
| 2026-11-07 | 0.29 | 0.38 | -0.09 | 7 |
| 2026-11-06 | 0.37 | 0.38 | -0.01 | 7 |
| 2026-11-05 | 0.15 | 0.43 | -0.28 | 7 |
| 2026-11-04 | 0.36 | 0.43 | -0.07 | 7 |
| 2026-11-03 | 0.38 | 0.47 | -0.09 | 7 |
| 2026-11-02 | 0.71 | 0.47 | 0.24 | 7 |
| 2026-11-01 | 0.43 | 0.47 | -0.04 | 7 |
| 2026-10-31 | 0.47 | 0.33 | 0.14 | 7 |
| 2026-10-30 | 0.33 | 0.49 | -0.16 | 7 |
| 2026-10-29 | 0.66 | 0.3 | 0.36 | 7 |

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

# SQL analysis report

Generated 2026-11-25 14:07 UTC from the repository's result files. Each section is one query in `analysis/queries/`.

Tables loaded: `daily_history` (54 rows), `daily_results` (1061 rows), `regression_history` (6 rows), `regression_items` (156 rows)

## Judge bias

*When the judge disagrees with linguists, does it under-call or over-call severity?*

Query: `01_judge_bias.sql`

| outcome | translations | percent | of_which_missed_majors |
|---|---|---|---|
| Agreed | 572 | 53.9 | 0 |
| Judge over-called severity | 334 | 31.5 | 0 |
| Judge under-called severity | 155 | 14.6 | 60 |

## Weekly trend

*How do accuracy and agreement change week to week?*

Query: `02_weekly_trend.sql`

| week_starting | days | avg_accuracy | avg_macro_f1 | avg_weighted_kappa | lowest_weighted_kappa |
|---|---|---|---|---|---|
| 2026-11-23 | 3 | 0.51 | 0.45 | 0.37 | 0.15 |
| 2026-11-16 | 7 | 0.48 | 0.41 | 0.36 | 0.19 |
| 2026-11-09 | 7 | 0.52 | 0.46 | 0.43 | 0.09 |
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
| 2026-11-25 | 0.43 | 0.42 | 0.01 | 7 |
| 2026-11-24 | 0.15 | 0.42 | -0.27 | 7 |
| 2026-11-23 | 0.52 | 0.32 | 0.2 | 7 |
| 2026-11-22 | 0.28 | 0.42 | -0.14 | 7 |
| 2026-11-21 | 0.53 | 0.42 | 0.11 | 7 |
| 2026-11-20 | 0.32 | 0.43 | -0.11 | 7 |
| 2026-11-19 | 0.55 | 0.42 | 0.13 | 7 |
| 2026-11-18 | 0.42 | 0.39 | 0.03 | 7 |
| 2026-11-17 | 0.22 | 0.43 | -0.21 | 7 |
| 2026-11-16 | 0.19 | 0.43 | -0.24 | 7 |
| 2026-11-15 | 0.43 | 0.39 | 0.04 | 7 |
| 2026-11-14 | 0.55 | 0.29 | 0.26 | 7 |
| 2026-11-13 | 0.56 | 0.29 | 0.27 | 7 |
| 2026-11-12 | 0.39 | 0.29 | 0.1 | 7 |

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

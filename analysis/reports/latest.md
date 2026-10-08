# SQL analysis report

Generated 2026-10-08 04:20 UTC from the repository's result files. Each section is one query in `analysis/queries/`.

Tables loaded: `daily_history` (6 rows), `daily_results` (109 rows), `regression_history` (6 rows), `regression_items` (156 rows)

## Judge bias across all days

*When the judge disagrees with the linguists, does it tend to under-call or over-call severity?*

Query: `01_judge_bias.sql`

| outcome | translations | percent | of_which_missed_majors |
|---|---|---|---|
| Agreed | 47 | 43.1 | 0 |
| Judge over-called severity | 39 | 35.8 | 0 |
| Judge under-called severity | 23 | 21.1 | 9 |

## Weekly trend

*How do accuracy and agreement move week to week, and how many days is each week based on?*

Query: `02_weekly_trend.sql`

| week_starting | days | avg_accuracy | avg_macro_f1 | avg_weighted_kappa | lowest_weighted_kappa |
|---|---|---|---|---|---|
| 2026-10-05 | 4 | 0.42 | 0.37 | 0.32 | -0.08 |
| 2026-09-28 | 2 | 0.45 | 0.35 |  |  |

## Daily agreement vs. its 7-day baseline

*Is each day's weighted kappa in line with the median of the 7 days before it? (The drop alert uses this logic.)*

Query: `03_rolling_baseline.sql`

| date | weighted_kappa | median_prior_7_days | difference | days_in_window |
|---|---|---|---|---|
| 2026-10-08 | 0.46 | 0.25 | 0.21 | 2 |
| 2026-10-07 | -0.08 | 0.58 | -0.66 | 1 |
| 2026-10-06 | 0.58 |  |  |  |

## Hardest golden items

*Which golden items do prompt versions get wrong most often? These point to prompt gaps or ambiguous items.*

Query: `04_hardest_golden_items.sql`

The query returned no rows.

## Judge recall by risk category

*For each business-risk category, how many critical golden items does the judge catch, and did the latest prompt version help or hurt?*

Query: `05_recall_by_category.sql`

| category | items | caught_latest | recall_latest_percent | recall_previous_percent | recall_all_runs_percent |
|---|---|---|---|---|---|
| brand | 1 | 1 | 100 | 100 | 100 |
| financial_numeric | 3 | 3 | 100 | 100 | 100 |
| legal_privacy | 3 | 3 | 100 | 100 | 100 |
| offensive | 1 | 1 | 100 | 100 | 100 |
| safety | 5 | 5 | 100 | 100 | 100 |

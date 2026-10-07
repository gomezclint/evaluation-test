-- Title: Judge recall by risk category
-- Question: For each business-risk category, how many critical golden items does the judge catch, and did the latest prompt version help or hurt?
-- Requires: regression_items
WITH runs AS (                        -- every regression run, newest first
  SELECT DISTINCT run FROM regression_items
),
latest AS (SELECT run FROM runs ORDER BY run DESC LIMIT 1),
previous AS (SELECT run FROM runs ORDER BY run DESC LIMIT 1 OFFSET 1),
critical AS (                         -- only items that really are critical, so this is recall
  SELECT run, gold_category AS category, outcome = 'TP' AS caught
  FROM regression_items
  WHERE gold_critical = 'yes'
)
SELECT
  category,
  SUM(run = (SELECT run FROM latest)) AS items,
  SUM(run = (SELECT run FROM latest) AND caught) AS caught_latest,
  ROUND(100.0 * SUM(run = (SELECT run FROM latest) AND caught)
        / NULLIF(SUM(run = (SELECT run FROM latest)), 0)) AS recall_latest_percent,
  ROUND(100.0 * SUM(run = (SELECT run FROM previous) AND caught)
        / NULLIF(SUM(run = (SELECT run FROM previous)), 0)) AS recall_previous_percent,
  ROUND(100.0 * SUM(caught) / COUNT(*)) AS recall_all_runs_percent
FROM critical
GROUP BY category
ORDER BY recall_latest_percent, category;

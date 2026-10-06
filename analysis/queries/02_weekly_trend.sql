-- Title: Weekly trend
-- Question: How do accuracy and agreement move week to week, and how many days is each week based on?
-- Requires: daily_history
SELECT
  date(date, '-6 days', 'weekday 1') AS week_starting,
  COUNT(*) AS days,
  ROUND(AVG(accuracy), 2) AS avg_accuracy,
  ROUND(AVG(macro_f1), 2) AS avg_macro_f1,
  ROUND(AVG(weighted_kappa), 2) AS avg_weighted_kappa,
  ROUND(MIN(weighted_kappa), 2) AS lowest_weighted_kappa
FROM daily_history
GROUP BY week_starting
ORDER BY week_starting DESC
LIMIT 12;

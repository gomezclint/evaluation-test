-- Title: Hardest golden items
-- Question: Which golden items do prompt versions get wrong most often? These point to prompt gaps or ambiguous items.
-- Requires: regression_items
SELECT
  id,
  MAX(translation_de) AS translation,
  MAX(gold_category) AS expected,
  COUNT(*) AS runs,
  SUM(outcome IN ('FN', 'FP', 'NO ANSWER')) AS wrong,
  ROUND(100.0 * SUM(outcome IN ('FN', 'FP', 'NO ANSWER')) / COUNT(*)) AS percent_wrong,
  SUM(outcome = 'FN') AS missed_risk,
  SUM(outcome = 'FP') AS false_alarm
FROM regression_items
GROUP BY id
HAVING wrong > 0
ORDER BY wrong DESC, id
LIMIT 10;

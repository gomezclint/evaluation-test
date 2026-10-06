-- Title: Judge bias across all days
-- Question: When the judge disagrees with the linguists, does it tend to under-call or over-call severity?
-- Requires: daily_results
WITH scored AS (
  SELECT
    CASE human_severity WHEN 'no error' THEN 0 WHEN 'minor' THEN 1 WHEN 'major' THEN 2 END AS human_rank,
    CASE llm_severity   WHEN 'no error' THEN 0 WHEN 'minor' THEN 1 WHEN 'major' THEN 2 END AS judge_rank
  FROM daily_results
)
SELECT
  CASE
    WHEN judge_rank < human_rank THEN 'Judge under-called severity'
    WHEN judge_rank > human_rank THEN 'Judge over-called severity'
    ELSE 'Agreed'
  END AS outcome,
  COUNT(*) AS translations,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS percent,
  SUM(human_rank = 2 AND judge_rank < 2) AS of_which_missed_majors
FROM scored
GROUP BY outcome
ORDER BY translations DESC;

-- Title: Daily agreement vs. its 7-day baseline
-- Question: Is each day's weighted kappa in line with the median of the 7 days before it? (The drop alert uses this logic.)
-- Requires: daily_history
WITH kappa AS (
  SELECT date, weighted_kappa AS value FROM daily_history WHERE weighted_kappa IS NOT NULL
),
prior_days AS (                       -- every (day, earlier day within the previous 7 days) pair
  SELECT day.date AS date, earlier.value
  FROM kappa AS day
  JOIN kappa AS earlier
    ON earlier.date >= date(day.date, '-7 days') AND earlier.date < day.date
),
ranked AS (
  SELECT date, value,
         ROW_NUMBER() OVER (PARTITION BY date ORDER BY value) AS position,
         COUNT(*)     OVER (PARTITION BY date)                AS days_in_window
  FROM prior_days
),
median_7d AS (                        -- the middle value, or the average of the two middle values
  SELECT date, AVG(value) AS median, MAX(days_in_window) AS days_in_window
  FROM ranked
  WHERE position IN ((days_in_window + 1) / 2, (days_in_window + 2) / 2)
  GROUP BY date
)
SELECT
  k.date,
  ROUND(k.value, 2) AS weighted_kappa,
  ROUND(m.median, 2) AS median_prior_7_days,
  ROUND(k.value - m.median, 2) AS difference,
  m.days_in_window
FROM kappa AS k
LEFT JOIN median_7d AS m ON m.date = k.date
ORDER BY k.date DESC
LIMIT 14;

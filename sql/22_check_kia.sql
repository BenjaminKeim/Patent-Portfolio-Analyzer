.print ===== Kia vs Hyundai: disposition and observability =====
SELECT company_id,
       COUNT(*) AS apps,
       COUNT(*) FILTER (WHERE disposition='granted')    AS granted,
       COUNT(*) FILTER (WHERE disposition='abandoned')  AS abandoned,
       COUNT(*) FILTER (WHERE disposition='pending')    AS pending,
       COUNT(*) FILTER (WHERE child_observable)         AS child_observable,
       COUNT(*) FILTER (WHERE had_restriction)          AS had_restriction,
       COUNT(*) FILTER (WHERE first_action_allowance)   AS faa,
       COUNT(*) FILTER (WHERE n_child>0)                AS has_child,
       COUNT(*) FILTER (WHERE n_div>0)                  AS has_div
FROM app_flags WHERE company_id IN ('kia','hyundai','dell','micron')
GROUP BY 1 ORDER BY 1;

.print ===== Kia flag states =====
SELECT a1, b1, b2, COUNT(*) FROM app_flags WHERE company_id='kia'
GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 10;

.print ===== Kia filing years =====
SELECT filing_year, COUNT(*) AS apps,
       COUNT(*) FILTER (WHERE disposition='granted') AS granted,
       ROUND(AVG(office_actions),2) AS mean_oas
FROM app_flags WHERE company_id='kia' GROUP BY 1 ORDER BY 1;

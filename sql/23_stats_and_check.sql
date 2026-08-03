.print ===== national-stage rate sanity check (expect high for JP/EU/KR filers, ~0 for US-direct) =====
SELECT ac.company_id,
       COUNT(*) AS apps,
       ROUND(100.0*COUNT(*) FILTER (WHERE f.is_national_stage)/COUNT(*),1) AS nst_rate
FROM app_flags f JOIN app_company ac USING (application_number)
GROUP BY 1 ORDER BY nst_rate DESC;

-- headline stats: distinct applications, NOT the sum of per-company counts
COPY (
    SELECT
        (SELECT COUNT(*) FROM cohort)      AS distinct_applications,
        (SELECT COUNT(*) FROM app_company) AS company_memberships,
        (SELECT COUNT(*) FROM (SELECT application_number FROM app_company
                               GROUP BY 1 HAVING COUNT(*)>1)) AS jointly_held,
        (SELECT COUNT(*) FROM app_flags WHERE a1='FLAG')
      + (SELECT COUNT(*) FROM app_flags WHERE b1='FLAG')
      + (SELECT COUNT(*) FROM app_flags WHERE b2='FLAG') AS distinct_flag_rows,
        (SELECT COUNT(*) FROM app_flags WHERE a1='FLAG' OR b1='FLAG' OR b2='FLAG')
                                           AS distinct_flagged_applications
) TO 'site/public/data/stats.json' (FORMAT JSON, ARRAY true);

.print ===== stats written =====
SELECT (SELECT COUNT(*) FROM cohort) AS distinct_applications,
       (SELECT COUNT(*) FROM app_company) AS memberships,
       (SELECT COUNT(*) FROM app_flags WHERE a1='FLAG' OR b1='FLAG' OR b2='FLAG')
           AS distinct_flagged_applications;

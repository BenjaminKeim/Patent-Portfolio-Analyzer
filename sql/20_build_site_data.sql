-- Build the website data set: per-company metrics, year series, technology mix, rule flags.
-- Run: duckdb data/patex.duckdb -f sql/20_build_site_data.sql
--
-- Source: PatEx 2022 release (PEDS pull June 2023). Cohort: Utility, filing years 2013-2019.
--
-- JOINT FILINGS. An application may list applicants belonging to more than one tracked
-- company (Hyundai and Kia co-file heavily; an earlier build collapsed each application to
-- a single company and silently cut Kia from ~5,900 applications to 59). Application-level
-- facts are therefore computed ONCE per application, and company membership is a separate
-- many-to-many table. A jointly-filed application legitimately belongs to both portfolios,
-- so per-company figures are correct; the consequence is that company totals SUM to more
-- than the number of distinct applications, which the site must not present as a grand total.
--
-- OBSERVABILITY. Absence-based rules (A1/B1) can only assert "no child was filed" when
-- enough time passed before the June 2023 data pull for such a child to appear. Anything
-- disposed after OBSERVABLE_UNTIL is reported as INDETERMINATE, never as a flag. This is
-- the three-state design: PRESENT / CONFIRMED_ABSENT (=FLAG) / NOT_YET_OBSERVABLE.

SET VARIABLE observable_until = DATE '2022-06-30';

CREATE OR REPLACE TEMP MACRO norm(s) AS
    trim(regexp_replace(regexp_replace(upper(s), '[^A-Z0-9 ]', ' ', 'g'), ' +', ' ', 'g'));

-- ---------------------------------------------------------------- company membership (many-to-many)
CREATE OR REPLACE TABLE app_company AS
SELECT DISTINCT a.application_number, c.company_id
FROM application_data a
JOIN all_applicants ap USING (application_number)
JOIN classification c ON c.org_norm = norm(ap.applicant_organization)
WHERE a.application_invention_type = 'Utility'
  AND EXTRACT(YEAR FROM a.filing_date) BETWEEN 2013 AND 2019
  AND c.company_id IS NOT NULL;

-- ---------------------------------------------------------------- application-level cohort (one row per application)
CREATE OR REPLACE TABLE cohort AS
SELECT
    a.application_number,
    a.filing_date,
    EXTRACT(YEAR FROM a.filing_date)::INT AS filing_year,
    a.patent_number,
    a.patent_issue_date,
    a.appl_status_desc,
    a.appl_status_date,
    CASE substr(a.examiner_art_unit,1,2)
        WHEN '16' THEN '1600' WHEN '17' THEN '1700' WHEN '21' THEN '2100'
        WHEN '24' THEN '2400' WHEN '26' THEN '2600' WHEN '28' THEN '2800'
        WHEN '36' THEN '3600' WHEN '37' THEN '3700' ELSE 'other'
    END AS tech_center,
    CASE
        WHEN a.appl_status_desc LIKE 'Patented Case%'
          OR a.appl_status_desc LIKE 'Patent Expired Due to NonPayment%' THEN 'granted'
        WHEN a.appl_status_desc LIKE '%bandoned%'                        THEN 'abandoned'
        ELSE 'pending'
    END AS disposition,
    CASE
        WHEN a.appl_status_desc LIKE 'Patented Case%'
          OR a.appl_status_desc LIKE 'Patent Expired Due to NonPayment%' THEN a.patent_issue_date
        WHEN a.appl_status_desc LIKE '%bandoned%'                        THEN a.appl_status_date
    END AS disposal_date
FROM application_data a
WHERE a.application_number IN (SELECT application_number FROM app_company);

-- ---------------------------------------------------------------- prosecution events
CREATE OR REPLACE TABLE ev AS
SELECT t.application_number,
    MIN(CASE WHEN t.event_code IN ('CTNF','CTFR') THEN t.recorded_date END) AS first_rejection,
    MIN(CASE WHEN t.event_code = 'CTRS'           THEN t.recorded_date END) AS first_restriction,
    MIN(CASE WHEN t.event_code = 'MN/=.'          THEN t.recorded_date END) AS first_allowance,
    COUNT(*) FILTER (WHERE t.event_code IN ('CTNF','CTFR'))                 AS office_actions,
    COUNT(*) FILTER (WHERE t.event_code = 'RCEX')                           AS rce_count,
    COUNT(*) FILTER (WHERE t.event_code IN ('EXIN','EXAC','EXAT','EXET'))   AS interviews,
    COUNT(*) FILTER (WHERE t.event_code IN ('FAIA','FAOO'))                 AS fai_pilot,
    COUNT(*) FILTER (WHERE t.event_code = 'N/AP')                           AS appeals
FROM transactions t
JOIN cohort c USING (application_number)
GROUP BY 1;

-- ---------------------------------------------------------------- children (relationship + date)
-- continuation_type lives on the CHILD's row in continuity_parents, pointing at its parent.
-- child_filing_date lives in continuity_children. Join both to get type + date together.
CREATE OR REPLACE TABLE kids AS
SELECT
    cp.parent_application_number AS application_number,
    COUNT(*) FILTER (WHERE cp.continuation_type = 'DIV')                AS n_div,
    COUNT(*) FILTER (WHERE cp.continuation_type = 'CON')                AS n_con,
    COUNT(*) FILTER (WHERE cp.continuation_type = 'CIP')                AS n_cip,
    COUNT(*)                                                            AS n_child,
    MIN(cc.child_filing_date) FILTER (WHERE cp.continuation_type='DIV') AS first_div_date,
    MIN(cc.child_filing_date)                                           AS first_child_date
FROM continuity_parents cp
JOIN cohort c ON c.application_number = cp.parent_application_number
LEFT JOIN continuity_children cc
       ON cc.application_number       = cp.parent_application_number
      AND cc.child_application_number = cp.application_number
WHERE cp.continuation_type IN ('CON','DIV','CIP')
GROUP BY 1;

-- national-stage entries (§371) file under different practice; keep them separable
CREATE OR REPLACE TABLE route AS
SELECT DISTINCT application_number, TRUE AS is_national_stage
FROM continuity_parents WHERE continuation_type = 'NST';

-- ---------------------------------------------------------------- per-application facts
CREATE OR REPLACE TABLE app_facts AS
SELECT
    c.*,
    COALESCE(e.office_actions,0) AS office_actions,
    COALESCE(e.rce_count,0)      AS rce_count,
    COALESCE(e.interviews,0)     AS interviews,
    COALESCE(e.appeals,0)        AS appeals,
    e.first_rejection, e.first_restriction, e.first_allowance,
    COALESCE(e.fai_pilot,0) > 0  AS fai_pilot,
    COALESCE(k.n_div,0)   AS n_div,
    COALESCE(k.n_con,0)   AS n_con,
    COALESCE(k.n_child,0) AS n_child,
    k.first_child_date,
    COALESCE(r.is_national_stage,FALSE) AS is_national_stage,
    CASE WHEN c.disposition='granted' AND c.patent_issue_date IS NOT NULL
         THEN datediff('month', c.filing_date, c.patent_issue_date) END AS months_to_issue,
    (e.first_restriction IS NOT NULL) AS had_restriction,
    -- First-action allowance: a notice of allowance with no prior rejection.
    -- Standard definition - restrictions are not rejections on the merits and are
    -- reported separately. FAI pilot cases excluded; their "first action" is a
    -- different procedure and would inflate the rate.
    (e.first_allowance IS NOT NULL
     AND (e.first_rejection IS NULL OR e.first_allowance < e.first_rejection)
     AND COALESCE(e.fai_pilot,0) = 0) AS first_action_allowance,
    -- observable only if disposed early enough for a child to surface before the data pull
    (c.disposal_date IS NOT NULL
     AND c.disposal_date <= getvariable('observable_until')) AS child_observable
FROM cohort c
LEFT JOIN ev    e USING (application_number)
LEFT JOIN kids  k USING (application_number)
LEFT JOIN route r USING (application_number);

-- ---------------------------------------------------------------- three-state rule evaluation
CREATE OR REPLACE TABLE app_flags AS
SELECT *,
    -- A1: first-action allowance, no continuing application filed before issuance
    CASE WHEN NOT first_action_allowance OR disposition <> 'granted' THEN 'N/A'
         WHEN n_child > 0 AND first_child_date <= patent_issue_date  THEN 'PRESENT'
         WHEN NOT child_observable                                   THEN 'INDETERMINATE'
         ELSE 'FLAG' END AS a1,
    -- B1: restriction requirement issued, no divisional ever filed
    CASE WHEN NOT had_restriction OR disposition = 'pending'         THEN 'N/A'
         WHEN n_div > 0                                              THEN 'PRESENT'
         WHEN NOT child_observable                                   THEN 'INDETERMINATE'
         ELSE 'FLAG' END AS b1,
    -- B2: restriction issued, a child was filed but designated continuation, not divisional
    --     (§121 safe harbour may not attach - a risk flag warranting review, not a conclusion)
    CASE WHEN NOT had_restriction OR disposition = 'pending'         THEN 'N/A'
         WHEN n_div > 0                                              THEN 'PRESENT'
         WHEN n_con > 0                                              THEN 'FLAG'
         ELSE 'N/A' END AS b2
FROM app_facts;

.print ===== distinct applications vs sum of company memberships =====
SELECT (SELECT COUNT(*) FROM cohort)                       AS distinct_applications,
       (SELECT COUNT(*) FROM app_company)                  AS company_memberships,
       (SELECT COUNT(*) FROM (SELECT application_number FROM app_company
                              GROUP BY 1 HAVING COUNT(*)>1)) AS jointly_held_applications;

.print ===== which company pairs co-file? =====
SELECT a.company_id AS company_a, b.company_id AS company_b, COUNT(*) AS joint_applications
FROM app_company a JOIN app_company b
  ON a.application_number = b.application_number AND a.company_id < b.company_id
GROUP BY 1,2 ORDER BY joint_applications DESC LIMIT 10;

.print ===== per-company application counts (Kia should now be ~5,900, not 59) =====
SELECT ac.company_id, COUNT(*) AS applications
FROM app_company ac GROUP BY 1 ORDER BY applications DESC;

.print ===== rule flag counts (application level, deduplicated) =====
SELECT 'A1 first-action allowance, no continuation' AS rule,
       COUNT(*) FILTER (WHERE a1='FLAG')          AS flagged,
       COUNT(*) FILTER (WHERE a1='PRESENT')       AS ok,
       COUNT(*) FILTER (WHERE a1='INDETERMINATE') AS indeterminate
FROM app_flags
UNION ALL SELECT 'B1 restriction, no divisional',
       COUNT(*) FILTER (WHERE b1='FLAG'), COUNT(*) FILTER (WHERE b1='PRESENT'),
       COUNT(*) FILTER (WHERE b1='INDETERMINATE') FROM app_flags
UNION ALL SELECT 'B2 restriction, child filed as CON not DIV',
       COUNT(*) FILTER (WHERE b2='FLAG'), COUNT(*) FILTER (WHERE b2='PRESENT'),
       COUNT(*) FILTER (WHERE b2='INDETERMINATE') FROM app_flags;

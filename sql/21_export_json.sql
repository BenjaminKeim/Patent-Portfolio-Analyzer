-- Export website data as JSON.
-- Run: duckdb data/patex.duckdb -f sql/21_export_json.sql
-- Company figures come from app_flags JOIN app_company (many-to-many), so a jointly
-- filed application counts for each company that filed it.

CREATE OR REPLACE TEMP TABLE seeds2 AS
SELECT company_id, display_name, ifi_rank
FROM read_csv('config/canonical_seeds.csv', header = true);

-- Per-company view of every application-level fact.
CREATE OR REPLACE TEMP TABLE cf AS
SELECT ac.company_id, f.*
FROM app_flags f JOIN app_company ac USING (application_number);

-- applicant-organization coverage by filing year: 2013-2014 are materially incomplete
-- because AIA applicant recording only ramped up after Sept 2012. The site shows this
-- so nobody reads the ramp as a real filing trend.
CREATE OR REPLACE TEMP TABLE coverage AS
SELECT EXTRACT(YEAR FROM a.filing_date)::INT AS year,
       ROUND(100.0*COUNT(ap.applicant_organization)/COUNT(*),1) AS coverage_pct
FROM application_data a
LEFT JOIN all_applicants ap USING (application_number)
WHERE a.application_invention_type='Utility'
  AND EXTRACT(YEAR FROM a.filing_date) BETWEEN 2013 AND 2019
GROUP BY 1;

CREATE OR REPLACE TEMP TABLE company_metrics AS
SELECT
    company_id,
    COUNT(*)                                                        AS applications,
    COUNT(*) FILTER (WHERE disposition='granted')                   AS granted,
    COUNT(*) FILTER (WHERE disposition='abandoned')                 AS abandoned,
    COUNT(*) FILTER (WHERE disposition='pending')                   AS pending,
    ROUND(100.0*COUNT(*) FILTER (WHERE disposition='granted')
          / NULLIF(COUNT(*) FILTER (WHERE disposition IN ('granted','abandoned')),0),1)
                                                                    AS allowance_rate,
    ROUND(median(months_to_issue),1)                                AS median_months_to_issue,
    ROUND(AVG(office_actions),2)                                    AS mean_office_actions,
    ROUND(100.0*COUNT(*) FILTER (WHERE had_restriction)/COUNT(*),1) AS restriction_rate,
    ROUND(100.0*COUNT(*) FILTER (WHERE first_action_allowance)/COUNT(*),1) AS faa_rate,
    ROUND(100.0*COUNT(*) FILTER (WHERE is_national_stage)/COUNT(*),1)      AS national_stage_rate,
    ROUND(AVG(rce_count),2)                                         AS mean_rces,
    ROUND(100.0*COUNT(*) FILTER (WHERE interviews>0)/COUNT(*),1)    AS interview_rate,
    COUNT(*) FILTER (WHERE a1='FLAG')          AS a1_flag,
    COUNT(*) FILTER (WHERE a1='PRESENT')       AS a1_present,
    COUNT(*) FILTER (WHERE a1='INDETERMINATE') AS a1_indeterminate,
    COUNT(*) FILTER (WHERE b1='FLAG')          AS b1_flag,
    COUNT(*) FILTER (WHERE b1='PRESENT')       AS b1_present,
    COUNT(*) FILTER (WHERE b1='INDETERMINATE') AS b1_indeterminate,
    COUNT(*) FILTER (WHERE b2='FLAG')          AS b2_flag
FROM cf GROUP BY 1;

-- ---------------------------------------------------------------- index file
COPY (
    SELECT
        s.company_id AS id, s.display_name AS name, s.ifi_rank,
        m.applications, m.granted, m.abandoned, m.pending,
        m.allowance_rate, m.median_months_to_issue, m.mean_office_actions,
        m.restriction_rate, m.faa_rate, m.national_stage_rate,
        m.mean_rces, m.interview_rate,
        struct_pack(
            a1 := struct_pack(flagged := m.a1_flag, present := m.a1_present,
                              indeterminate := m.a1_indeterminate,
                              rate := ROUND(100.0*m.a1_flag/NULLIF(m.a1_flag+m.a1_present,0),1)),
            b1 := struct_pack(flagged := m.b1_flag, present := m.b1_present,
                              indeterminate := m.b1_indeterminate,
                              rate := ROUND(100.0*m.b1_flag/NULLIF(m.b1_flag+m.b1_present,0),1)),
            b2 := struct_pack(flagged := m.b2_flag, present := m.b1_present,
                              indeterminate := 0,
                              rate := ROUND(100.0*m.b2_flag/NULLIF(m.b2_flag+m.b1_present,0),1))
        ) AS flags
    FROM seeds2 s JOIN company_metrics m USING (company_id)
    ORDER BY s.ifi_rank
) TO 'site/public/data/companies.json' (FORMAT JSON, ARRAY true);

-- ---------------------------------------------------------------- per-company detail
COPY (
    WITH by_year AS (
        SELECT company_id, filing_year AS year,
               COUNT(*) AS filed,
               COUNT(*) FILTER (WHERE disposition='granted')   AS granted,
               COUNT(*) FILTER (WHERE disposition='abandoned') AS abandoned,
               COUNT(*) FILTER (WHERE disposition='pending')   AS pending,
               ROUND(100.0*COUNT(*) FILTER (WHERE disposition='granted')
                     / NULLIF(COUNT(*) FILTER (WHERE disposition IN ('granted','abandoned')),0),1)
                                                               AS allowance_rate,
               ROUND(median(months_to_issue),1)                AS median_months_to_issue,
               ROUND(AVG(office_actions),2)                    AS mean_office_actions,
               ROUND(100.0*COUNT(*) FILTER (WHERE had_restriction)/COUNT(*),1) AS restriction_rate
        FROM cf GROUP BY 1,2
    ),
    tech AS (
        SELECT company_id, tech_center, COUNT(*) AS applications,
               ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (PARTITION BY company_id),1) AS pct
        FROM cf GROUP BY 1,2
    ),
    flagged AS (
        SELECT company_id, application_number, 'A1' AS rule, filing_date, patent_number,
               patent_issue_date, tech_center, office_actions
        FROM cf WHERE a1='FLAG'
        UNION ALL
        SELECT company_id, application_number, 'B1', filing_date, patent_number,
               patent_issue_date, tech_center, office_actions
        FROM cf WHERE b1='FLAG'
        UNION ALL
        SELECT company_id, application_number, 'B2', filing_date, patent_number,
               patent_issue_date, tech_center, office_actions
        FROM cf WHERE b2='FLAG'
    )
    SELECT
        s.company_id AS id, s.display_name AS name, s.ifi_rank,
        (SELECT list(struct_pack(
                year := y.year, filed := y.filed, granted := y.granted,
                abandoned := y.abandoned, pending := y.pending,
                allowance_rate := y.allowance_rate,
                median_months_to_issue := y.median_months_to_issue,
                mean_office_actions := y.mean_office_actions,
                restriction_rate := y.restriction_rate,
                coverage_pct := cv.coverage_pct) ORDER BY y.year)
         FROM by_year y JOIN coverage cv ON cv.year = y.year
         WHERE y.company_id = s.company_id) AS by_year,
        (SELECT list(struct_pack(tech_center := t.tech_center,
                                 applications := t.applications, pct := t.pct)
                     ORDER BY t.applications DESC)
         FROM tech t WHERE t.company_id = s.company_id) AS tech,
        (SELECT list(struct_pack(
                application := fl.application_number, rule := fl.rule,
                filed := fl.filing_date, patent := fl.patent_number,
                issued := fl.patent_issue_date, tech_center := fl.tech_center,
                office_actions := fl.office_actions) ORDER BY fl.filing_date DESC)
         FROM flagged fl WHERE fl.company_id = s.company_id) AS flagged
    FROM seeds2 s ORDER BY s.ifi_rank
) TO 'site/public/data/_details.json' (FORMAT JSON, ARRAY true);

.print ===== per-company summary =====
SELECT s.ifi_rank, s.display_name, m.applications, m.allowance_rate,
       m.median_months_to_issue, m.restriction_rate, m.faa_rate,
       m.a1_flag, m.b1_flag, m.b2_flag
FROM seeds2 s JOIN company_metrics m USING (company_id) ORDER BY s.ifi_rank;

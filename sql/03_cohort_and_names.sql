-- (a) validate the cohort year choice, (b) build the disambiguation worksheet.
-- Run: duckdb data/patex.duckdb -f sql/03_cohort_and_names.sql

.print ===== A. disposition completeness by filing year (Utility only) =====
SELECT
    EXTRACT(YEAR FROM filing_date) AS filing_year,
    COUNT(*) AS apps,
    ROUND(100.0 * SUM(CASE WHEN appl_status_desc LIKE 'Patented Case%'
                             OR appl_status_desc LIKE 'Patent Expired Due to NonPayment%'
                            THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_granted,
    ROUND(100.0 * SUM(CASE WHEN appl_status_desc LIKE '%bandoned%'
                            THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_abandoned,
    ROUND(100.0 * SUM(CASE WHEN appl_status_desc LIKE 'Patented Case%'
                             OR appl_status_desc LIKE 'Patent Expired Due to NonPayment%'
                             OR appl_status_desc LIKE '%bandoned%'
                            THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_disposed
FROM application_data
WHERE application_invention_type = 'Utility'
  AND EXTRACT(YEAR FROM filing_date) BETWEEN 2012 AND 2019
GROUP BY 1 ORDER BY 1;

.print ===== B. applicant_organization strings, 2015 Utility filings, by company stem =====
WITH c AS (
    SELECT a.application_number, ap.applicant_organization AS org
    FROM application_data a
    JOIN all_applicants ap USING (application_number)
    WHERE a.application_invention_type = 'Utility'
      AND EXTRACT(YEAR FROM a.filing_date) = 2015
      AND ap.applicant_organization IS NOT NULL
),
tagged AS (
    SELECT
        CASE
            WHEN org ILIKE '%SAMSUNG%'              THEN '01 SAMSUNG'
            WHEN org ILIKE '%TAIWAN SEMICONDUCTOR%'
              OR org ILIKE '%TSMC%'                 THEN '02 TSMC'
            WHEN org ILIKE '%QUALCOMM%'             THEN '03 QUALCOMM'
            WHEN org ILIKE '%HUAWEI%'               THEN '04 HUAWEI'
            WHEN org ILIKE '%APPLE%'                THEN '05 APPLE'
            WHEN org ILIKE '%CANON%'                THEN '06 CANON'
            WHEN org ILIKE '%TOYOTA%'               THEN '07 TOYOTA'
            WHEN org ILIKE '%DELL%'                 THEN '08 DELL'
            WHEN org ILIKE 'LG %' OR org ILIKE '%LG ELECTRONICS%'
              OR org ILIKE '%LG DISPLAY%' OR org ILIKE '%LG CHEM%'
              OR org ILIKE '%LG INNOTEK%'           THEN '09 LG'
        END AS stem,
        org
    FROM c
)
SELECT stem, org, COUNT(*) AS applications_2015
FROM tagged
WHERE stem IS NOT NULL
GROUP BY 1, 2
HAVING COUNT(*) >= 5
ORDER BY stem, applications_2015 DESC;

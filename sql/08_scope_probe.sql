-- Sizing the disambiguation problem for 20 companies x 2012-2019,
-- and probing whether attorney docket number is a usable non-string signal.

CREATE OR REPLACE TEMP TABLE pool AS
SELECT
    a.application_number,
    EXTRACT(YEAR FROM a.filing_date) AS fy,
    a.atty_docket_number,
    ap.applicant_country_code AS cc,
    ap.applicant_city_name AS city,
    trim(regexp_replace(regexp_replace(upper(ap.applicant_organization),
        '[^A-Z0-9 ]', ' ', 'g'), ' +', ' ', 'g')) AS org_norm,
    CASE
        WHEN ap.applicant_organization ILIKE '%SAMSUNG%'   THEN 'SAMSUNG'
        WHEN ap.applicant_organization ILIKE '%TAIWAN SEMICONDUCTOR%'
          OR ap.applicant_organization ILIKE '%TSMC%'      THEN 'TSMC'
        WHEN ap.applicant_organization ILIKE '%QUALCOMM%'  THEN 'QUALCOMM'
        WHEN ap.applicant_organization ILIKE '%HUAWEI%'    THEN 'HUAWEI'
        WHEN ap.applicant_organization ILIKE '%APPLE%'     THEN 'APPLE'
        WHEN ap.applicant_organization ILIKE '%CANON%'     THEN 'CANON'
        WHEN ap.applicant_organization ILIKE '%TOYOTA%'    THEN 'TOYOTA'
        WHEN ap.applicant_organization ILIKE '%DELL%'      THEN 'DELL'
        WHEN ap.applicant_organization ILIKE '%LG %'
          OR ap.applicant_organization ILIKE 'LG%'         THEN 'LG'
        WHEN ap.applicant_organization ILIKE '%INTERNATIONAL BUSINESS MACHINES%'
          OR ap.applicant_organization ILIKE '%IBM%'       THEN 'IBM'
        WHEN ap.applicant_organization ILIKE '%INTEL%'     THEN 'INTEL'
        WHEN ap.applicant_organization ILIKE '%BOE %'      THEN 'BOE'
        WHEN ap.applicant_organization ILIKE '%GOOGLE%'    THEN 'GOOGLE'
        WHEN ap.applicant_organization ILIKE '%MICROSOFT%' THEN 'MICROSOFT'
        WHEN ap.applicant_organization ILIKE '%HYUNDAI%'   THEN 'HYUNDAI'
        WHEN ap.applicant_organization ILIKE '%KIA %'      THEN 'KIA'
        WHEN ap.applicant_organization ILIKE '%ERICSSON%'  THEN 'ERICSSON'
        WHEN ap.applicant_organization ILIKE '%MICRON%'    THEN 'MICRON'
        WHEN ap.applicant_organization ILIKE '%AMAZON%'    THEN 'AMAZON'
    END AS stem
FROM application_data a
JOIN all_applicants ap USING (application_number)
WHERE a.application_invention_type = 'Utility'
  AND EXTRACT(YEAR FROM a.filing_date) BETWEEN 2012 AND 2019
  AND ap.applicant_organization IS NOT NULL;

.print ===== A. review burden: distinct names per stem, and how the volume tail falls =====
WITH n AS (
    SELECT stem, org_norm, COUNT(*) AS apps
    FROM pool WHERE stem IS NOT NULL GROUP BY 1,2
)
SELECT stem,
       COUNT(*) AS distinct_names,
       SUM(CASE WHEN apps >= 10 THEN 1 ELSE 0 END) AS names_ge10,
       SUM(CASE WHEN apps BETWEEN 3 AND 9 THEN 1 ELSE 0 END) AS names_3to9,
       SUM(CASE WHEN apps <= 2 THEN 1 ELSE 0 END) AS names_le2,
       SUM(apps) AS total_apps,
       SUM(CASE WHEN apps <= 2 THEN apps ELSE 0 END) AS apps_in_le2_tail
FROM n GROUP BY 1 ORDER BY total_apps DESC;

.print ===== B. grand totals =====
WITH n AS (
    SELECT stem, org_norm, COUNT(*) AS apps
    FROM pool WHERE stem IS NOT NULL GROUP BY 1,2
)
SELECT COUNT(*) AS all_distinct_names,
       SUM(CASE WHEN apps >= 10 THEN 1 ELSE 0 END) AS names_ge10,
       SUM(CASE WHEN apps BETWEEN 3 AND 9 THEN 1 ELSE 0 END) AS names_3to9,
       SUM(CASE WHEN apps <= 2 THEN 1 ELSE 0 END) AS names_le2,
       SUM(apps) AS total_apps,
       ROUND(100.0*SUM(CASE WHEN apps <= 2 THEN apps ELSE 0 END)/SUM(apps),2) AS pct_apps_in_tail
FROM n;

.print ===== C. Microsoft entity breakdown (his client - sanity check) =====
SELECT org_norm, COUNT(*) AS apps, ANY_VALUE(cc) AS cc, ANY_VALUE(city) AS city
FROM pool WHERE stem='MICROSOFT' GROUP BY 1 ORDER BY apps DESC LIMIT 12;

.print ===== D. is atty_docket_number a usable signal? Samsung entities =====
SELECT org_norm,
       COUNT(*) AS apps,
       COUNT(atty_docket_number) AS with_docket,
       ANY_VALUE(atty_docket_number) AS example_docket
FROM pool WHERE stem='SAMSUNG' GROUP BY 1 ORDER BY apps DESC LIMIT 8;

.print ===== E. country/city as a signal: Samsung entities =====
SELECT org_norm, cc, city, COUNT(*) AS apps
FROM pool WHERE stem='SAMSUNG' GROUP BY 1,2,3 ORDER BY apps DESC LIMIT 12;

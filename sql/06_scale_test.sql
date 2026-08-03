-- How far can the cohort be expanded, and what does it cost?

.print ===== A. applicant_organization coverage, 2008-2020 (the real constraint) =====
SELECT
    EXTRACT(YEAR FROM a.filing_date) AS filing_year,
    COUNT(*) AS utility_apps,
    COUNT(ap.applicant_organization) AS with_org,
    ROUND(100.0 * COUNT(ap.applicant_organization) / COUNT(*), 1) AS pct_with_org
FROM application_data a
LEFT JOIN all_applicants ap USING (application_number)
WHERE a.application_invention_type = 'Utility'
  AND EXTRACT(YEAR FROM a.filing_date) BETWEEN 2008 AND 2020
GROUP BY 1 ORDER BY 1;

.print ===== B. top-20 stems, applications per filing year 2013-2018 =====
WITH c AS (
    SELECT EXTRACT(YEAR FROM a.filing_date) AS fy, ap.applicant_organization AS org
    FROM application_data a
    JOIN all_applicants ap USING (application_number)
    WHERE a.application_invention_type = 'Utility'
      AND EXTRACT(YEAR FROM a.filing_date) BETWEEN 2013 AND 2018
      AND ap.applicant_organization IS NOT NULL
),
tagged AS (
    SELECT fy,
        CASE
            WHEN org ILIKE 'SAMSUNG ELECTRONICS%'                THEN '01 Samsung Electronics'
            WHEN org ILIKE 'TAIWAN SEMICONDUCTOR%'               THEN '02 TSMC'
            WHEN org ILIKE 'QUALCOMM%'                           THEN '03 Qualcomm'
            WHEN org ILIKE 'HUAWEI%'                             THEN '04 Huawei'
            WHEN org ILIKE 'SAMSUNG DISPLAY%'                    THEN '05 Samsung Display'
            WHEN org ILIKE 'APPLE INC%'                          THEN '06 Apple'
            WHEN org ILIKE 'CANON KABUSHIKI%'                    THEN '07 Canon'
            WHEN org ILIKE 'TOYOTA JIDOSHA%'                     THEN '08 Toyota'
            WHEN org ILIKE 'DELL PRODUCTS%'                      THEN '09 Dell'
            WHEN org ILIKE 'LG ELECTRONICS%'                     THEN '10 LG Electronics'
            WHEN org ILIKE 'INTERNATIONAL BUSINESS MACHINES%'    THEN '11 IBM'
            WHEN org ILIKE 'INTEL CORP%'                         THEN '12 Intel'
            WHEN org ILIKE 'BOE TECHNOLOGY%'                     THEN '13 BOE'
            WHEN org ILIKE 'GOOGLE%'                             THEN '14 Google'
            WHEN org ILIKE 'MICROSOFT%'                          THEN '15 Microsoft'
            WHEN org ILIKE 'HYUNDAI MOTOR%'                      THEN '16 Hyundai'
            WHEN org ILIKE 'KIA MOTORS%' OR org ILIKE 'KIA CORP%' THEN '17 Kia'
            WHEN org ILIKE '%ERICSSON%'                          THEN '18 Ericsson'
            WHEN org ILIKE 'MICRON TECHNOLOGY%'                  THEN '19 Micron'
            WHEN org ILIKE 'AMAZON TECHNOLOGIES%'                THEN '20 Amazon'
        END AS company
    FROM c
)
SELECT company,
       SUM(CASE WHEN fy=2013 THEN 1 ELSE 0 END) AS y2013,
       SUM(CASE WHEN fy=2014 THEN 1 ELSE 0 END) AS y2014,
       SUM(CASE WHEN fy=2015 THEN 1 ELSE 0 END) AS y2015,
       SUM(CASE WHEN fy=2016 THEN 1 ELSE 0 END) AS y2016,
       SUM(CASE WHEN fy=2017 THEN 1 ELSE 0 END) AS y2017,
       SUM(CASE WHEN fy=2018 THEN 1 ELSE 0 END) AS y2018,
       COUNT(*) AS total_2013_2018
FROM tagged
WHERE company IS NOT NULL
GROUP BY 1 ORDER BY 1;

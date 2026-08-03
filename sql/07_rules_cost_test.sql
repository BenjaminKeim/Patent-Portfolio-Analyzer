-- Representative rules-weight query: joins the 507M-row transactions table
-- for the full top-20 / 2015-2018 cohort. Measures real cost of the rules pass.

CREATE OR REPLACE TEMP TABLE cohort AS
SELECT * FROM (
SELECT a.application_number, a.filing_date, a.patent_number, a.patent_issue_date,
       a.appl_status_desc,
    CASE
        WHEN ap.applicant_organization ILIKE 'SAMSUNG ELECTRONICS%'             THEN 'Samsung Electronics'
        WHEN ap.applicant_organization ILIKE 'TAIWAN SEMICONDUCTOR%'            THEN 'TSMC'
        WHEN ap.applicant_organization ILIKE 'QUALCOMM%'                        THEN 'Qualcomm'
        WHEN ap.applicant_organization ILIKE 'HUAWEI%'                          THEN 'Huawei'
        WHEN ap.applicant_organization ILIKE 'SAMSUNG DISPLAY%'                 THEN 'Samsung Display'
        WHEN ap.applicant_organization ILIKE 'APPLE INC%'                       THEN 'Apple'
        WHEN ap.applicant_organization ILIKE 'CANON KABUSHIKI%'                 THEN 'Canon'
        WHEN ap.applicant_organization ILIKE 'TOYOTA JIDOSHA%'                  THEN 'Toyota'
        WHEN ap.applicant_organization ILIKE 'DELL PRODUCTS%'                   THEN 'Dell'
        WHEN ap.applicant_organization ILIKE 'LG ELECTRONICS%'                  THEN 'LG Electronics'
        WHEN ap.applicant_organization ILIKE 'INTERNATIONAL BUSINESS MACHINES%' THEN 'IBM'
        WHEN ap.applicant_organization ILIKE 'INTEL CORP%'                      THEN 'Intel'
        WHEN ap.applicant_organization ILIKE 'BOE TECHNOLOGY%'                  THEN 'BOE'
        WHEN ap.applicant_organization ILIKE 'GOOGLE%'                          THEN 'Google'
        WHEN ap.applicant_organization ILIKE 'MICROSOFT%'                       THEN 'Microsoft'
        WHEN ap.applicant_organization ILIKE 'HYUNDAI MOTOR%'                   THEN 'Hyundai'
        WHEN ap.applicant_organization ILIKE 'KIA MOTORS%'
          OR ap.applicant_organization ILIKE 'KIA CORP%'                        THEN 'Kia'
        WHEN ap.applicant_organization ILIKE '%ERICSSON%'                       THEN 'Ericsson'
        WHEN ap.applicant_organization ILIKE 'MICRON TECHNOLOGY%'               THEN 'Micron'
        WHEN ap.applicant_organization ILIKE 'AMAZON TECHNOLOGIES%'             THEN 'Amazon'
    END AS company
FROM application_data a
JOIN all_applicants ap USING (application_number)
WHERE a.application_invention_type = 'Utility'
  AND EXTRACT(YEAR FROM a.filing_date) BETWEEN 2015 AND 2018
  AND ap.applicant_organization IS NOT NULL
) WHERE company IS NOT NULL;

.print ===== cohort size =====
SELECT COUNT(*) AS applications, COUNT(DISTINCT company) AS companies FROM cohort;

.print ===== rules-weight pass: restriction + office actions + allowance per application =====
CREATE OR REPLACE TEMP TABLE ev AS
SELECT c.application_number,
       MIN(CASE WHEN t.event_code = 'CTRS'  THEN t.recorded_date END) AS first_restriction,
       MIN(CASE WHEN t.event_code IN ('CTNF','CTFR') THEN t.recorded_date END) AS first_rejection,
       MIN(CASE WHEN t.event_code = 'MN/=.' THEN t.recorded_date END) AS first_allowance,
       SUM(CASE WHEN t.event_code IN ('CTNF','CTFR') THEN 1 ELSE 0 END) AS office_actions,
       SUM(CASE WHEN t.event_code = 'RCEX'  THEN 1 ELSE 0 END) AS rces,
       SUM(CASE WHEN t.event_code IN ('EXIN','EXAC','EXAT','EXET') THEN 1 ELSE 0 END) AS interviews
FROM cohort c
JOIN transactions t USING (application_number)
GROUP BY 1;

.print ===== headline signal per company =====
SELECT c.company,
       COUNT(*) AS apps,
       ROUND(100.0 * SUM(CASE WHEN e.first_restriction IS NOT NULL THEN 1 ELSE 0 END)/COUNT(*),1) AS pct_restricted,
       ROUND(100.0 * SUM(CASE WHEN e.first_allowance IS NOT NULL
                               AND e.first_rejection IS NULL
                               AND e.first_restriction IS NULL THEN 1 ELSE 0 END)/COUNT(*),1) AS pct_first_action_allowance,
       ROUND(AVG(e.office_actions),2) AS avg_office_actions
FROM cohort c JOIN ev e USING (application_number)
GROUP BY 1 ORDER BY apps DESC;

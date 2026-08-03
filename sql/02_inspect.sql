-- Diagnostics before writing any rules.
-- Run: duckdb data/patex.duckdb -f sql/02_inspect.sql

.print ===== transactions schema =====
DESCRIBE transactions;

.print ===== most common event codes overall (top 30) =====
SELECT t.event_code, COUNT(*) AS n, ANY_VALUE(e.event_desc) AS event_desc
FROM transactions t
LEFT JOIN event_codes e ON e.event_cd = t.event_code
GROUP BY 1 ORDER BY n DESC LIMIT 30;

.print ===== application status values (top 30) =====
SELECT appl_status_desc, COUNT(*) AS n
FROM application_data
GROUP BY 1 ORDER BY n DESC LIMIT 30;

.print ===== applicant_organization coverage by filing year =====
SELECT
    EXTRACT(YEAR FROM a.filing_date) AS filing_year,
    COUNT(*) AS applications,
    COUNT(ap.applicant_organization) AS with_applicant_org
FROM application_data a
LEFT JOIN all_applicants ap USING (application_number)
WHERE EXTRACT(YEAR FROM a.filing_date) BETWEEN 2010 AND 2018
GROUP BY 1 ORDER BY 1;

.print ===== application_invention_type values =====
SELECT application_invention_type, COUNT(*) AS n
FROM application_data GROUP BY 1 ORDER BY n DESC LIMIT 20;

.print ===== sample application_data rows, 2015 =====
SELECT application_number, application_invention_type, filing_date,
       appl_status_desc, patent_number, patent_issue_date
FROM application_data
WHERE EXTRACT(YEAR FROM filing_date) = 2015
LIMIT 8;

.print ===== sample all_applicants rows =====
SELECT * FROM all_applicants WHERE applicant_organization IS NOT NULL LIMIT 8;

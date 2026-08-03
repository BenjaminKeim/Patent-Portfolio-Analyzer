.print ===== is uspc_class usable for 2013-2019 utility filings? =====
SELECT EXTRACT(YEAR FROM filing_date) AS fy,
       COUNT(*) AS apps,
       COUNT(uspc_class) AS with_uspc,
       COUNT(examiner_art_unit) AS with_art_unit
FROM application_data
WHERE application_invention_type='Utility'
  AND EXTRACT(YEAR FROM filing_date) BETWEEN 2013 AND 2019
GROUP BY 1 ORDER BY 1;

.print ===== art unit -> technology center distribution =====
SELECT substr(examiner_art_unit,1,2) || '00' AS tech_center, COUNT(*) AS apps
FROM application_data
WHERE application_invention_type='Utility'
  AND EXTRACT(YEAR FROM filing_date) BETWEEN 2013 AND 2019
  AND examiner_art_unit IS NOT NULL
GROUP BY 1 ORDER BY apps DESC LIMIT 15;

.print ===== continuity direction sanity check: children of a known parent =====
SELECT cp.parent_application_number AS parent, cp.application_number AS child,
       cp.continuation_type, cc.child_filing_date
FROM continuity_parents cp
LEFT JOIN continuity_children cc
       ON cc.application_number = cp.parent_application_number
      AND cc.child_application_number = cp.application_number
WHERE cp.parent_application_number IN (
    SELECT application_number FROM application_data
    WHERE application_invention_type='Utility'
      AND EXTRACT(YEAR FROM filing_date)=2015
      AND patent_number IS NOT NULL
    LIMIT 3)
ORDER BY parent, child LIMIT 12;

.print ===== how many applications have multiple applicant rows? =====
SELECT n_applicants, COUNT(*) AS applications FROM (
  SELECT application_number, COUNT(*) AS n_applicants
  FROM all_applicants GROUP BY 1
) GROUP BY 1 ORDER BY 1 LIMIT 8;

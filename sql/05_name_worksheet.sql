-- Build the disambiguation worksheet: normalized applicant names per company stem.
-- Normalization collapses case + punctuation only. It deliberately does NOT strip
-- corporate suffixes, because that would merge genuinely distinct legal entities.
-- Output: data/name_worksheet.csv  (open in Excel, fill in the `keep` column)

COPY (
    WITH c AS (
        SELECT ap.applicant_organization AS org
        FROM application_data a
        JOIN all_applicants ap USING (application_number)
        WHERE a.application_invention_type = 'Utility'
          AND EXTRACT(YEAR FROM a.filing_date) = 2015
          AND ap.applicant_organization IS NOT NULL
    ),
    tagged AS (
        SELECT
            CASE
                WHEN org ILIKE '%SAMSUNG%'              THEN 'SAMSUNG'
                WHEN org ILIKE '%TAIWAN SEMICONDUCTOR%'
                  OR org ILIKE '%TSMC%'                 THEN 'TSMC'
                WHEN org ILIKE '%QUALCOMM%'             THEN 'QUALCOMM'
                WHEN org ILIKE '%HUAWEI%'               THEN 'HUAWEI'
                WHEN org ILIKE '%APPLE%'                THEN 'APPLE'
                WHEN org ILIKE '%CANON%'                THEN 'CANON'
                WHEN org ILIKE '%TOYOTA%'               THEN 'TOYOTA'
                WHEN org ILIKE '%DELL%'                 THEN 'DELL'
                WHEN org ILIKE 'LG %' OR org ILIKE '%LG ELECTRONICS%'
                  OR org ILIKE '%LG DISPLAY%' OR org ILIKE '%LG CHEM%'
                  OR org ILIKE '%LG INNOTEK%'           THEN 'LG'
            END AS stem,
            trim(regexp_replace(
                regexp_replace(upper(org), '[^A-Z0-9 ]', ' ', 'g'),
                ' +', ' ', 'g')) AS org_normalized
        FROM c
    )
    SELECT
        stem,
        org_normalized,
        COUNT(*) AS applications_2015,
        '' AS keep          -- <-- fill in: Y or N
    FROM tagged
    WHERE stem IS NOT NULL
    GROUP BY 1, 2
    ORDER BY stem, applications_2015 DESC
) TO 'data/name_worksheet.csv' (HEADER, DELIMITER ',');

.print ===== normalized worksheet (full) =====
WITH c AS (
    SELECT ap.applicant_organization AS org
    FROM application_data a
    JOIN all_applicants ap USING (application_number)
    WHERE a.application_invention_type = 'Utility'
      AND EXTRACT(YEAR FROM a.filing_date) = 2015
      AND ap.applicant_organization IS NOT NULL
),
tagged AS (
    SELECT
        CASE
            WHEN org ILIKE '%SAMSUNG%'              THEN 'SAMSUNG'
            WHEN org ILIKE '%TAIWAN SEMICONDUCTOR%'
              OR org ILIKE '%TSMC%'                 THEN 'TSMC'
            WHEN org ILIKE '%QUALCOMM%'             THEN 'QUALCOMM'
            WHEN org ILIKE '%HUAWEI%'               THEN 'HUAWEI'
            WHEN org ILIKE '%APPLE%'                THEN 'APPLE'
            WHEN org ILIKE '%CANON%'                THEN 'CANON'
            WHEN org ILIKE '%TOYOTA%'               THEN 'TOYOTA'
            WHEN org ILIKE '%DELL%'                 THEN 'DELL'
            WHEN org ILIKE 'LG %' OR org ILIKE '%LG ELECTRONICS%'
              OR org ILIKE '%LG DISPLAY%' OR org ILIKE '%LG CHEM%'
              OR org ILIKE '%LG INNOTEK%'           THEN 'LG'
        END AS stem,
        trim(regexp_replace(
            regexp_replace(upper(org), '[^A-Z0-9 ]', ' ', 'g'),
            ' +', ' ', 'g')) AS org_normalized
    FROM c
)
SELECT stem, org_normalized, COUNT(*) AS apps_2015
FROM tagged
WHERE stem IS NOT NULL
GROUP BY 1, 2
HAVING COUNT(*) >= 3
ORDER BY stem, apps_2015 DESC;

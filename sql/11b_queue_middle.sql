.mode line
SELECT nearest_display AS company, org_norm, apps, cc
FROM classification
WHERE bucket='B_review' AND apps>=10
  AND nearest_display NOT IN ('BOE Technology Group Co., Ltd.','Toyota Motor Corporation',
                               'Telefonaktiebolaget LM Ericsson (publ)')
ORDER BY nearest_display, apps DESC;

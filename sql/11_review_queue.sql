COPY (
  SELECT nearest_display AS nearest_company, org_norm, apps, cc, jw, tok_overlap,
         '' AS decision
  FROM classification WHERE bucket='B_review' AND apps>=10
  ORDER BY nearest_display, apps DESC
) TO 'data/review_queue.csv' (HEADER, DELIMITER ',');

.print ===== full batch-2 queue (99 names), grouped by nearest company =====
SELECT row_number() OVER (ORDER BY nearest_display, apps DESC) AS n,
       nearest_display AS company, org_norm, apps, cc
FROM classification WHERE bucket='B_review' AND apps>=10
ORDER BY nearest_display, apps DESC;

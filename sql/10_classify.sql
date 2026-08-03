-- Applicant-name disambiguation classifier.  Deterministic rules only; no ML.
-- Human decisions in config/decisions.csv ALWAYS override the rules.
-- Run: duckdb data/patex.duckdb -f sql/10_classify.sql
--
-- Buckets
--   DECIDED  - a human decision exists (exact match), or a trivial variant of one (Stage B)
--   A_auto   - trivial variant of a canonical seed, or a shell/holding-entity pattern (R6)
--   B_review - shares the brand token, real word difference. Needs Ben's judgment.
--   C_reject - not this company.
--
-- Brand tokens: pipe-separated in config/canonical_seeds.csv.
--   A leading '~' marks a WEAK token - a generic industry word that alone is not
--   evidence of identity (SEMICONDUCTOR, MACHINES, TAIWAN). Weak hits must also clear
--   the token-overlap floor to reach review. Strong hits always reach review.
--
-- Stage A rules (candidate vs. the 20 canonical seeds)
--   R1  core tokens identical after corporate-suffix stripping        -> A_auto
--   R2  bare brand name (core == brand token) merges into the brand's -> A_auto
--       primary company            [derived from Ben's Microsoft ruling, 2026-08-02]
--   R3  same core token count and Jaro-Winkler >= 0.90                -> A_auto
--   R6  strong brand token + all remaining core tokens are shell/     -> A_auto
--       holding words (IP, TECHNOLOGY, HOLDINGS, LICENSING, ...)
--       [derived from Ben's "merge for renamed" ruling, Batch 1 Group 1]
--   R4a strong brand token present (and none of R1/R2/R3/R6 fired)    -> B_review
--   R4b weak brand token present and token-overlap >= 0.50            -> B_review
--   R5  everything else                                               -> C_reject
--
-- Stage B (candidates NOT resolved by Stage A, checked against every DECIDED name)
--   R1b/R3b  trivial variant (core identical, or same core length +   -> DECIDED
--            Jaro-Winkler >= 0.90) of an already-decided org_norm.
--            Applied at ANY application count, per Ben's instruction
--            to sweep trivial variations even below the review floor.

SET VARIABLE suffixes = ['CO','LTD','INC','CORP','CORPORATION','COMPANY','LIMITED',
    'INCORPORATED','LLC','LLP','LP','L','P','C','KK','KABUSHIKI','KAISHA','GMBH',
    'AB','NV','SA','PLC','PUBL','AG','BV','OY','AS','KGAA','SARL','SAS','SPA','SRL'];

SET VARIABLE shell_toks = ['IP','TECHNOLOGY','TECHNOLOGIES','HOLDINGS','LICENSING','LICENCING'];

CREATE OR REPLACE TEMP MACRO norm(s) AS
    trim(regexp_replace(regexp_replace(upper(s), '[^A-Z0-9 ]', ' ', 'g'), ' +', ' ', 'g'));

-- A token counts as a corporate suffix if it matches the list exactly, OR is a close
-- typo of one (JW >= 0.85, length >= 6 to avoid short-token false matches). Catches
-- COPORATION / INCORPORTED / INCOPORATED - real names USPTO itself misspelled -
-- without this they fail suffix-stripping, get treated as a "real" extra word, and
-- wrongly land in the review queue instead of auto-merging.
CREATE OR REPLACE TEMP MACRO is_suffix_word(tok) AS (
    list_contains(getvariable('suffixes'), tok)
    OR (length(tok) >= 6 AND
        list_max(list_transform(getvariable('suffixes'),
                  lambda s: jaro_winkler_similarity(tok, s))) >= 0.85)
);

CREATE OR REPLACE TEMP MACRO core_tokens(s) AS
    list_filter(string_split(s, ' '), lambda x: NOT is_suffix_word(x) AND x <> '');

-- ---------------------------------------------------------------- seeds
CREATE OR REPLACE TEMP TABLE seeds AS
SELECT company_id, display_name, ifi_rank, canonical_norm, country_code, is_brand_primary,
       list_filter(string_split(brand_tokens,'|'), lambda t: NOT starts_with(t,'~'))
           AS strong_toks,
       list_transform(
           list_filter(string_split(brand_tokens,'|'), lambda t: starts_with(t,'~')),
           lambda t: replace(t,'~',''))                        AS weak_toks,
       core_tokens(canonical_norm)                             AS seed_core_toks,
       array_to_string(core_tokens(canonical_norm), ' ')       AS seed_core
FROM read_csv('config/canonical_seeds.csv', header = true);

CREATE OR REPLACE TEMP TABLE decisions AS
SELECT norm(org_norm) AS org_norm, company_id, decided_by, note
FROM read_csv('config/decisions.csv', header = true);

CREATE OR REPLACE TEMP TABLE decided_anchors AS
SELECT company_id, org_norm AS anchor_norm,
       core_tokens(org_norm)                       AS anchor_core_toks,
       array_to_string(core_tokens(org_norm), ' ') AS anchor_core
FROM decisions;

-- ---------------------------------------------------------------- candidate pool
-- Token-boundary matching (not substring): kills TRUDELL/LYONDELL under DELL,
-- PINEAPPLE under APPLE, INTELLECTUAL VENTURES under INTEL, NATIONAL TAIWAN
-- UNIVERSITY under TSMC.
CREATE OR REPLACE TEMP TABLE all_brand_toks AS
SELECT DISTINCT unnest(list_concat(strong_toks, weak_toks)) AS tok FROM seeds;

CREATE OR REPLACE TEMP TABLE candidates AS
SELECT org_norm,
       COUNT(*)                                    AS apps,
       mode(cc)                                    AS cc,
       core_tokens(org_norm)                       AS cand_core_toks,
       array_to_string(core_tokens(org_norm), ' ') AS cand_core
FROM (
    SELECT norm(ap.applicant_organization) AS org_norm,
           ap.applicant_country_code       AS cc
    FROM application_data a
    JOIN all_applicants ap USING (application_number)
    WHERE a.application_invention_type = 'Utility'
      AND EXTRACT(YEAR FROM a.filing_date) BETWEEN 2013 AND 2019
      AND ap.applicant_organization IS NOT NULL
)
WHERE len(list_intersect(string_split(org_norm,' '),
                         (SELECT list(tok) FROM all_brand_toks))) > 0
GROUP BY org_norm, cand_core_toks, cand_core;

-- ---------------------------------------------------------------- Stage A: score vs. seeds
CREATE OR REPLACE TEMP TABLE scored AS
SELECT c.org_norm, c.apps, c.cc, c.cand_core, c.cand_core_toks,
       s.company_id, s.display_name, s.canonical_norm, s.seed_core, s.seed_core_toks,
       s.is_brand_primary, s.strong_toks, s.weak_toks,
       len(list_intersect(string_split(c.org_norm,' '), s.strong_toks)) > 0 AS strong_hit,
       len(list_intersect(string_split(c.org_norm,' '), s.weak_toks))   > 0 AS weak_hit,
       jaro_winkler_similarity(c.cand_core, s.seed_core)                    AS jw,
       len(list_intersect(c.cand_core_toks, s.seed_core_toks))::DOUBLE
           / greatest(len(s.seed_core_toks), 1)                             AS tok_overlap,
       len(c.cand_core_toks) = len(s.seed_core_toks)                        AS same_core_len,
       list_filter(c.cand_core_toks, lambda x: NOT list_contains(s.strong_toks, x))
           AS remaining_after_brand
FROM candidates c CROSS JOIN seeds s;

CREATE OR REPLACE TEMP TABLE best AS
SELECT * FROM (
    SELECT *, row_number() OVER (
        PARTITION BY org_norm
        ORDER BY (strong_hit OR weak_hit) DESC,
                 round(tok_overlap * 0.6 + jw * 0.4, 2) DESC,
                 is_brand_primary DESC,          -- prefer the brand's primary company on ties
                 apps DESC
    ) AS rn
    FROM scored
) WHERE rn = 1;

CREATE OR REPLACE TEMP TABLE stage_a AS
WITH r AS (
    SELECT b.*,
        (b.strong_hit OR b.weak_hit)                       AS brand_hit,
        (b.cand_core = b.seed_core)                        AS r1,
        (b.is_brand_primary = 1 AND len(b.cand_core_toks) = 1
         AND len(list_intersect(b.cand_core_toks,
                 list_concat(b.strong_toks, b.weak_toks))) = 1) AS r2,
        (b.same_core_len AND b.jw >= 0.90)                 AS r3,
        (b.strong_hit
         AND len(b.remaining_after_brand) > 0
         AND len(b.remaining_after_brand) < len(b.cand_core_toks)
         AND len(list_filter(b.remaining_after_brand,
                 lambda y: NOT list_contains(getvariable('shell_toks'), y))) = 0
        )                                                   AS r6,
        (b.tok_overlap >= 0.50)                             AS floor_ok
    FROM best b
)
SELECT
    r.org_norm, r.apps, r.cc,
    CASE WHEN r.brand_hit AND (r.r1 OR r.r2 OR r.r3 OR r.r6) THEN r.company_id END AS company_id,
    CASE
        WHEN NOT r.brand_hit                       THEN 'C_reject'
        WHEN r.r1 OR r.r2 OR r.r3 OR r.r6          THEN 'A_auto'
        WHEN r.strong_hit                          THEN 'B_review'
        WHEN r.weak_hit AND r.floor_ok             THEN 'B_review'
        ELSE 'C_reject'
    END AS bucket,
    CASE
        WHEN NOT r.brand_hit           THEN 'no brand token'
        WHEN r.r1                      THEN 'R1 core identical'
        WHEN r.r2                      THEN 'R2 bare brand'
        WHEN r.r3                      THEN 'R3 typo variant'
        WHEN r.r6                      THEN 'R6 shell/holding entity'
        WHEN r.strong_hit              THEN 'R4a strong brand token'
        WHEN r.weak_hit AND r.floor_ok THEN 'R4b weak token + floor'
        ELSE 'R5 below floor'
    END AS rule_fired,
    r.company_id AS nearest_company, r.display_name AS nearest_display,
    r.canonical_norm, round(r.jw,3) AS jw, round(r.tok_overlap,2) AS tok_overlap,
    r.cand_core, r.cand_core_toks
FROM r;

-- ---------------------------------------------------------------- Stage B: decided-entity variants
-- Only runs on rows Stage A left in B_review/C_reject. Applied at any apps count.
-- b_r3 compares the SINGLE differing token, not the whole string. Whole-string JW on
-- short "BRAND + one word" names is fooled by a long shared prefix even when the second
-- word is completely unrelated (e.g. "HYUNDAI STEEL COMPANY" vs "HYUNDAI AUTOEVER CORP"
-- scored >=0.90 on whole-string JW despite STEEL and AUTOEVER having nothing in common -
-- they are different real Hyundai affiliates, not a typo of one another). Requiring
-- exactly one token to differ on each side, then checking THAT token's similarity,
-- catches true typos (MECHANICS/MACHANICS) while rejecting different-word collisions.
CREATE OR REPLACE TEMP TABLE stage_b_scored AS
SELECT s.org_norm, s.cand_core, s.cand_core_toks,
       da.company_id AS anchor_company_id, da.anchor_norm, da.anchor_core_toks,
       (s.cand_core = da.anchor_core) AS b_r1,
       list_filter(s.cand_core_toks, lambda x: NOT list_contains(da.anchor_core_toks, x))
           AS diff_cand,
       list_filter(da.anchor_core_toks, lambda x: NOT list_contains(s.cand_core_toks, x))
           AS diff_anchor,
       jaro_winkler_similarity(s.cand_core, da.anchor_core) AS jw
FROM stage_a s
CROSS JOIN decided_anchors da
WHERE s.bucket IN ('B_review','C_reject');

CREATE OR REPLACE TEMP TABLE stage_b_scored2 AS
SELECT *,
    (len(diff_cand) = 1 AND len(diff_anchor) = 1
     AND jaro_winkler_similarity(diff_cand[1], diff_anchor[1]) >= 0.80) AS b_r3
FROM stage_b_scored;

CREATE OR REPLACE TEMP TABLE stage_b_best AS
SELECT * FROM (
    SELECT *, row_number() OVER (
        PARTITION BY org_norm ORDER BY (b_r1 OR b_r3) DESC, jw DESC
    ) AS rn
    FROM stage_b_scored2
    WHERE b_r1 OR b_r3
) WHERE rn = 1;

-- ---------------------------------------------------------------- final: exact decisions win, then Stage B, then Stage A
-- A decision's company_id may be the literal sentinel 'EXCLUDE' (human veto: shares the
-- brand token but is not this company - JVs, unrelated businesses, false positives).
-- Excluded names resolve to no company (terminal, not counted, not re-queued), and their
-- own typo variants are excluded too via the same Stage B anchor mechanism.
CREATE OR REPLACE TABLE classification AS
SELECT
    sa.org_norm, sa.apps, sa.cc,
    CASE
        WHEN d.company_id = 'EXCLUDE'          THEN NULL
        WHEN sb.anchor_company_id = 'EXCLUDE'  THEN NULL
        ELSE COALESCE(d.company_id, sb.anchor_company_id, sa.company_id)
    END AS company_id,
    CASE
        WHEN d.company_id = 'EXCLUDE'          THEN 'EXCLUDED'
        WHEN sb.anchor_company_id = 'EXCLUDE'  THEN 'EXCLUDED'
        WHEN d.company_id IS NOT NULL          THEN 'DECIDED'
        WHEN sb.anchor_company_id IS NOT NULL  THEN 'DECIDED'
        ELSE sa.bucket
    END AS bucket,
    CASE
        WHEN d.company_id = 'EXCLUDE'          THEN 'human exclude: ' || COALESCE(d.note,'')
        WHEN sb.anchor_company_id = 'EXCLUDE'  THEN 'R1b/R3b variant of excluded: ' || sb.anchor_norm
        WHEN d.company_id IS NOT NULL          THEN 'human (exact)'
        WHEN sb.anchor_company_id IS NOT NULL
             THEN 'R1b/R3b variant of decided: ' || sb.anchor_norm
        ELSE sa.rule_fired
    END AS rule_fired,
    sa.nearest_company, sa.nearest_display, sa.canonical_norm, sa.jw, sa.tok_overlap
FROM stage_a sa
LEFT JOIN decisions d   ON d.org_norm = sa.org_norm
LEFT JOIN stage_b_best sb ON sb.org_norm = sa.org_norm;

.print ===== bucket summary =====
SELECT bucket, COUNT(*) AS names, SUM(apps) AS applications
FROM classification GROUP BY 1 ORDER BY applications DESC;

.print ===== explicitly excluded names (human veto) =====
SELECT org_norm, apps, rule_fired
FROM classification WHERE bucket='EXCLUDED' ORDER BY apps DESC;

.print ===== Stage B: names swept up as variants of a decided entity =====
SELECT rule_fired, org_norm, apps
FROM classification WHERE rule_fired LIKE 'R1b/R3b%' ORDER BY apps DESC;

.print ===== review queue (B_review, >=10 apps) by company =====
SELECT nearest_display AS company, COUNT(*) AS names, SUM(apps) AS apps
FROM classification WHERE bucket='B_review' AND apps>=10
GROUP BY 1 ORDER BY apps DESC;

.print ===== review queue total =====
SELECT COUNT(*) AS queue_size, SUM(apps) AS apps_at_stake
FROM classification WHERE bucket='B_review' AND apps>=10;

.print ===== resulting company totals (DECIDED + A_auto) =====
SELECT s.ifi_rank, c.company_id, s.display_name,
       COUNT(*) AS names_merged, SUM(c.apps) AS applications
FROM classification c JOIN seeds s USING (company_id)
WHERE c.company_id IS NOT NULL
GROUP BY 1,2,3 ORDER BY s.ifi_rank;

-- Load PatEx 2022-release CSVs into a native DuckDB database.
-- Run once:  duckdb data/patex.duckdb -f sql/01_load.sql
-- Native tables are far faster to query than the raw CSVs and take much less disk.

SET preserve_insertion_order = false;

-- NOTE: DuckDB does not auto-detect the quote character on these files
-- (values like "PCT/FR99/02,868" contain commas inside quotes), so quote is set explicitly.

CREATE OR REPLACE TABLE application_data AS
SELECT * FROM read_csv(
    'data/raw/application_data.csv',
    quote = '"', header = true, all_varchar = false
);

CREATE OR REPLACE TABLE all_applicants AS
SELECT * FROM read_csv(
    'data/raw/all_applicants.csv',
    quote = '"', header = true, all_varchar = false
);

CREATE OR REPLACE TABLE continuity_parents AS
SELECT * FROM read_csv(
    'data/raw/continuity_parents.csv',
    quote = '"', header = true, all_varchar = false
);

CREATE OR REPLACE TABLE continuity_children AS
SELECT * FROM read_csv(
    'data/raw/continuity_children.csv',
    quote = '"', header = true, all_varchar = false
);

CREATE OR REPLACE TABLE foreign_priority AS
SELECT * FROM read_csv(
    'data/raw/foreign_priority.csv',
    quote = '"', header = true, all_varchar = false
);

CREATE OR REPLACE TABLE event_codes AS
SELECT * FROM read_csv(
    'data/raw/event_codes.csv',
    quote = '"', header = true, all_varchar = false
);

-- Largest file (12.2 GB CSV); this step takes the longest.
CREATE OR REPLACE TABLE transactions AS
SELECT * FROM read_csv(
    'data/raw/transactions.csv',
    quote = '"', header = true, all_varchar = false
);

-- Row counts, so we can confirm nothing was silently dropped.
SELECT 'application_data'    AS tbl, COUNT(*) AS rows FROM application_data
UNION ALL SELECT 'all_applicants',      COUNT(*) FROM all_applicants
UNION ALL SELECT 'continuity_parents',  COUNT(*) FROM continuity_parents
UNION ALL SELECT 'continuity_children', COUNT(*) FROM continuity_children
UNION ALL SELECT 'foreign_priority',    COUNT(*) FROM foreign_priority
UNION ALL SELECT 'event_codes',         COUNT(*) FROM event_codes
UNION ALL SELECT 'transactions',        COUNT(*) FROM transactions
ORDER BY rows DESC;

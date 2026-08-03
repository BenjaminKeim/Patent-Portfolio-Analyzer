/* Types and display constants shared by server and client components.
   Deliberately free of any Node imports: lib/data.ts reads the JSON with node:fs at
   build time, and a client component importing from there would drag fs into the
   browser bundle. Anything both sides need lives here instead. */

export type FlagStat = {
  flagged: number;
  present: number | null;
  indeterminate: number;
  rate: number | null;
};

export type CompanySummary = {
  id: string;
  name: string;
  ifi_rank: number;
  applications: number;
  granted: number;
  abandoned: number;
  pending: number;
  allowance_rate: number;
  median_months_to_issue: number;
  mean_office_actions: number;
  restriction_rate: number;
  faa_rate: number;
  national_stage_rate: number;
  mean_rces: number;
  interview_rate: number;
  flags: { a1: FlagStat; b1: FlagStat; b2: FlagStat };
};

export type YearRow = {
  year: number;
  filed: number;
  granted: number;
  abandoned: number;
  pending: number;
  allowance_rate: number | null;
  median_months_to_issue: number | null;
  mean_office_actions: number;
  restriction_rate: number;
  coverage_pct: number;
};

export type TechRow = { tech_center: string; applications: number; pct: number };

export type FlaggedRow = {
  application: string;
  rule: "A1" | "B1" | "B2";
  filed: string;
  patent: string | null;
  issued: string | null;
  tech_center: string;
  office_actions: number;
};

export type Meta = {
  source: string;
  cohort: string;
  observable_until: string;
  notes: string[];
};

/** Corpus-level counts. Deliberately separate from the per-company figures: summing
 *  company application counts double-counts jointly filed applications, so headline
 *  totals must come from here rather than from a reduce() over the company list. */
export type Stats = {
  distinct_applications: number;
  company_memberships: number;
  jointly_held: number;
  distinct_flag_rows: number;
  distinct_flagged_applications: number;
};

/** Company detail WITHOUT the flagged list. The flagged rows live in a separate file
 *  (public/data/flagged/<id>.json) fetched by the client, because Next inlines any data
 *  a server component touches into the HTML and three RSC payload copies. */
export type CompanyDetail = {
  id: string;
  name: string;
  ifi_rank: number;
  by_year: YearRow[];
  tech: TechRow[];
  flagged_count: number;
  meta: Meta;
};

/** Short labels for chart axes. Derived by hand rather than by stripping corporate
 *  suffixes with a regex, which mangled "International Business Machines" and cut
 *  "Telefonaktiebolaget LM Ericsson" mid-word. */
export const SHORT_NAMES: Record<string, string> = {
  "samsung-electronics": "Samsung Electronics",
  tsmc: "TSMC",
  qualcomm: "Qualcomm",
  huawei: "Huawei",
  "samsung-display": "Samsung Display",
  apple: "Apple",
  canon: "Canon",
  toyota: "Toyota",
  dell: "Dell",
  "lg-electronics": "LG Electronics",
  ibm: "IBM",
  intel: "Intel",
  boe: "BOE",
  google: "Google",
  microsoft: "Microsoft",
  hyundai: "Hyundai",
  kia: "Kia",
  ericsson: "Ericsson",
  micron: "Micron",
  amazon: "Amazon",
};

/** USPTO technology centres. Art unit prefix -> the technology it examines. */
export const TECH_CENTER_LABELS: Record<string, string> = {
  "1600": "Biotechnology & Organic Chemistry",
  "1700": "Chemical & Materials Engineering",
  "2100": "Computer Architecture & Software",
  "2400": "Computer Networks & Security",
  "2600": "Communications",
  "2800": "Semiconductors, Electrical & Optical",
  "3600": "Transportation, Construction & E-Commerce",
  "3700": "Mechanical Engineering & Manufacturing",
  other: "Other / unclassified",
};

export const RULE_LABELS: Record<string, { short: string; full: string; why: string }> = {
  A1: {
    short: "First-action allowance, no continuation",
    full:
      "Allowed on the first action with no continuing application filed before issuance.",
    why:
      "A first-action allowance means the examiner found nothing worth citing against the claims as presented — the strongest signal in the public record that scope was left unclaimed. A continuation filed before issue would have preserved the option for a filing fee.",
  },
  B1: {
    short: "Restriction, no divisional",
    full:
      "A restriction requirement issued and no divisional was ever filed for the non-elected subject matter.",
    why:
      "Claims to the non-elected invention were withdrawn and never pursued. Whether that was deliberate is not visible in the public record.",
  },
  B2: {
    short: "Child filed as continuation, not divisional",
    full:
      "A restriction issued and a child was filed, but designated a continuation rather than a divisional.",
    why:
      "§ 121's safe harbour against double-patenting rejections attaches to a divisional filed as a result of the restriction. Courts look to substance and consonance rather than the ADS label, so this is a risk flag warranting review — not a conclusion.",
  },
};

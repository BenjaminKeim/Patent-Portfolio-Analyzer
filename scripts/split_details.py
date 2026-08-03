"""Split the exported _details.json into per-company files.

Two files per company, deliberately:

  data/company/<id>.json  - summary, year series, technology mix. Small, and read at
                            build time by a server component, so it gets inlined into
                            the prerendered HTML.
  data/flagged/<id>.json  - the flagged-application list, up to ~12,700 rows. Fetched
                            by the client at runtime instead.

Keeping the flagged rows out of the server component matters: Next inlines server data
into the HTML *and* three separate RSC payload files, so a single 1.7 MB list became
~7 MB of build output per company. Splitting it cut the static export from 66 MB to a
few MB of HTML plus JSON that is only downloaded when someone opens a company page.

Run after sql/21_export_json.sql:
    python scripts/split_details.py
"""
import json
import pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent / "site" / "public" / "data"
src = DATA / "_details.json"
company_dir = DATA / "company"
flagged_dir = DATA / "flagged"
company_dir.mkdir(parents=True, exist_ok=True)
flagged_dir.mkdir(parents=True, exist_ok=True)

details = json.loads(src.read_text(encoding="utf-8"))

meta = {
    "source": "USPTO Patent Examination Research Dataset (PatEx), 2022 release "
              "(PEDS pull June 2023)",
    "cohort": "US utility applications, filing years 2013-2019",
    "observable_until": "2022-06-30",
    "notes": [
        "Applicant-organization recording only ramped up after the AIA (Sept 2012). "
        "Coverage is 65% in 2013 and 81% in 2014, reaching ~90% from 2015. Filing "
        "counts for 2013-2014 are understated; per-year coverage is included in the "
        "data so charts can mark those years as incomplete.",
        "An application filed jointly by two tracked companies counts for both. "
        "Company totals therefore sum to more than the number of distinct applications "
        "(399,905 memberships across 393,587 applications; Hyundai and Kia alone "
        "co-file 5,879).",
        "Flags identify unexercised options, not errors. The public record does not "
        "show client instructions, budgets, or strategy, so no flag can distinguish a "
        "mistake from a deliberate decision.",
        "Absence-based rules use three states. FLAG means a filing would have been "
        "visible and was not made; INDETERMINATE means the case was disposed too close "
        "to the data cutoff to tell.",
    ],
}

total_flagged = 0
for company in details:
    for key in ("by_year", "tech", "flagged"):
        if company.get(key) is None:
            company[key] = []

    flagged = company.pop("flagged")
    total_flagged += len(flagged)

    (flagged_dir / f"{company['id']}.json").write_text(
        json.dumps(flagged, separators=(",", ":")), encoding="utf-8"
    )

    company["meta"] = meta
    company["flagged_count"] = len(flagged)
    (company_dir / f"{company['id']}.json").write_text(
        json.dumps(company, separators=(",", ":")), encoding="utf-8"
    )

    small_kb = (company_dir / f"{company['id']}.json").stat().st_size / 1024
    big_kb = (flagged_dir / f"{company['id']}.json").stat().st_size / 1024
    print(f"{company['id']:<22} summary {small_kb:>7.1f} KB   flagged {big_kb:>8.1f} KB "
          f"({len(flagged):,} rows)")

(DATA / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
src.unlink()
print(f"\n{len(details)} companies, {total_flagged:,} flagged rows total")

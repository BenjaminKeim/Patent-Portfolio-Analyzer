"""Regression tests for entity resolution.

Every case here is a trap that has actually bitten this project, recorded in
CONTEXT.md or found while building this module. Run:

    python test_entity.py

The classification tests need no corpus. The resolution tests need one and skip
without it.
"""
from __future__ import annotations

import sys

import entity

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        FAILURES.append(f"{label}\n      got  {got!r}\n      want {want!r}")


def state(target: str, candidate: str) -> str:
    return entity.classify(entity.core_tokens(target), entity.core_tokens(candidate))[0]


def reason(target: str, candidate: str) -> str:
    return entity.classify(entity.core_tokens(target), entity.core_tokens(candidate))[1]


# ------------------------------------------------------------------ the substring bug
# The defect this module exists to fix. A substring test kept every one of these;
# token-boundary matching means they never even enter the candidate pool.
SUBSTRING_TRAPS = [
    ("Intel Corporation", "Intellectual Ventures LLC"),
    ("Intel Corporation", "Intelligent Energy Limited"),
    ("Apple Inc.", "Pineapple Energy Inc."),
    ("Dell Products L.P.", "Trudell Medical International"),
    ("Dell Products L.P.", "LyondellBasell Industries"),
    ("Micron Technology, Inc.", "Micronics Japan Co Ltd"),
]

# --------------------------------------------------------------- same filer, must be IN
SAME_FILER = [
    ("Microsoft Corporation", "Microsoft Corporation", "exact"),
    ("Microsoft Corporation", "MICROSOFT TECHNOLOGY LICENSING LLC", "licensing vehicle"),
    ("Microsoft Corporation", "MICROSOFT TECHNOLGOY LICENSING LLC", "typo in shell word"),
    ("Microsoft Corporation", "MICROSOFT TECHNOLOGY LICESNING LLC", "typo in shell word"),
    ("Microsoft Corporation", "C O MICROSOFT TECHNOLOGY LICENSING LLC", "care-of prefix"),
    ("Microsoft Corporation", "MICROSOFT TECHNOLOGY LICENSING LC", "mangled LLC suffix"),
    ("Microsoft Corporation", "MICROSOFT COPORATION", "USPTO misspelling of suffix"),
    ("Microsoft Corporation", "MICROSOFT", "bare brand"),
    ("Intel Corporation", "INTEL IP CORPORATION", "IP vehicle"),
    ("Hyundai Motor Company", "HYUNDAI MOTORS COMPANY", "plural of a name word"),
    # Over IDENTITY_EXACT_MAX_LEN, so a long descriptive word keeps its typo budget.
    ("Taiwan Semiconductor Manufacturing Co., Ltd.",
     "TAIWAN SEMICONDUCTOR MANFACTURING CO LTD", "typo in a >10-char name word"),
    ("Taiwan Semiconductor Manufacturing Co., Ltd.",
     "TAIWAN SEMICONDUCTOR MANUGACTURING COMPANY LTD", "typo in a >10-char name word"),
]

# The company name itself is matched EXACTLY at or below IDENTITY_EXACT_MAX_LEN
# characters (Ben's ruling, 2026-08-21). These are all real filings by the named
# company that are nonetheless out of scope, and must surface as near misses instead
# of being silently dropped.
BRAND_TYPO_OUT_OF_SCOPE = [
    ("Samsung Electronics Co., Ltd.", "SAMSUNG ELECTONICS CO LTD"),
    ("Hyundai Motor Company", "HYNDAI MOTOR COMPANY"),
    ("Qualcomm Incorporated", "QUALCOM INCORPORATED"),
    ("Microsoft Corporation", "MICROSFT TECHNOLOGY LICENSING LLC"),
    ("NVIDIA Corporation", "NIVIDIA CORPORATION"),
]

# ------------------------------------------------- different filer, must NOT be in scope
DIFFERENT_FILER = [
    # CONTEXT.md: scored Jaro-Winkler 0.941 whole-string against Samsung Electronics
    # and is a different company. The reason the threshold cannot drop below 0.90.
    ("Samsung Electronics Co., Ltd.", "SAMSUNG ELECTRO MECHANICS CO LTD"),
    ("Samsung Electronics Co., Ltd.", "SAMSUNG DISPLAY CO LTD"),
    ("Samsung Electronics Co., Ltd.", "SAMSUNG SDI CO LTD"),
    ("Samsung Electronics Co., Ltd.", "SAMSUNG HEAVY IND CO LTD"),
    ("Samsung Electronics Co., Ltd.", "SAMSIN USA LLC"),
    # CONTEXT.md: cleared 0.90 whole-string on the shared prefix. Comparing only the
    # differing token is what fixed it.
    ("Hyundai Motor Company", "HYUNDAI AUTOEVER CORP"),
    ("Hyundai Motor Company", "HYUNDAI STEEL COMPANY"),
    ("Hyundai Motor Company", "HYUNDAI MOBIS CO LTD"),
    ("Hyundai Motor Company", "HONDA MOTOR CO LTD"),
    ("Microsoft Corporation", "MICROSOFT MOBILE OY"),
    ("Microsoft Corporation", "ONE MICROSOFT WAY"),
    ("Dell Products L.P.", "DELL SOFTWARE INC"),
    ("Dell Products L.P.", "UNIVERSITA DEGLI STUDI DELL AQUILA"),
    ("International Business Machines Corporation",
     "INTERNATIONAL ELECTRONIC MACHINES CORPORATION"),
    # Real companies that Jaro-Winkler scored >= 0.90 against the 5-character token
    # INTEL on the shared prefix alone. 169 of these were swept into Intel's scope
    # before the typo test became bounded edit distance.
    ("Intel Corporation", "INTEPLAST GROUP CORPORATION"),
    ("Intel Corporation", "INTELSAT CORPORATION"),
    ("Intel Corporation", "INTELGENX CORP"),
    ("Intel Corporation", "INTELLON CORPORATION"),
    ("Intel Corporation", "INTELESOL LLC"),
    ("Intel Corporation", "INTEC INC"),
    ("Intel Corporation", "INTERBLOCK D D"),
    ("Samsung Electronics Co., Ltd.", "SAMSON ROPE TECHNOLOGIES"),
    # One edit from NVIDIA and a different company. NIVIDIA and NAVIDIA are also one
    # edit away and ARE NVIDIA - the first letter is what separates them.
    ("NVIDIA Corporation", "AVIDIA INC"),
]

# ------------------------------------------- genuinely ambiguous, must be flagged UNCERTAIN
UNCERTAIN = [
    ("Samsung Electronics Co., Ltd.", "SAMSUNG RESEARCH AMERICA INC"),
    ("Samsung Electronics Co., Ltd.", "SAMSUNG ELECTRONICS UK LIMITED"),
    ("Microsoft Corporation", "MICROSOFT ISRAEL RESEARCH AND DEVELOPMENT 2002 L"),
]


def run_classification() -> None:
    for target, cand in SUBSTRING_TRAPS:
        # Two guarantees: the classifier rejects it, AND it shares no token with the
        # target, so token-boundary enumeration never surfaces it in the first place.
        check(f"substring trap: {target} vs {cand}", state(target, cand), "EXCLUDED")
        shared = set(entity.core_tokens(target)) & set(entity.core_tokens(cand))
        identity_shared = {t for t in shared if not entity.is_noise(t)}
        check(f"no shared identity token: {target} vs {cand}", identity_shared, set())

    for target, cand, why in SAME_FILER:
        check(f"same filer ({why}): {target} vs {cand}", state(target, cand), "IN")

    for target, cand in BRAND_TYPO_OUT_OF_SCOPE:
        check(f"company name matched exactly: {target} vs {cand}",
              state(target, cand), "EXCLUDED")

    for target, cand in DIFFERENT_FILER:
        got = state(target, cand)
        detail = reason(target, cand)
        check(f"different filer: {target} vs {cand} [{detail}]", got, "EXCLUDED")
        if got == "EXCLUDED":
            check(
                f"different filer must not read as a regional arm: {cand}",
                detail.startswith("regional"),
                False,
            )

    for target, cand in UNCERTAIN:
        got, detail = entity.classify(entity.core_tokens(target), entity.core_tokens(cand))
        check(f"uncertain: {target} vs {cand}", (got, detail.startswith("regional")),
              ("EXCLUDED", True))


def run_helpers() -> None:
    check("suffix typo COPORATION", entity.is_suffix_word("COPORATION"), True)
    check("suffix artifact LC", entity.is_suffix_word("LC"), True)
    check("suffix artifact LLC", entity.is_suffix_word("LLC"), True)
    check("MOBILE is not a suffix", entity.is_suffix_word("MOBILE"), False)
    check("shell typo TECHNOLGOY", entity.is_shell_word("TECHNOLGOY"), True)
    check("shell typo LICESNING", entity.is_shell_word("LICESNING"), True)
    check("DISPLAY is not a shell word", entity.is_shell_word("DISPLAY"), False)
    check("noise: bare year", entity.is_noise("2002"), True)
    check("noise: single letter", entity.is_noise("V"), True)
    check("MOBIS is not noise", entity.is_noise("MOBIS"), False)
    # JW(SAMSIN, SAS) = 0.867 clears the 0.85 typo threshold on a shared prefix alone.
    # Without a length guard the brand token is eaten and Samsin joins Samsung.
    check("SAMSIN is not a corporate suffix", entity.is_suffix_word("SAMSIN"), False)
    check("SAMSUNG is not a corporate suffix", entity.is_suffix_word("SAMSUNG"), False)
    check("CANON is not a corporate suffix", entity.is_suffix_word("CANON"), False)
    # same_word: the short-token rule. Under six characters, exact match only -
    # there is no room for a typo that is not also a different word.
    check("INTEL / INTEC are different words", entity.same_word("INTEL", "INTEC"), False)
    check("INTEL / INTELSAT are different words",
          entity.same_word("INTEL", "INTELSAT"), False)
    check("SAMSUNG / SAMSIN are different words",
          entity.same_word("SAMSUNG", "SAMSIN"), False)
    check("SAMSUNG / SAMSON are different words",
          entity.same_word("SAMSUNG", "SAMSON"), False)
    # Identity tokens: EXACT at or below IDENTITY_EXACT_MAX_LEN, no typo budget.
    check("HYUNDAI / HYNDAI is not an exact match",
          entity.same_word("HYUNDAI", "HYNDAI"), False)
    check("NVIDIA / NIVIDIA is not an exact match",
          entity.same_word("NVIDIA", "NIVIDIA"), False)
    check("NVIDIA / AVIDIA is not an exact match",
          entity.same_word("NVIDIA", "AVIDIA"), False)
    check("ELECTRONICS / ELECTONICS is not an exact match (10 chars)",
          entity.same_word("ELECTRONICS", "ELECTONICS"), False)
    check("QUALCOMM / QUALCOM is not an exact match",
          entity.same_word("QUALCOMM", "QUALCOM"), False)
    # Above the threshold a long descriptive word keeps a typo budget.
    check("MANUFACTURING / MANFACTURING is a typo (12 chars)",
          entity.same_word("MANUFACTURING", "MANFACTURING"), True)
    check("MANUFACTURING / MANUGACTURING is a typo",
          entity.same_word("MANUFACTURING", "MANUGACTURING"), True)
    check("ELECTRONICS / LELECTRONICS is a typo (11 chars)",
          entity.same_word("ELECTRONICS", "LELECTRONICS"), True)
    check("ELECTRONICS / ELECTRO are still different words",
          entity.same_word("ELECTRONICS", "ELECTRO"), False)
    # Plurals are a variant spelling, not a typo, and survive at any length.
    check("MOTOR / MOTORS is a plural", entity.same_word("MOTOR", "MOTORS"), True)
    check("TECHNOLOGY / TECHNOLOGIES is a plural",
          entity.same_word("TECHNOLOGY", "TECHNOLOGIES"), True)
    check("transposition costs one edit",
          entity.edit_distance("HUYNDAI", "HYUNDAI"), 1)
    # Corporate-form and boilerplate words keep their typo tolerance - a small closed
    # vocabulary cannot pull in an unrelated brand.
    check("suffix typo CORPORATON", entity.is_suffix_word("CORPORATON"), True)
    check("suffix typo CORPRATION", entity.is_suffix_word("CORPRATION"), True)
    check("shell typo TEHCNOLOGY", entity.is_shell_word("TEHCNOLOGY"), True)
    check("shell typo LINCENSING", entity.is_shell_word("LINCENSING"), True)
    # The calibration point from CONTEXT.md, verified against our own implementation.
    check(
        "JW(SAMSUNG ELECTRO MECHANICS, SAMSUNG ELECTRONICS) still >= 0.90 whole-string",
        entity.jaro_winkler("SAMSUNG ELECTRO MECHANICS", "SAMSUNG ELECTRONICS") >= 0.90,
        True,
    )
    check(
        "but the differing tokens are far apart",
        entity.jaro_winkler("ELECTRO", "ELECTRONICS") >= 0.90,
        True,
    )


def run_resolution() -> None:
    """End-to-end against the corpus. Skipped when no corpus is present."""
    try:
        import corpus

        con = corpus.connect()
    except Exception as exc:  # corpus.CorpusUnavailable or duckdb missing
        print(f"  (resolution tests skipped - no corpus: {exc})")
        return

    try:
        m = entity.resolve("Samsung Electronics Co., Ltd.", con=con)
        names = {c["name"] for c in m["in_scope"]}
        check("Samsung Display not in scope", "SAMSUNG DISPLAY CO LTD" in names, False)
        check("Samsung Electro Mechanics not in scope",
              "SAMSUNG ELECTRO MECHANICS CO LTD" in names, False)
        check("Samsung Electronics in scope", "SAMSUNG ELECTRONICS CO LTD" in names, True)

        m = entity.resolve("Microsoft Corporation", con=con)
        names = {c["name"] for c in m["in_scope"]}
        check("MTL in scope", "MICROSOFT TECHNOLOGY LICENSING LLC" in names, True)
        check("Microsoft Mobile not in scope", "MICROSOFT MOBILE OY" in names, False)

        m = entity.resolve("Hyundai Motor Company", con=con)
        names = {c["name"] for c in m["in_scope"]}
        excluded = {c["name"] for c in m["excluded"]}
        check("Honda never reaches the pool", "HONDA MOTOR CO LTD" in names | excluded, False)
        check("Hyundai Mobis excluded", "HYUNDAI MOBIS CO LTD" in excluded, True)

        # decisions.csv EXCLUDE rulings must bind at runtime, not only at build time.
        m = entity.resolve("Hyundai Motor Company", con=con)
        by_name = {c["name"]: c for c in m["excluded"]}
        if "HYUNDAI STEEL COMPANY" in by_name:
            check("prior ruling honoured for Hyundai Steel",
                  by_name["HYUNDAI STEEL COMPANY"]["reason"],
                  "prior ruling in decisions.csv")

        m = entity.resolve("NVIDIA Corporation", con=con)
        names = {c["name"] for c in m["in_scope"]}
        check("Avidia is not NVIDIA", "AVIDIA INC" in names, False)
        check("NVIDIA resolves", "NVIDIA CORPORATION" in names, True)

        # A misspelled company name is out of scope, but must be REPORTED rather than
        # silently dropped - otherwise strict matching hides the filer's own filings.
        m = entity.resolve("Qualcomm Incorporated", con=con)
        scope = {c["name"] for c in m["in_scope"]}
        near = {c["name"] for c in m["near_miss"]}
        check("QUALCOM is out of scope", "QUALCOM INCORPORATED" in scope, False)
        check("QUALCOM is reported as a near miss",
              "QUALCOM INCORPORATED" in near, True)
        check("near misses are warned about",
              any("spell the company name" in w for w in m["warnings"]), True)

        # Two edits away is a different company, and must not reach the near-miss list
        # where its volume would swamp the real typos.
        m = entity.resolve("Intel Corporation", con=con)
        near = {c["name"] for c in m["near_miss"]}
        scope = {c["name"] for c in m["in_scope"]}
        for other in ("LINTEC CORPORATION", "XINTEC INC", "INTELSAT CORPORATION"):
            check(f"{other} is neither in scope nor a near miss",
                  other in near or other in scope, False)
    finally:
        con.close()


def run_portfolio() -> None:
    """Company-level corpus access must work for ANY applicant, not just the 20 that
    the site-era app_company table covers."""
    try:
        import corpus
        import rules

        con = corpus.connect()
    except Exception as exc:
        print(f"  (portfolio tests skipped - no corpus: {exc})")
        return

    try:
        names = sorted(entity.scope_names("NVIDIA Corporation", con=con))
        corpus.materialise_scope(con, names)

        base = corpus.applicant_baseline(con, names, scoped=True)
        check("NVIDIA has a meaningful corpus portfolio", base["applications"] > 1000, True)
        check("allowance rate is a percentage",
              0 < (base.get("allowance_rate") or 0) <= 100, True)

        apps = corpus.applicant_applications(con, names, scoped=True)
        check("application count matches the baseline", len(apps), base["applications"])

        # Every row must be shaped for rules.from_corpus, or a portfolio figure and a
        # single-application audit could disagree.
        row = next(a for a in apps if a["events"])
        facts = rules.from_corpus(row)
        flags = rules.evaluate(facts)
        check("rules evaluate on a bulk-fetched row", set(flags),
              {"A1", "B1", "B2", "D2", "D3", "E1"})
        check("provenance is carried", facts.source, "corpus")

        # The 2012 floor: applicant organisation is unrecorded before the AIA, so
        # anything earlier would be a silently empty portfolio, not a small one.
        early = [a for a in apps if a["filing_date"].year < corpus.APPLICANT_FLOOR_YEAR]
        check("filing floor is enforced", early, [])

        ctx = corpus.applicant_context(con)
        check("national-stage share is reported",
              ctx.get("national_stage_share") is not None, True)
    finally:
        con.close()


if __name__ == "__main__":
    print("classification ...")
    run_classification()
    print("helpers ...")
    run_helpers()
    print("resolution ...")
    run_resolution()
    print("portfolio ...")
    run_portfolio()

    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED\n")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("\nall passed")

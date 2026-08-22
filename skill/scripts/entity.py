"""Entity resolution - step 1 of the pipeline.

Resolves a user-supplied company name to an explicit, auditable set of applicant
names, so that every downstream figure is scoped to one filer and nothing else.

Why this exists as its own step
-------------------------------
Scoping used to be a `--applicant` substring test inside audit.py. A substring test
keeps INTELLECTUAL VENTURES under "Intel", PINEAPPLE under "Apple", and TRUDELL and
LYONDELLBASELL under "Dell". sql/10_classify.sql fixed that at corpus build time with
token-boundary matching, but the fix never reached the runtime path, and it only ever
covered the 20 seeded companies.

This module applies the same precision discipline to any company, at runtime, and
emits a scope manifest you can inspect, save, and re-use - so "why was this
application in scope?" always has an answer.

Policy (Ben's rulings, 2026-08-21)
----------------------------------
STRICT FILER IDENTITY. Scope is the named entity plus renamed / shell / typo variants
of it - Microsoft Corporation and Microsoft Technology Licensing are one filer. Sibling
operating companies (LG Display under LG Electronics), regional arms, and joint
ventures are NOT rolled up. They are enumerated and reported so they can be opted in
deliberately, never swept in silently.

UNCERTAIN NAMES ARE EXCLUDED, LOUDLY. A name that cannot be confidently classified is
left out of scope, and the manifest reports it with the number of applications at
stake, so an under-counted denominator is visible rather than invisible.

decisions.csv EXCLUDE rulings are always honoured - they only ever remove names. Its
merge rulings are deliberately NOT applied here: they encode the corporate-family
rollup used for IFI-style ranking, which is the opposite of strict filer identity.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SKILL_ROOT.parent
_DECISIONS = _REPO_ROOT / "config" / "decisions.csv"

# A token appearing in this many or more DISTINCT applicant organisations is generic
# industry vocabulary, not evidence of identity. Measured over the corpus's 369,090
# distinct applicant names: TECHNOLOGY 17768, SYSTEMS 8446, INTERNATIONAL 6312,
# RESEARCH 5259, ELECTRONICS 2044, AMERICA 1618, SEMICONDUCTOR 878 - versus the brand
# tokens MICROSOFT 80, QUALCOMM 80, DELL 30, GOOGLE 23, APPLE 14.
WEAK_DF_THRESHOLD = 500

# Identity tokens at or below this length must match EXACTLY - no typo budget. Ben's
# ruling, 2026-08-21: the company name itself is matched strictly; only corporate-form
# and boilerplate words (Corp., Ltd., Licensing) get typo tolerance. Above this length
# a word is long enough that a one- or two-character edit is far more likely to be a
# misspelling than a different company (MANUFACTURING / MANFACTURING).
IDENTITY_EXACT_MAX_LEN = 10

CORPORATE_SUFFIXES = {
    "CO", "LTD", "INC", "CORP", "CORPORATION", "COMPANY", "LIMITED", "INCORPORATED",
    "LLC", "LLP", "LP", "L", "P", "C", "KK", "KABUSHIKI", "KAISHA", "GMBH", "AB",
    "NV", "SA", "PLC", "PUBL", "AG", "BV", "OY", "AS", "KGAA", "SARL", "SAS",
    "SPA", "SRL", "PTE", "PTY", "PVT", "SE",
}

# Words that denote the same filer wearing a different hat - an IP-holding or
# licensing vehicle. Microsoft Technology Licensing is Microsoft.
SHELL_TOKENS = {
    "IP", "TECHNOLOGY", "TECHNOLOGIES", "HOLDING", "HOLDINGS", "LICENSING",
    "LICENCING", "GROUP", "ENTERPRISES", "VENTURES",
}

# Geographic or organisational modifiers. A name differing from the target only by one
# of these plausibly IS the target's own regional or research arm - but equally may be
# a separate legal filer. Not determinable from patent data alone, so these land in
# UNCERTAIN rather than being called a distinct entity.
MODIFIER_TOKENS = {
    "AMERICA", "AMERICAS", "USA", "US", "EUROPE", "EUROPEAN", "ASIA", "PACIFIC",
    "JAPAN", "KOREA", "CHINA", "INDIA", "GERMANY", "FRANCE", "UK", "CANADA",
    "ISRAEL", "TAIWAN", "SINGAPORE", "INTERNATIONAL", "GLOBAL", "WORLDWIDE",
    "RESEARCH", "LAB", "LABS", "LABORATORY", "LABORATORIES", "DEVELOPMENT",
    "INSTITUTE", "CENTER", "CENTRE", "RD", "SCIENCE", "SCIENTIFIC", "INNOVATION",
    "INNOVATIONS", "SOLUTIONS", "OPERATIONS", "SERVICES", "SUBSIDIARY", "BRANCH",
}

NOISE_TOKENS = {"AND", "OF", "THE", "FOR", "DE", "A", "AN", "N"}


# --------------------------------------------------------------------- normalisation
def norm(s: str | None) -> str:
    """Uppercase, punctuation to space, collapse whitespace. Identical to the norm()
    macro in sql/10_classify.sql so runtime and build-time agree."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())).strip()


def jaro_winkler(a: str, b: str) -> float:
    """Jaro-Winkler similarity, matching DuckDB's jaro_winkler_similarity - the 0.90
    threshold in CONTEXT.md is calibrated against that function. SAMSUNG ELECTRO
    MECHANICS scores 0.941 against Samsung Electronics and is a different company,
    which is why the threshold cannot be lowered."""
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    reach = max(max(len(a), len(b)) // 2 - 1, 0)
    a_hit = [False] * len(a)
    b_hit = [False] * len(b)
    matches = 0
    for i, ch in enumerate(a):
        for j in range(max(0, i - reach), min(i + reach + 1, len(b))):
            if not b_hit[j] and b[j] == ch:
                a_hit[i] = b_hit[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    k = transpositions = 0
    for i, ch in enumerate(a):
        if a_hit[i]:
            while not b_hit[k]:
                k += 1
            if ch != b[k]:
                transpositions += 1
            k += 1
    m = float(matches)
    jaro = (m / len(a) + m / len(b) + (m - transpositions / 2) / m) / 3
    prefix = 0
    for x, y in zip(a[:4], b[:4]):
        if x != y:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def edit_distance(a: str, b: str) -> int:
    """Damerau-Levenshtein (optimal string alignment). An adjacent transposition
    counts as one edit, because that is what a typed mistake usually is:
    HUYNDAI for HYUNDAI, ELECTORNICS for ELECTRONICS, TECHNOLGOY for TECHNOLOGY."""
    la, lb = len(a), len(b)
    if abs(la - lb) > 3:
        return 4
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def _is_plural_pair(a: str, b: str) -> bool:
    """MOTOR/MOTORS, PRODUCT/PRODUCTS, TECHNOLOGY/TECHNOLOGIES. A different mechanism
    from typo tolerance: a plural is a variant spelling of the same word, and no two
    distinct filers have been observed to differ only by one."""
    if a + "S" == b or b + "S" == a:
        return True
    if a.endswith("IES") and b.endswith("Y") and a[:-3] == b[:-1]:
        return True
    if b.endswith("IES") and a.endswith("Y") and b[:-3] == a[:-1]:
        return True
    return False


def same_word(a: str, b: str) -> bool:
    """Are these two IDENTITY tokens the same word?

    Identity tokens - the actual company name - must match EXACTLY at or below
    IDENTITY_EXACT_MAX_LEN characters. No typo budget, because at that length a single
    edit is as likely to be a different company as a misspelling: NVIDIA/AVIDIA,
    INTEL/INTEC, SAMSUNG/SAMSIN are each one or two edits apart and each a different
    filer. Corporate-form and boilerplate words are handled separately by
    _vocab_typo(), which can afford to be forgiving because it matches against a small
    closed vocabulary.

    Above that length a bounded edit distance applies, so long descriptive words such
    as MANUFACTURING survive the misspellings USPTO actually contains (MANFACTURING,
    MANUFACTUING, MANUGACTURING).

    Deliberately NOT Jaro-Winkler at any length. JW awards a large bonus for a shared
    prefix: JW(INTEL, INTELSAT) and JW(INTEL, INTEPLAST) both clear 0.90, and
    JW(SAMSIN, SAS) clears 0.85. Using it merged 169 unrelated companies into Intel.
    """
    if a == b:
        return True
    if _is_plural_pair(a, b):
        return True
    if min(len(a), len(b)) <= IDENTITY_EXACT_MAX_LEN:
        return False
    return edit_distance(a, b) <= 2


def _vocab_typo(tok: str, word: str) -> bool:
    """Is `tok` a misspelling of a corporate-form or boilerplate word?

    Forgiving on purpose. CORPORATION, LIMITED, TECHNOLOGY and LICENSING are a small
    closed vocabulary, so a fuzzy match cannot pull in an unrelated brand the way it
    can on the company name itself. USPTO's own records contain COPORATION,
    INCORPORTED, TECHNOLGOY, TEHCNOLOGY, LICESNING and LINCENSING; without this each
    one looks like a real distinguishing word and splits a filer out of its own scope.
    """
    if tok == word:
        return True
    if len(tok) < 6 or len(word) < 6 or abs(len(tok) - len(word)) > 2:
        return False
    return edit_distance(tok, word) <= 2


def _is_typo_of(tok: str, vocabulary: set[str]) -> bool:
    """Is `tok` a misspelling of a word in `vocabulary`?"""
    return any(_vocab_typo(tok, w) for w in vocabulary)


def is_suffix_word(tok: str) -> bool:
    """Corporate suffix, or a close typo of one. USPTO itself contains COPORATION,
    INCORPORTED and INCOPORATED; without typo tolerance those survive stripping, look
    like real distinguishing words, and push a genuine match out of scope."""
    if tok in CORPORATE_SUFFIXES:
        return True
    # A token made only of L, C and P is a mangled LLC / LLP / LP / PC. USPTO holds
    # LC, LCC and LL; no real distinguishing word is spelled from those letters alone.
    if len(tok) <= 4 and set(tok) <= {"L", "C", "P"}:
        return True
    return _is_typo_of(tok, CORPORATE_SUFFIXES)


def is_shell_word(tok: str) -> bool:
    """Shell/holding word, or a close typo of one. USPTO contains TECHNOLGOY,
    TECHNOLGY, TECHOLOGY, TEHCNOLOGY, TECNOLOGY, LINCENSING and LICESNING - without
    typo tolerance each looks like a real distinguishing word and wrongly splits a
    filer's own licensing vehicle out of scope."""
    return tok in SHELL_TOKENS or _is_typo_of(tok, SHELL_TOKENS)


def is_noise(tok: str) -> bool:
    """Connector words, bare years, and single letters left behind by punctuation
    splitting (L.L.C. -> L L C, B.V. -> B V, c/o -> C O). Never identity-bearing."""
    return tok in NOISE_TOKENS or tok.isdigit() or len(tok) == 1


def core_tokens(s: str) -> list[str]:
    return [t for t in norm(s).split(" ") if t and not is_suffix_word(t)]


def identity_tokens(s_tokens: list[str]) -> list[str]:
    """Core tokens stripped of shell and noise words - what actually distinguishes
    one filer from another."""
    return [t for t in s_tokens if not is_shell_word(t) and not is_noise(t)]


# --------------------------------------------------------------------------- decisions
def load_exclusions() -> dict[str, str]:
    """EXCLUDE rulings from config/decisions.csv, keyed by normalised name."""
    out: dict[str, str] = {}
    if not _DECISIONS.exists():
        return out
    with _DECISIONS.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if (row.get("company_id") or "").strip().upper() == "EXCLUDE":
                out[norm(row.get("org_norm"))] = (row.get("note") or "").strip()
    return out


# ------------------------------------------------------------------------ enumeration
_NORM_MACRO = (
    "CREATE OR REPLACE TEMP MACRO norm(s) AS "
    "trim(regexp_replace(regexp_replace(upper(s), '[^A-Z0-9 ]', ' ', 'g'), ' +', ' ', 'g'))"
)


def token_df(con, tokens: list[str]) -> dict[str, int]:
    """How many distinct applicant organisations contain each token."""
    if not tokens:
        return {}
    _ensure_token_index(con)
    rows = con.execute(
        """
        SELECT tok, COUNT(*) AS df FROM (
            SELECT unnest(string_split(org_norm, ' ')) AS tok FROM _entity_org_index
        )
        WHERE list_contains(?::VARCHAR[], tok)
        GROUP BY tok
        """,
        [tokens],
    ).fetchall()
    return {t: d for t, d in rows}


_ORG_INDEX = "_entity_org_index"
_ORG_TOKENS = "_entity_org_tokens"


def _ensure_token_index(con) -> None:
    """Two lazily-built per-connection indexes: distinct applicant names with their
    application counts, and the distinct token vocabulary across them.

    Both exist for speed. Fuzzy-matching every token of all 6.7M applicant rows is
    roughly 27M edit-distance computations and took ~40s per resolve; the distinct
    token vocabulary is far smaller, so matching there first and enumerating by the
    few tokens that hit is orders of magnitude less work. Aggregating the names once
    likewise avoids re-normalising 6.7M rows on every call. Built once, then every
    subsequent resolve on the same connection is sub-second.
    """
    # Ask the database whether the tables are there rather than remembering in Python.
    # A previous version cached on id(con); CPython reuses an id once a connection is
    # collected, so a new connection could inherit a "ready" flag pointing at temp
    # tables that had gone with the old one, and every query against them failed.
    try:
        con.execute(f"SELECT 1 FROM {_ORG_INDEX} LIMIT 1").fetchone()
        con.execute(f"SELECT 1 FROM {_ORG_TOKENS} LIMIT 1").fetchone()
        return
    except Exception:
        pass
    con.execute(_NORM_MACRO)
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _entity_org_index AS
        SELECT norm(applicant_organization)         AS org_norm,
               COUNT(DISTINCT application_number)   AS apps,
               mode(applicant_country_code)         AS country
        FROM all_applicants
        WHERE applicant_organization IS NOT NULL
          AND length(trim(applicant_organization)) > 1
        GROUP BY 1
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _entity_org_tokens AS
        SELECT DISTINCT unnest(string_split(org_norm, ' ')) AS tok
        FROM _entity_org_index
        """
    )


def matching_tokens(con, anchor: str) -> list[str]:
    """Tokens that are the anchor, a one-edit near miss of it, or - for anchors long
    enough to carry a typo budget - within two edits.

    Mirrors same_word() and _near_anchor_token() so enumeration cannot disagree with
    classification about what is reachable.
    """
    _ensure_token_index(con)
    rows = con.execute(
        f"""
        SELECT tok FROM _entity_org_tokens
        WHERE tok = ?
           OR (length(tok) >= 5
               AND abs(length(tok) - length(?)) <= 1
               AND damerau_levenshtein(tok, ?) = 1)
           OR (length(?) > {IDENTITY_EXACT_MAX_LEN} AND length(tok) > {IDENTITY_EXACT_MAX_LEN}
               AND abs(length(tok) - length(?)) <= 2
               AND damerau_levenshtein(tok, ?) <= 2)
        """,
        [anchor, anchor, anchor, anchor, anchor, anchor],
    ).fetchall()
    return [r[0] for r in rows]


def enumerate_candidates(con, anchor: str | None, all_tokens: list[str]) -> list[dict]:
    """Every distinct applicant organisation that could be this filer.

    Matching is always on TOKEN BOUNDARIES, never a substring. The token INTEL does
    not match the token INTELLECTUAL, so Intellectual Ventures never enters the pool
    at all - which is precisely where the substring filter in audit.py went wrong.

    Anchored on the single MOST DISTINCTIVE token rather than every distinctive one.
    "Hyundai Motor Company" anchored on both HYUNDAI and MOTOR drags in Honda, Toyota
    and every other carmaker - correctly excluded afterwards, but it inflates the
    excluded-application count into something that looks like lost Hyundai volume.
    A typo tolerance on the anchor keeps HYUNDIA MOTOR COMPANY reachable.

    With no distinctive token at all, every token is generic and any one of them would
    match half the corpus, so the full name is required instead.
    """
    con.execute(_NORM_MACRO)
    if anchor:
        # Enumeration is deliberately looser than classification. Classification
        # requires the company name to match exactly, but a name that misses the
        # anchor by one character still has to be SEEN so it can be reported as a near
        # miss - otherwise a genuine misspelling of the filer becomes invisible rather
        # than excluded, which is the opposite of reporting loudly. The widening is
        # resolved against the token index first, so this stays a plain list lookup.
        predicate = "len(list_intersect(string_split(org_norm, ' '), ?::VARCHAR[])) > 0"
        params: list = [matching_tokens(con, anchor)]
    else:
        predicate = "list_has_all(string_split(org_norm, ' '), ?::VARCHAR[])"
        params = [all_tokens]

    _ensure_token_index(con)
    rows = con.execute(
        f"""
        SELECT org_norm, apps, country
        FROM _entity_org_index
        WHERE {predicate}
        ORDER BY apps DESC
        """,
        params,
    ).fetchall()
    return [{"name": r[0], "applications": r[1], "country": r[2]} for r in rows]


# ---------------------------------------------------------------------- classification
def _near_anchor_token(cand_core: list[str], anchor: str) -> str | None:
    """The token in this name that is ONE edit from the anchor, if any.

    One edit, not two. At two, the neighbourhood of a short brand token fills up with
    real companies: LINTEC and XINTEC are both two edits from INTEL and neither is
    Intel, and they carry enough volume (348 and 311 applications) to swamp the list
    they would appear in. One edit still catches what this is for - QUALCOM, MICROSFT,
    MIRCOSOFT, SUMSUNG, NIVIDIA, LNTEL.
    """
    for t in cand_core:
        if t != anchor and len(t) >= 5 and edit_distance(t, anchor) == 1:
            return t
    return None


def classify(target_core: list[str], cand_core: list[str]) -> tuple[str, str]:
    """One candidate name against the target. Returns (state, reason)."""
    if set(cand_core) == set(target_core):
        return "IN", "exact match"

    # Compare on identity-bearing tokens only. A filer's licensing vehicle differs
    # from the filer solely by shell words, so stripping those makes the two equal.
    t_id = identity_tokens(target_core)
    c_id = identity_tokens(cand_core)
    if c_id and set(c_id) == set(t_id):
        return "IN", "IP-holding or licensing vehicle of the same filer"

    extra = [x for x in c_id if x not in set(t_id)]
    missing = [x for x in t_id if x not in set(c_id)]

    if len(extra) == 1 and len(missing) == 1:
        # Compare ONLY the differing tokens. Whole-string similarity is what fooled
        # the variant sweep - HYUNDAI STEEL vs HYUNDAI AUTOEVER clears 0.90 on the
        # shared prefix alone (CONTEXT.md, 2026-08-02).
        if same_word(extra[0], missing[0]):
            return "IN", f"spelling variant ({missing[0]} / {extra[0]})"

    if not extra and missing:
        return "EXCLUDED", "name is a fragment of the target, not the target"

    substantive = [x for x in extra if x not in MODIFIER_TOKENS]
    if substantive:
        return "EXCLUDED", f"distinct entity - differs by {', '.join(substantive)}"

    if extra:
        return "EXCLUDED", (
            "regional or research arm - may be the same filer, "
            "not determinable from patent data"
        )

    return "EXCLUDED", "insufficient evidence of identity"


# ------------------------------------------------------------------------------ resolve
def resolve(entity: str, con=None) -> dict:
    """Resolve a company name to an auditable scope manifest."""
    import corpus

    owns_con = con is None
    if owns_con:
        con = corpus.connect()
    try:
        target_core = core_tokens(entity)
        if not target_core:
            raise ValueError(f"{entity!r} contains no usable name tokens.")

        df = token_df(con, target_core)
        id_core = identity_tokens(target_core) or target_core
        strong = [t for t in id_core if df.get(t, 0) < WEAK_DF_THRESHOLD]

        # Anchor on the rarest distinctive token - the one carrying the most identity.
        anchor = min(strong, key=lambda t: df.get(t, 0)) if strong else None

        candidates = enumerate_candidates(con, anchor, target_core)
        exclusions = load_exclusions()

        in_scope: list[dict] = []
        excluded: list[dict] = []
        near_miss: list[dict] = []
        for cand in candidates:
            name = cand["name"]
            cand_core = core_tokens(name)
            if name in exclusions:
                cand["reason"] = "prior ruling in decisions.csv"
                cand["ruling_note"] = exclusions[name]
                excluded.append(cand)
                continue

            state, reason = classify(target_core, cand_core)
            cand["reason"] = reason
            if state == "IN":
                in_scope.append(cand)
            elif anchor and anchor not in cand_core:
                # Came from the relaxed enumeration. It is a near miss only if
                # correcting the near-anchor token would make it resolve; otherwise
                # it is an unrelated company that merely looks similar (ONTEL and
                # INTEX under INTEL) and does not belong in the report at all.
                typo = _near_anchor_token(cand_core, anchor)
                if typo and classify(
                    target_core, [anchor if t == typo else t for t in cand_core]
                )[0] == "IN":
                    cand["reason"] = f"company name spelled {typo}, not {anchor}"
                    near_miss.append(cand)
            else:
                excluded.append(cand)

        excluded.sort(key=lambda c: -c["applications"])
        near_miss.sort(key=lambda c: -c["applications"])
        uncertain = [c for c in excluded if c["reason"].startswith("regional")]
        related = [c for c in excluded if c["reason"].startswith("distinct entity")]

        return {
            "entity": entity,
            "policy": "strict filer identity",
            "target_core_tokens": target_core,
            "distinctive_tokens": strong,
            "anchor_token": anchor,
            "token_document_frequency": df,
            "match": f"token-boundary on {anchor}" if anchor else "all tokens required",
            "in_scope": in_scope,
            "in_scope_names": len(in_scope),
            "in_scope_applications": sum(c["applications"] for c in in_scope),
            "excluded": excluded,
            "excluded_names": len(excluded),
            "excluded_applications": sum(c["applications"] for c in excluded),
            "near_miss": near_miss,
            "near_miss_names": len(near_miss),
            "near_miss_applications": sum(c["applications"] for c in near_miss),
            "uncertain_names": len(uncertain),
            "uncertain_applications": sum(c["applications"] for c in uncertain),
            "related_entity_names": len(related),
            "related_entity_applications": sum(c["applications"] for c in related),
            "warnings": _warnings(entity, in_scope, uncertain, strong, target_core,
                                  near_miss),
        }
    finally:
        if owns_con:
            con.close()


def _warnings(entity, in_scope, uncertain, strong, target_core, near_miss=()) -> list[str]:
    w: list[str] = []
    if near_miss:
        n = sum(c["applications"] for c in near_miss)
        w.append(
            f"{len(near_miss)} name(s) covering {n:,} applications spell the company "
            "name slightly differently and were left OUT, because the company name is "
            "matched exactly. Review the near-miss list: these are usually the filer's "
            "own applications with a USPTO typo."
        )
    if not in_scope:
        w.append(
            f"No applicant name in the corpus resolves to {entity!r}. Check spelling, "
            "or the filer may post-date the corpus (frozen June 2023) - confirm via ODP."
        )
    if not strong:
        w.append(
            "No distinctive token in this name; every token is generic industry "
            f"vocabulary ({', '.join(target_core)}). Matching required the full name, "
            "so a filer using a shortened form will be missed."
        )
    if uncertain:
        n = sum(c["applications"] for c in uncertain)
        w.append(
            f"{len(uncertain)} name(s) covering {n:,} applications were left OUT of "
            "scope as possible regional or research arms. If any belongs to this "
            "filer, the denominator is understated by that amount."
        )
    return w


def scope_names(entity: str, con=None) -> set[str]:
    """Just the in-scope normalised names - what audit.py filters on."""
    return {c["name"] for c in resolve(entity, con=con)["in_scope"]}


class Matcher:
    """Decides whether a given application belongs to one filer.

    Source-neutral, the same way rules.py is: the corpus manifest is a fast path, but
    any name absent from it - a live ODP record, a post-2023 filing, a typo nobody has
    made before - is classified with the identical rules rather than dropped. Building
    without a corpus is fine; it just loses the fast path.
    """

    def __init__(self, entity: str, con=None, use_corpus: bool = True):
        self.entity = entity
        self.target_core = core_tokens(entity)
        if not self.target_core:
            raise ValueError(f"{entity!r} contains no usable name tokens.")
        self.exclusions = load_exclusions()
        self.manifest: dict | None = None
        self.in_scope: set[str] = set()
        if use_corpus:
            try:
                self.manifest = resolve(entity, con=con)
                self.in_scope = {c["name"] for c in self.manifest["in_scope"]}
            except Exception:
                # ODP-only mode. Classification still applies.
                self.manifest = None

    def match_name(self, applicant_name: str | None) -> tuple[bool, str]:
        n = norm(applicant_name)
        if not n:
            return False, "no applicant name on the record"
        if n in self.exclusions:
            return False, "prior ruling in decisions.csv"
        if n in self.in_scope:
            return True, "in resolved scope"
        state, reason = classify(self.target_core, core_tokens(n))
        return state == "IN", reason

    def match_application(self, applicant_names: list[str | None]) -> tuple[bool, str]:
        """An application is in scope if ANY applicant on it is the target filer.

        Joint filings are real and large - Hyundai and Kia co-file 5,879 applications,
        essentially Kia's entire portfolio (CONTEXT.md). Testing only the first
        applicant would drop every one of them from the second filer's audit.
        """
        if not applicant_names:
            return False, "no applicant on the record"
        reasons = []
        for name in applicant_names:
            ok, why = self.match_name(name)
            if ok:
                return True, why
            reasons.append(f"{norm(name) or '(blank)'}: {why}")
        return False, "; ".join(reasons[:3])


# ---------------------------------------------------------------------------- reporting
def render(m: dict) -> str:
    L = [
        f"Entity resolution - {m['entity']}",
        f"  policy      : {m['policy']}",
        f"  matched on  : {m['match']}",
        "",
        f"IN SCOPE  {m['in_scope_names']} name(s), {m['in_scope_applications']:,} applications",
    ]
    for c in m["in_scope"]:
        L.append(f"    {c['applications']:>8,}  {c['name']}  [{c['reason']}]")

    L += ["", f"EXCLUDED  {m['excluded_names']} name(s), {m['excluded_applications']:,} applications"]
    if m["related_entity_names"]:
        L.append(
            f"  related entities ({m['related_entity_names']} names, "
            f"{m['related_entity_applications']:,} applications) - opt in deliberately if wanted:"
        )
        for c in [x for x in m["excluded"] if x["reason"].startswith("distinct entity")][:15]:
            L.append(f"    {c['applications']:>8,}  {c['name']}  [{c['reason']}]")
    if m["uncertain_names"]:
        L.append(
            f"  UNCERTAIN ({m['uncertain_names']} names, "
            f"{m['uncertain_applications']:,} applications) - excluded, may belong to this filer:"
        )
        for c in [x for x in m["excluded"] if x["reason"].startswith("regional")][:15]:
            L.append(f"    {c['applications']:>8,}  {c['name']}")

    if m.get("near_miss_names"):
        L += ["", f"NEAR MISS  {m['near_miss_names']} name(s), "
                  f"{m['near_miss_applications']:,} applications - the company name is "
                  "spelled differently, so they are out of scope under exact matching. "
                  "Usually the filer's own applications with a USPTO typo:"]
        for c in m["near_miss"][:15]:
            L.append(f"    {c['applications']:>8,}  {c['name']}  [{c['reason']}]")

    for warning in m["warnings"]:
        L += ["", f"  ! {warning}"]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="Resolve a company name to an audit scope.")
    ap.add_argument("entity")
    ap.add_argument("--json", action="store_true", help="emit the manifest as JSON")
    ap.add_argument("--save", metavar="PATH", help="write the manifest to a JSON file")
    args = ap.parse_args()

    manifest = resolve(args.entity)
    print(json.dumps(manifest, indent=2, default=str) if args.json else render(manifest))
    if args.save:
        Path(args.save).write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8"
        )
        print(f"\nmanifest written to {args.save}", file=sys.stderr)


if __name__ == "__main__":
    main()

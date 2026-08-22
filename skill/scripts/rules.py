"""Prosecution rules for the patent-portfolio-analyzer skill.

Normalises an application from either source - the local PatEx corpus or the live
ODP API - into one shape, then evaluates the rules against it. Both sources use the
same USPTO event codes (CTNF, CTRS, MN/=. ...) and the same continuation type codes
(CON/DIV/CIP/NST), so the rules run unchanged on either.

WHAT THESE FLAGS ARE. They identify UNEXERCISED OPTIONS, not errors. The public
record contains no client instruction, budget, or strategy, so no rule here can
distinguish a mistake from a deliberate decision. Output language matters: a
document calling a prosecution decision an "error" is discoverable, and running
this over your own or a client's portfolio produces exactly such a document.

THREE STATES. Absence-based rules never assert "no child was filed" when a child
would not yet be visible:
    PRESENT       - the filing exists
    FLAG          - enough time passed for it to appear, and it did not
    INDETERMINATE - disposed too close to the data horizon to tell
    N/A           - the rule does not apply to this application
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable

REJECTION_CODES = {"CTNF", "CTFR"}
RESTRICTION_CODES = {"CTRS", "MRTRS"}
ALLOWANCE_CODES = {"MN/=."}
RCE_CODES = {"RCEX"}
INTERVIEW_CODES = {"EXIN", "EXAC", "EXAT", "EXET"}
APPEAL_CODES = {"N/AP"}
FAI_PILOT_CODES = {"FAIA", "FAOO"}

# A granted petition to revive is the evidence that an abandonment was UNINTENTIONAL.
# Abandonment on its own is not a finding: 774,934 modern utility applications went
# abandoned for failure to respond, which is simply the normal, cheap way to drop a
# case you have decided not to pursue. Nobody files a revival petition on a case they
# meant to abandon, so keying on the petition is what separates a docketing failure
# from a deliberate decision. Measured: 42,444 granted, 211 dismissed.
REVIVAL_GRANTED_CODES = {
    "PREV", "MPREV", "P032", "MP032", "MP001",
    "ODPET1", "ODPET3", "ODPET7", "MODPET1", "MODPET3", "MODPET7",
}
# Dismissed is the worse outcome: the lapse happened, revival was attempted, and the
# application was lost anyway.
REVIVAL_DISMISSED_CODES = {"ODPET4", "ODPET8", "MODPET4", "MODPET8"}

CHILD_TYPES = {"CON", "DIV", "CIP"}

# The corpus is a June 2023 snapshot. Allow a year of slack so a child filed shortly
# before a parent issued still had time to be recorded before the pull.
CORPUS_HORIZON = date(2022, 6, 30)

# More than two RCEs. Measured: 59,525 modern utility applications.
RCE_THRESHOLD = 2


def _as_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(str(value)[: len(fmt) + 6], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


@dataclass
class Child:
    application: str
    kind: str          # CON / DIV / CIP / NST
    filed: date | None


@dataclass
class AppFacts:
    """Source-neutral view of one application."""
    application: str
    source: str                      # "corpus" | "odp"
    filing_date: date | None = None
    patent_number: str | None = None
    issue_date: date | None = None
    status: str | None = None
    status_date: date | None = None
    examiner: str | None = None
    art_unit: str | None = None
    title: str | None = None
    events: list[tuple[date | None, str]] = field(default_factory=list)
    children: list[Child] = field(default_factory=list)
    children_known: bool = True      # False when children were not fetched
    horizon: date | None = None      # data currency limit for three-state logic

    # ---- derived -------------------------------------------------------
    def _first(self, codes: Iterable[str]) -> date | None:
        hits = [d for d, c in self.events if c in codes and d]
        return min(hits) if hits else None

    def _count(self, codes: Iterable[str]) -> int:
        return sum(1 for _, c in self.events if c in codes)

    @property
    def first_rejection(self) -> date | None:
        return self._first(REJECTION_CODES)

    @property
    def first_restriction(self) -> date | None:
        return self._first(RESTRICTION_CODES)

    @property
    def first_allowance(self) -> date | None:
        return self._first(ALLOWANCE_CODES)

    @property
    def office_actions(self) -> int:
        return self._count(REJECTION_CODES)

    @property
    def rce_count(self) -> int:
        return self._count(RCE_CODES)

    @property
    def interviews(self) -> int:
        return self._count(INTERVIEW_CODES)

    @property
    def appeals(self) -> int:
        return self._count(APPEAL_CODES)

    @property
    def fai_pilot(self) -> bool:
        return self._count(FAI_PILOT_CODES) > 0

    @property
    def had_restriction(self) -> bool:
        return self.first_restriction is not None

    @property
    def revivals_granted(self) -> int:
        return self._count(REVIVAL_GRANTED_CODES)

    @property
    def revivals_dismissed(self) -> int:
        return self._count(REVIVAL_DISMISSED_CODES)

    @property
    def disposition(self) -> str:
        s = (self.status or "").lower()
        if "patented case" in s or "patent expired due to nonpayment" in s:
            return "granted"
        if "abandon" in s:
            return "abandoned"
        return "pending"

    @property
    def disposal_date(self) -> date | None:
        if self.disposition == "granted":
            return self.issue_date or self.status_date
        if self.disposition == "abandoned":
            return self.status_date
        return None

    @property
    def first_action_allowance(self) -> bool:
        """Allowance with no prior rejection.

        Standard definition: a restriction is not a rejection on the merits, so it
        does not disqualify. FAI pilot cases are excluded - their "first action" is a
        different procedure and would inflate the rate.
        """
        noa = self.first_allowance
        if noa is None or self.fai_pilot:
            return False
        rej = self.first_rejection
        return rej is None or noa < rej

    @property
    def months_to_issue(self) -> int | None:
        if self.filing_date and self.issue_date:
            return round((self.issue_date - self.filing_date).days / 30.44)
        return None

    def _observable(self) -> bool:
        """Would a child filed against this application be visible in the data yet?"""
        disposed = self.disposal_date
        if disposed is None:
            return False
        horizon = self.horizon or (date.today() - timedelta(days=548))
        return disposed <= horizon

    def children_of(self, *kinds: str) -> list[Child]:
        return [c for c in self.children if c.kind in kinds]


def evaluate(f: AppFacts) -> dict:
    """Return {rule: {state, detail}} for one application."""
    out: dict[str, dict] = {}
    observable = f._observable()

    # Children whose parentage code the source could not classify. PatEx carries 6,058
    # children typed '?' under modern parents, and ODP marks ~11% of inline child
    # entries the same way. Such a child may BE the divisional or the continuation the
    # absence rules are looking for, so its presence must degrade the answer to
    # INDETERMINATE - counting it as absence fabricates a FLAG. Only genuinely
    # unclassified codes qualify: REI, REX, NST and the rest are known types that
    # simply are not continuing applications, and must not soften an absence finding.
    unknown_kids = [c for c in f.children if (c.kind or "?").strip() in ("", "?")]

    # ---- A1: first-action allowance, no continuation filed before issuance
    if not f.first_action_allowance or f.disposition != "granted":
        out["A1"] = {"state": "N/A", "detail": "not a granted first-action allowance"}
    elif not f.children_known:
        out["A1"] = {"state": "INDETERMINATE", "detail": "children not fetched"}
    elif f.issue_date is None:
        # 16,822 granted corpus records carry no issue date. Without it the copendency
        # comparison cannot run, and silently dropping every child would flag a case
        # whose continuation is sitting right there in the record.
        out["A1"] = {"state": "INDETERMINATE",
                     "detail": "granted but no issue date recorded; copendency cannot be tested"}
    else:
        kids = [c for c in f.children_of(*CHILD_TYPES)
                if c.filed and c.filed <= f.issue_date]
        undated = [c for c in f.children_of(*CHILD_TYPES) if c.filed is None]
        if kids:
            out["A1"] = {"state": "PRESENT",
                         "detail": f"{len(kids)} continuing application(s) filed before issue"}
        elif undated or unknown_kids:
            out["A1"] = {"state": "INDETERMINATE",
                         "detail": "a child exists whose filing date or type is not recorded"}
        elif not observable:
            out["A1"] = {"state": "INDETERMINATE",
                         "detail": "disposed too near the data horizon to confirm absence"}
        else:
            out["A1"] = {"state": "FLAG",
                         "detail": "allowed on first action; no continuation filed before issuance"}

    # ---- B1: restriction issued, no divisional ever filed
    if not f.had_restriction or f.disposition == "pending":
        out["B1"] = {"state": "N/A", "detail": "no restriction requirement, or still pending"}
    elif not f.children_known:
        out["B1"] = {"state": "INDETERMINATE", "detail": "children not fetched"}
    else:
        divs = f.children_of("DIV")
        if divs:
            out["B1"] = {"state": "PRESENT", "detail": f"{len(divs)} divisional(s) filed"}
        elif unknown_kids:
            out["B1"] = {"state": "INDETERMINATE",
                         "detail": f"{len(unknown_kids)} child(ren) of unrecorded type - "
                                   "one may be the divisional"}
        elif not observable:
            out["B1"] = {"state": "INDETERMINATE",
                         "detail": "disposed too near the data horizon to confirm absence"}
        else:
            out["B1"] = {"state": "FLAG",
                         "detail": "restriction issued; no divisional filed for the non-elected claims"}

    # ---- B2: restriction issued, child filed as continuation rather than divisional
    if not f.had_restriction or f.disposition == "pending":
        out["B2"] = {"state": "N/A", "detail": "no restriction, or still pending"}
    elif not f.children_known:
        out["B2"] = {"state": "INDETERMINATE", "detail": "children not fetched"}
    elif f.children_of("DIV"):
        out["B2"] = {"state": "PRESENT", "detail": "a divisional was filed"}
    elif unknown_kids and not f.children_of("CON"):
        out["B2"] = {"state": "INDETERMINATE",
                     "detail": "a child of unrecorded type exists; its designation is unknown"}
    elif f.children_of("CON"):
        out["B2"] = {
            "state": "FLAG",
            "detail": ("restriction issued; child designated a continuation, not a divisional. "
                       "Sec. 121 safe harbour may not attach - courts look to substance and "
                       "consonance rather than the ADS label, so this warrants review"),
        }
    else:
        out["B2"] = {"state": "N/A", "detail": "no continuing application filed"}

    # ---- D2: three or more office actions with no examiner interview
    if f.office_actions >= 3 and f.interviews == 0:
        out["D2"] = {"state": "FLAG",
                     "detail": f"{f.office_actions} office actions, no interview conducted"}
    else:
        out["D2"] = {"state": "N/A", "detail": "fewer than 3 office actions, or an interview occurred"}

    # ---- D3: more than two RCEs
    if f.rce_count > RCE_THRESHOLD:
        out["D3"] = {"state": "FLAG",
                     "detail": f"{f.rce_count} RCEs filed"
                               + ("" if f.appeals else "; no appeal was taken")}
    else:
        out["D3"] = {"state": "N/A", "detail": f"{f.rce_count} RCE(s)"}

    # ---- E1: unintentional abandonment, evidenced by a petition to revive
    if f.revivals_dismissed and not f.revivals_granted:
        out["E1"] = {"state": "FLAG",
                     "detail": ("application went abandoned and a petition to revive was "
                                "DISMISSED - the lapse was not cured and the application "
                                "was lost")}
    elif f.revivals_dismissed and f.revivals_granted:
        # Both present means an early petition failed and a later one succeeded. The
        # application was NOT lost, so it must not be reported as though it were.
        out["E1"] = {"state": "FLAG",
                     "detail": (f"application went abandoned unintentionally; "
                                f"{f.revivals_dismissed} petition(s) to revive were dismissed "
                                "before one was granted")}
    elif f.revivals_granted:
        out["E1"] = {"state": "FLAG",
                     "detail": ("application went abandoned unintentionally and was revived "
                                "on petition - the revival is evidence the abandonment was "
                                "not a deliberate decision")}
    else:
        out["E1"] = {"state": "N/A", "detail": "no petition to revive on the record"}

    # Counting rules read events that can still accrue while an application is alive.
    # Two RCEs before the data horizon and a third after it is a finding the record
    # cannot yet show, so a negative answer on a live application is provisional -
    # true as of the data, not final.
    if f.disposition == "pending":
        for rule in ("D2", "D3", "E1"):
            if out[rule]["state"] == "N/A":
                out[rule]["provisional"] = True
                out[rule]["detail"] += "; still pending, so this count may still grow"

    return out


# --------------------------------------------------------------------- adapters
def from_corpus(row: dict) -> AppFacts:
    """Build AppFacts from corpus.application_facts() output."""
    return AppFacts(
        application=str(row.get("application_number")),
        source="corpus",
        filing_date=_as_date(row.get("filing_date")),
        patent_number=row.get("patent_number"),
        issue_date=_as_date(row.get("patent_issue_date")),
        status=row.get("appl_status_desc"),
        status_date=_as_date(row.get("appl_status_date")),
        examiner=row.get("examiner_full_name"),
        art_unit=row.get("examiner_art_unit"),
        title=row.get("invention_title"),
        events=[(_as_date(e.get("recorded_date")), e.get("event_code")) for e in row.get("events", [])],
        children=[Child(str(c.get("child")), c.get("continuation_type"), _as_date(c.get("child_filing_date")))
                  for c in row.get("children", [])],
        children_known=True,
        horizon=CORPUS_HORIZON,
    )


def from_odp(wrapper: dict, children: list[dict] | None = None) -> AppFacts:
    """Build AppFacts from an ODP patentFileWrapperDataBag entry.

    `children` comes from the /continuity endpoint's childContinuityBag; search results
    carry only parentContinuityBag, so absence-based rules stay INDETERMINATE until
    continuity is fetched.
    """
    meta = wrapper.get("applicationMetaData") or {}
    return AppFacts(
        application=str(wrapper.get("applicationNumberText")),
        source="odp",
        filing_date=_as_date(meta.get("filingDate")),
        patent_number=meta.get("patentNumber"),
        issue_date=_as_date(meta.get("grantDate") or meta.get("patentIssueDate")),
        status=meta.get("applicationStatusDescriptionText"),
        status_date=_as_date(meta.get("applicationStatusDate")),
        examiner=meta.get("examinerNameText"),
        art_unit=meta.get("groupArtUnitNumber"),
        title=meta.get("inventionTitle"),
        events=[(_as_date(e.get("eventDate")), e.get("eventCode"))
                for e in wrapper.get("eventDataBag", []) or []],
        children=[Child(str(c.get("childApplicationNumberText")),
                        c.get("claimParentageTypeCode"),
                        _as_date(c.get("childApplicationFilingDate")))
                  for c in (children or [])],
        children_known=children is not None,
        horizon=date.today() - timedelta(days=548),
    )


def summarise(f: AppFacts, flags: dict) -> dict:
    return {
        "application": f.application,
        "source": f.source,
        "title": f.title,
        "examiner": f.examiner,
        "art_unit": f.art_unit,
        "filed": str(f.filing_date) if f.filing_date else None,
        "patent": f.patent_number,
        "issued": str(f.issue_date) if f.issue_date else None,
        "disposition": f.disposition,
        "office_actions": f.office_actions,
        "rces": f.rce_count,
        "interviews": f.interviews,
        "appeals": f.appeals,
        "restriction": f.had_restriction,
        "revivals_granted": f.revivals_granted,
        "revivals_dismissed": f.revivals_dismissed,
        "first_action_allowance": f.first_action_allowance,
        "months_to_issue": f.months_to_issue,
        "children": [{"application": c.application, "type": c.kind,
                      "filed": str(c.filed) if c.filed else None} for c in f.children],
        "flags": flags,
        "flagged": sorted(r for r, v in flags.items() if v["state"] == "FLAG"),
    }

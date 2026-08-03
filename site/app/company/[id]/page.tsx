import Link from "next/link";
import { notFound } from "next/navigation";
import { getCompanies, getCompany } from "@/lib/data";
import { RULE_LABELS, TECH_CENTER_LABELS, type FlagStat } from "@/lib/types";
import { Bars, ChartLegend, Donut, TrendLine } from "@/components/Charts";
import FlaggedTable from "./FlaggedTable";

export function generateStaticParams() {
  return getCompanies().map((c) => ({ id: c.id }));
}

function FlagCard({ rule, stat }: { rule: "A1" | "B1" | "B2"; stat: FlagStat }) {
  const label = RULE_LABELS[rule];
  return (
    <div className="card">
      <h3>
        <span className="badge flag">{rule}</span> {label.short}
      </h3>
      <div style={{ display: "flex", gap: 22, alignItems: "baseline", margin: "10px 0 8px" }}>
        <div>
          <div className="stat">
            <div className="value" style={{ color: "var(--flag)" }}>
              {stat.flagged.toLocaleString()}
            </div>
            <div className="note">flagged</div>
          </div>
        </div>
        {stat.rate !== null && (
          <div className="stat">
            <div className="value" style={{ fontSize: 19 }}>{stat.rate}%</div>
            <div className="note">of eligible cases</div>
          </div>
        )}
        {stat.indeterminate > 0 && (
          <div className="stat">
            <div className="value" style={{ fontSize: 19, color: "var(--indet)" }}>
              {stat.indeterminate.toLocaleString()}
            </div>
            <div className="note">indeterminate</div>
          </div>
        )}
      </div>
      <p className="small muted" style={{ margin: 0 }}>{label.why}</p>
    </div>
  );
}

export default async function CompanyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const all = getCompanies();
  const summary = all.find((c) => c.id === id);
  if (!summary) notFound();
  const detail = getCompany(id);

  const techData = detail.tech.map((t) => ({
    name: TECH_CENTER_LABELS[t.tech_center] ?? t.tech_center,
    value: t.applications,
    pct: t.pct,
  }));

  const lowCoverageYears = detail.by_year.filter((y) => y.coverage_pct < 85).map((y) => y.year);

  return (
    <>
      <Link className="backlink" href="/">
        &larr; All companies
      </Link>
      <h1>{detail.name}</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        Rank {detail.ifi_rank} by 2025 US patent grants &middot;{" "}
        {summary.applications.toLocaleString()} utility applications filed 2013&ndash;2019
      </p>

      <div className="grid cols-4" style={{ marginTop: 20 }}>
        <div className="card stat">
          <div className="label">Allowance rate</div>
          <div className="value">{summary.allowance_rate}%</div>
          <div className="note">
            {summary.granted.toLocaleString()} granted / {summary.abandoned.toLocaleString()} abandoned
          </div>
        </div>
        <div className="card stat">
          <div className="label">Median time to issue</div>
          <div className="value">{summary.median_months_to_issue} mo</div>
          <div className="note">Filing to grant</div>
        </div>
        <div className="card stat">
          <div className="label">Office actions</div>
          <div className="value">{summary.mean_office_actions}</div>
          <div className="note">Mean per application</div>
        </div>
        <div className="card stat">
          <div className="label">Restriction rate</div>
          <div className="value">{summary.restriction_rate}%</div>
          <div className="note">Received a requirement</div>
        </div>
      </div>

      <div className="grid cols-4" style={{ marginTop: 14 }}>
        <div className="card stat">
          <div className="label">First-action allowance</div>
          <div className="value">{summary.faa_rate}%</div>
          <div className="note">Allowed with no prior rejection</div>
        </div>
        <div className="card stat">
          <div className="label">National stage (&sect;371)</div>
          <div className="value">{summary.national_stage_rate}%</div>
          <div className="note">Entered via PCT</div>
        </div>
        <div className="card stat">
          <div className="label">Interviews</div>
          <div className="value">{summary.interview_rate}%</div>
          <div className="note">Had at least one</div>
        </div>
        <div className="card stat">
          <div className="label">RCEs</div>
          <div className="value">{summary.mean_rces}</div>
          <div className="note">Mean per application</div>
        </div>
      </div>

      <h2>Filings by year</h2>
      {lowCoverageYears.length > 0 && (
        <p className="muted small" style={{ marginTop: -4 }}>
          <strong>{lowCoverageYears.join(" and ")}</strong>{" "}
          {lowCoverageYears.length > 1 ? "are" : "is"} understated. USPTO only began recording
          the applicant organisation systematically after the AIA, so early years capture a
          fraction of actual filings &mdash; the rise across these years reflects data coverage,
          not filing behaviour.
        </p>
      )}
      <div className="card">
        <Bars
          data={detail.by_year as unknown as Record<string, unknown>[]}
          bars={[
            { key: "granted", name: "Granted", color: "#3d7ab8" },
            { key: "abandoned", name: "Abandoned", color: "#c2554d" },
            { key: "pending", name: "Pending", color: "#7d8fa1" },
          ]}
          stacked
        />
      </div>

      <div className="grid cols-2" style={{ marginTop: 14 }}>
        <div className="card">
          <h3>Allowance rate by filing year</h3>
          <TrendLine
            data={detail.by_year as unknown as Record<string, unknown>[]}
            lines={[{ key: "allowance_rate", name: "Allowance rate (%)" }]}
          />
        </div>
        <div className="card">
          <h3>Median months to issue</h3>
          <TrendLine
            data={detail.by_year as unknown as Record<string, unknown>[]}
            lines={[{ key: "median_months_to_issue", name: "Months" }]}
          />
        </div>
      </div>

      <h2>Technology mix</h2>
      <p className="muted small" style={{ marginTop: -4 }}>
        By USPTO technology centre, derived from the examining art unit.
      </p>
      <div className="card">
        <Donut data={techData} />
        <ChartLegend
          items={techData.map((t) => ({ label: t.name, value: `${t.pct}%` }))}
        />
      </div>

      <h2>Review flags</h2>
      <p className="muted small" style={{ marginTop: -4, maxWidth: 760 }}>
        These identify <strong>unexercised options</strong>, not errors. The public record
        contains no client instructions, budgets, or strategy, so no rule here can distinguish a
        mistake from a deliberate decision.
      </p>
      <div className="grid cols-3">
        <FlagCard rule="A1" stat={summary.flags.a1} />
        <FlagCard rule="B1" stat={summary.flags.b1} />
        <FlagCard rule="B2" stat={summary.flags.b2} />
      </div>

      <h2>Flagged applications</h2>
      <FlaggedTable companyId={detail.id} expected={detail.flagged_count} />
    </>
  );
}

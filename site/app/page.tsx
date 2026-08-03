import Link from "next/link";
import { getCompanies, getMeta, getStats } from "@/lib/data";
import { SHORT_NAMES } from "@/lib/types";
import { Bars } from "@/components/Charts";

export default function Home() {
  const companies = getCompanies();
  const meta = getMeta();
  // Corpus totals come from stats.json. Summing the per-company `applications` field
  // would double-count the 6,292 jointly filed applications (Hyundai/Kia alone account
  // for 5,879 of them).
  const stats = getStats();

  const byApps = [...companies].sort((a, b) => b.applications - a.applications);
  const byAllowance = [...companies].sort((a, b) => b.allowance_rate - a.allowance_rate);
  const byRestriction = [...companies].sort((a, b) => b.restriction_rate - a.restriction_rate);

  return (
    <>
      <h1>Twenty US patent filers, examined</h1>
      <p className="muted" style={{ marginTop: 0, maxWidth: 760 }}>
        Prosecution-level analysis of {stats.distinct_applications.toLocaleString()} US utility
        applications filed 2013&ndash;2019, built entirely from USPTO public records. Allowance
        rates, pendency, restriction practice, and{" "}
        {stats.distinct_flagged_applications.toLocaleString()} applications where a procedural
        option appears to have gone unexercised.
      </p>

      <div className="grid cols-4" style={{ marginTop: 22 }}>
        <div className="card stat">
          <div className="label">Companies</div>
          <div className="value">{companies.length}</div>
          <div className="note">Top US patent recipients, 2025</div>
        </div>
        <div className="card stat">
          <div className="label">Applications</div>
          <div className="value">{(stats.distinct_applications / 1000).toFixed(0)}k</div>
          <div className="note">Utility, filed 2013&ndash;2019</div>
        </div>
        <div className="card stat">
          <div className="label">Flagged applications</div>
          <div className="value">
            {(stats.distinct_flagged_applications / 1000).toFixed(1)}k
          </div>
          <div className="note">
            {stats.distinct_flag_rows.toLocaleString()} flags across three rules
          </div>
        </div>
        <div className="card stat">
          <div className="label">Data source</div>
          <div className="value" style={{ fontSize: 19 }}>PatEx</div>
          <div className="note">USPTO, June 2023 pull</div>
        </div>
      </div>

      <h2>Portfolio size</h2>
      <div className="card">
        <Bars
          data={byApps.map((c) => ({ name: SHORT_NAMES[c.id] ?? c.name, applications: c.applications }))}
          bars={[{ key: "applications", name: "Applications" }]}
          xKey="name"
          layout="vertical"
          height={560}
        />
      </div>

      <h2>Allowance rate</h2>
      <p className="muted small" style={{ marginTop: -4 }}>
        Grants as a share of disposed applications (granted + abandoned). Pending cases are
        excluded, so recent cohorts are not penalised.
      </p>
      <div className="card">
        <Bars
          data={byAllowance.map((c) => ({ name: SHORT_NAMES[c.id] ?? c.name, rate: c.allowance_rate }))}
          bars={[{ key: "rate", name: "Allowance rate (%)" }]}
          xKey="name"
          layout="vertical"
          height={560}
        />
      </div>

      <h2>Restriction rate</h2>
      <p className="muted small" style={{ marginTop: -4 }}>
        Share of applications receiving a restriction or election requirement. This tracks
        technology far more than filing behaviour &mdash; semiconductor and display filers are
        restricted constantly, software and communications filers rarely.
      </p>
      <div className="card">
        <Bars
          data={byRestriction.map((c) => ({ name: SHORT_NAMES[c.id] ?? c.name, rate: c.restriction_rate }))}
          bars={[{ key: "rate", name: "Restriction rate (%)" }]}
          xKey="name"
          layout="vertical"
          height={560}
        />
      </div>

      <h2>All companies</h2>
      <div className="card" style={{ padding: 0 }}>
        <div className="table-scroll" style={{ maxHeight: 620 }}>
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th className="num">Apps</th>
                <th className="num">Allowance</th>
                <th className="num">Months to issue</th>
                <th className="num">Office actions</th>
                <th className="num">Restriction</th>
                <th className="num">1st-action allow.</th>
                <th className="num">Flags</th>
              </tr>
            </thead>
            <tbody>
              {companies.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link href={`/company/${c.id}/`}>{c.name}</Link>
                  </td>
                  <td className="num">{c.applications.toLocaleString()}</td>
                  <td className="num">{c.allowance_rate}%</td>
                  <td className="num">{c.median_months_to_issue}</td>
                  <td className="num">{c.mean_office_actions}</td>
                  <td className="num">{c.restriction_rate}%</td>
                  <td className="num">{c.faa_rate}%</td>
                  <td className="num">
                    {(c.flags.a1.flagged + c.flags.b1.flagged + c.flags.b2.flagged).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <h2>How to read this</h2>
      <div className="callout">
        <strong>{meta.cohort}.</strong> Source: {meta.source}.
        <ul>
          {meta.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </div>
    </>
  );
}

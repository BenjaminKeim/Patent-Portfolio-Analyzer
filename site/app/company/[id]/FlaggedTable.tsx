"use client";

import { useEffect, useMemo, useState } from "react";
import type { FlaggedRow } from "@/lib/types";
import { TECH_CENTER_LABELS } from "@/lib/types";

const PAGE = 100;

/** Flagged lists run to ~12,700 rows for the largest filers. They are fetched at runtime
 *  rather than passed down from the server component: anything a server component reads
 *  gets inlined into the prerendered HTML and three RSC payload files, which turned a
 *  1.7 MB list into ~7 MB of build output per company. Fetching keeps pages small and
 *  only downloads the list when someone actually opens the page. */
export default function FlaggedTable({
  companyId,
  expected,
}: {
  companyId: string;
  expected: number;
}) {
  const [rows, setRows] = useState<FlaggedRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rule, setRule] = useState<"ALL" | "A1" | "B1" | "B2">("ALL");
  const [page, setPage] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetch(`/data/flagged/${companyId}.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: FlaggedRow[]) => {
        if (!cancelled) setRows(d);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [companyId]);

  const counts = useMemo(() => {
    const c = { A1: 0, B1: 0, B2: 0 };
    for (const r of rows ?? []) c[r.rule]++;
    return c;
  }, [rows]);

  const filtered = useMemo(
    () => (rule === "ALL" ? rows ?? [] : (rows ?? []).filter((r) => r.rule === rule)),
    [rows, rule]
  );

  const csvHref = useMemo(() => {
    if (!filtered.length) return undefined;
    const head = "application,rule,filed,patent,issued,tech_center,office_actions\n";
    const body = filtered
      .map((r) =>
        [r.application, r.rule, r.filed, r.patent ?? "", r.issued ?? "", r.tech_center, r.office_actions].join(",")
      )
      .join("\n");
    return "data:text/csv;charset=utf-8," + encodeURIComponent(head + body);
  }, [filtered]);

  if (error) {
    return (
      <div className="card">
        <p className="muted small" style={{ margin: 0 }}>
          Could not load the flagged list ({error}).
        </p>
      </div>
    );
  }

  if (rows === null) {
    return (
      <div className="card">
        <p className="muted small" style={{ margin: 0 }}>
          Loading {expected.toLocaleString()} flagged applications&hellip;
        </p>
      </div>
    );
  }

  const pageRows = filtered.slice(page * PAGE, page * PAGE + PAGE);
  const pages = Math.ceil(filtered.length / PAGE);

  function pick(r: typeof rule) {
    setRule(r);
    setPage(0);
  }

  return (
    <div className="card" style={{ padding: 0 }}>
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          flexWrap: "wrap",
          padding: "12px 16px",
          borderBottom: "1px solid var(--border)",
        }}
      >
        {(["ALL", "A1", "B1", "B2"] as const).map((r) => (
          <button
            key={r}
            onClick={() => pick(r)}
            style={{
              font: "inherit",
              fontSize: 13,
              padding: "4px 11px",
              borderRadius: 99,
              cursor: "pointer",
              border: "1px solid " + (rule === r ? "var(--accent)" : "var(--border-strong)"),
              background: rule === r ? "var(--accent-soft)" : "transparent",
              color: rule === r ? "var(--accent)" : "var(--text-muted)",
            }}
          >
            {r === "ALL"
              ? `All (${rows.length.toLocaleString()})`
              : `${r} (${counts[r].toLocaleString()})`}
          </button>
        ))}
        <span style={{ flex: 1 }} />
        {csvHref && (
          <a className="small" href={csvHref} download={`flagged-${companyId}-${rule.toLowerCase()}.csv`}>
            Download CSV
          </a>
        )}
      </div>

      <div className="table-scroll" style={{ maxHeight: 560 }}>
        <table>
          <thead>
            <tr>
              <th>Application</th>
              <th>Rule</th>
              <th>Filed</th>
              <th>Patent</th>
              <th>Issued</th>
              <th>Technology</th>
              <th className="num">OAs</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r, i) => (
              <tr key={`${r.application}-${r.rule}-${i}`}>
                <td className="mono">
                  <a
                    href={`https://patentcenter.uspto.gov/applications/${r.application}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {r.application}
                  </a>
                </td>
                <td>
                  <span className="badge flag">{r.rule}</span>
                </td>
                <td className="mono">{r.filed}</td>
                <td className="mono">{r.patent ?? "—"}</td>
                <td className="mono">{r.issued ?? "—"}</td>
                <td className="small">
                  {TECH_CENTER_LABELS[r.tech_center] ?? r.tech_center}
                </td>
                <td className="num">{r.office_actions}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div
          style={{
            display: "flex",
            gap: 12,
            alignItems: "center",
            padding: "10px 16px",
            borderTop: "1px solid var(--border)",
            fontSize: 13,
          }}
        >
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            style={{ font: "inherit", cursor: page === 0 ? "default" : "pointer" }}
          >
            Previous
          </button>
          <span className="muted">
            {(page * PAGE + 1).toLocaleString()}&ndash;
            {Math.min((page + 1) * PAGE, filtered.length).toLocaleString()} of{" "}
            {filtered.length.toLocaleString()}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
            disabled={page >= pages - 1}
            style={{ font: "inherit", cursor: page >= pages - 1 ? "default" : "pointer" }}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

/* Server-only data access. Reads the exported JSON from public/data at build time.
   Never import this from a "use client" component - it pulls in node:fs.
   Shared types and labels live in lib/types.ts. */

import fs from "node:fs";
import path from "node:path";
import type { CompanyDetail, CompanySummary, Meta, Stats } from "./types";

const DATA_DIR = path.join(process.cwd(), "public", "data");

export function getCompanies(): CompanySummary[] {
  const raw = fs.readFileSync(path.join(DATA_DIR, "companies.json"), "utf-8");
  return JSON.parse(raw) as CompanySummary[];
}

export function getCompany(id: string): CompanyDetail {
  const raw = fs.readFileSync(path.join(DATA_DIR, "company", `${id}.json`), "utf-8");
  return JSON.parse(raw) as CompanyDetail;
}

export function getMeta(): Meta {
  const raw = fs.readFileSync(path.join(DATA_DIR, "meta.json"), "utf-8");
  return JSON.parse(raw) as Meta;
}

export function getStats(): Stats {
  const raw = fs.readFileSync(path.join(DATA_DIR, "stats.json"), "utf-8");
  return (JSON.parse(raw) as Stats[])[0];
}

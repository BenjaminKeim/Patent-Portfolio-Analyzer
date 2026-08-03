import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Patent Portfolio Analyzer",
  description:
    "Prosecution-level analysis of US patent portfolios, built from USPTO public data.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="site">
          <div className="wrap">
            <div className="title">
              <Link href="/" style={{ color: "inherit" }}>
                Patent Portfolio Analyzer
              </Link>
            </div>
            <div className="sub">
              Prosecution analytics for 20 US patent filers &middot; filing years 2013&ndash;2019
            </div>
          </div>
        </header>
        <main className="wrap">{children}</main>
        <div className="wrap">
          <footer className="site">
            Built from the USPTO Patent Examination Research Dataset (PatEx), 2022 release.
            Public-domain US government data. Flags identify unexercised options, not errors.
          </footer>
        </div>
      </body>
    </html>
  );
}

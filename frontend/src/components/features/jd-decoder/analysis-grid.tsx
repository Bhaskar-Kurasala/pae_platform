"use client";

import type { JdAnalysisPayload, CultureSeverity } from "@/lib/hooks/use-readiness";
import { readinessCopy } from "@/lib/copy/readiness";

interface AnalysisGridProps {
  analysis: JdAnalysisPayload;
}

const SEVERITY_COLOR: Record<CultureSeverity, string> = {
  info: "var(--ink-2)",
  watch: "var(--gold-2)",
  warn: "#c14a3f",
};

/**
 * Three-column structured analysis: must-haves / wishlist / culture.
 * Filler flags surface above the three columns as an educational
 * banner. Inflated-wishlist gets its own honest call-out.
 */
export function AnalysisGrid({ analysis }: AnalysisGridProps) {
  const c = readinessCopy.jd;
  return (
    <div className="jd-analysis-grid" style={{ display: "grid", gap: 16 }}>
      {/* Header — role + seniority read */}
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div
          style={{
            fontSize: 12,
            color: "var(--ink-2)",
            textTransform: "uppercase",
            letterSpacing: 1.2,
          }}
        >
          {c.seniorityHeader}
        </div>
        <div
          style={{
            fontFamily: "var(--serif, 'Fraunces', Georgia, serif)",
            fontSize: 22,
            color: "var(--ink)",
          }}
        >
          {analysis.role}
          {analysis.company ? ` · ${analysis.company}` : ""}
        </div>
        {analysis.seniority_read && (
          <div style={{ color: "var(--ink-2)", fontSize: 14 }}>
            {analysis.seniority_read}
          </div>
        )}
      </header>

      {analysis.wishlist_inflated && (
        <div
          className="jd-inflated-flag"
          role="status"
          style={{
            background: "var(--gold-soft)",
            border: "1px solid var(--gold)",
            borderRadius: 8,
            padding: "10px 14px",
            color: "var(--ink)",
            fontSize: 14,
          }}
        >
          ⚠ {c.inflatedWishlistFlag}
        </div>
      )}

      {/* Filler flags — educational moment */}
      {analysis.filler_flags.length > 0 && (
        <section
          aria-labelledby="jd-filler-heading"
          style={{
            background: "var(--forest-soft)",
            borderRadius: 10,
            padding: "12px 16px",
          }}
        >
          <h4
            id="jd-filler-heading"
            style={{
              margin: 0,
              fontFamily: "var(--serif, 'Fraunces', Georgia, serif)",
              fontSize: 16,
              color: "var(--forest)",
            }}
          >
            {c.sectionFiller}
          </h4>
          <p
            style={{
              margin: "4px 0 8px",
              color: "var(--ink-2)",
              fontSize: 13,
            }}
          >
            {c.sectionFillerBlurb}
          </p>
          <dl style={{ margin: 0, display: "grid", gap: 6 }}>
            {analysis.filler_flags.map((f) => (
              <div key={f.phrase} style={{ display: "grid", gap: 2 }}>
                <dt
                  style={{
                    fontWeight: 600,
                    color: "var(--ink)",
                    fontSize: 14,
                  }}
                >
                  &ldquo;{f.phrase}&rdquo;
                </dt>
                <dd style={{ margin: 0, color: "var(--ink-2)", fontSize: 13 }}>
                  {f.meaning}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {/* Three-column layout */}
      <div
        className="jd-cols"
        style={{
          display: "grid",
          gap: 16,
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        }}
      >
        <Column
          title={c.sectionMustHaves}
          blurb={c.sectionMustHavesBlurb}
          items={analysis.must_haves}
          tone="must"
        />
        <Column
          title={c.sectionWishlist}
          blurb={c.sectionWishlistBlurb}
          items={analysis.wishlist}
          tone="nice"
        />
        <CultureColumn
          title={c.sectionCulture}
          blurb={c.sectionCultureBlurb}
          signals={analysis.culture_signals}
        />
      </div>
    </div>
  );
}

function Column({
  title,
  blurb,
  items,
  tone,
}: {
  title: string;
  blurb: string;
  items: string[];
  tone: "must" | "nice";
}) {
  return (
    <section
      style={{
        border: "1px solid var(--forest-soft)",
        borderRadius: 10,
        padding: "12px 14px",
        background: tone === "must" ? "var(--forest-soft)" : "transparent",
      }}
    >
      <h4
        style={{
          margin: 0,
          fontFamily: "var(--serif, 'Fraunces', Georgia, serif)",
          fontSize: 16,
          color: "var(--forest)",
        }}
      >
        {title}
      </h4>
      <p style={{ margin: "4px 0 8px", color: "var(--ink-2)", fontSize: 12 }}>
        {blurb}
      </p>
      {items.length === 0 ? (
        <p style={{ margin: 0, color: "var(--ink-2)", fontStyle: "italic" }}>
          (none surfaced)
        </p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 18, color: "var(--ink)" }}>
          {items.map((item) => (
            <li key={item} style={{ fontSize: 14, marginBottom: 4 }}>
              {item}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function CultureColumn({
  title,
  blurb,
  signals,
}: {
  title: string;
  blurb: string;
  signals: JdAnalysisPayload["culture_signals"];
}) {
  return (
    <section
      style={{
        border: "1px solid var(--forest-soft)",
        borderRadius: 10,
        padding: "12px 14px",
      }}
    >
      <h4
        style={{
          margin: 0,
          fontFamily: "var(--serif, 'Fraunces', Georgia, serif)",
          fontSize: 16,
          color: "var(--forest)",
        }}
      >
        {title}
      </h4>
      <p style={{ margin: "4px 0 8px", color: "var(--ink-2)", fontSize: 12 }}>
        {blurb}
      </p>
      {signals.length === 0 ? (
        <p style={{ margin: 0, color: "var(--ink-2)", fontStyle: "italic" }}>
          (no flags)
        </p>
      ) : (
        <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
          {signals.map((sig) => (
            <li
              key={sig.pattern}
              style={{
                marginBottom: 8,
                paddingLeft: 8,
                borderLeft: `3px solid ${SEVERITY_COLOR[sig.severity]}`,
              }}
            >
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: "var(--ink)",
                  textTransform: "capitalize",
                }}
              >
                {sig.pattern}
              </div>
              <div style={{ fontSize: 12, color: "var(--ink-2)", marginTop: 2 }}>
                {sig.note}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

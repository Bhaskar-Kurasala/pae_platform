"use client";

import Link from "next/link";

import type { EvidenceChip, VerdictPayload } from "@/lib/hooks/use-readiness";

import { diagnosticAnalytics } from "./analytics";

interface VerdictCardProps {
  sessionId: string;
  verdict: VerdictPayload;
  /** Optional click handler the parent uses to fire the north-star
   * beacon (commit 10). Always invoked alongside the analytics event. */
  onNextActionClick?: (sessionId: string) => void;
}

/**
 * The page's emotional anchor at the closing moment.
 *
 * Layout:
 *   - Eyebrow: small kicker ("Verdict")
 *   - Headline: Fraunces serif, generous, evidence-grounded sentence
 *   - Evidence: 3-5 chips, mixed strengths and gaps
 *   - One primary CTA — single most leveraged action, no competing
 *     buttons. The "what else?" affordance is intentionally NOT here
 *     by default; if the verdict is wrong for this student, the action
 *     is to return to the conversation, not pile on alternatives.
 */
export function VerdictCard({
  sessionId,
  verdict,
  onNextActionClick,
}: VerdictCardProps) {
  const onClick = () => {
    diagnosticAnalytics.nextActionClicked({
      session_id: sessionId,
      action_label: verdict.next_action.label,
      intent: verdict.next_action.intent,
    });
    onNextActionClick?.(sessionId);
  };

  return (
    <article
      className="diagnostic-verdict-card"
      aria-label="Diagnostic verdict"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 20,
        padding: "28px 28px 24px",
        borderRadius: 14,
        background: "var(--forest-soft)",
        border: "1px solid var(--forest-soft)",
        // Generous internal whitespace per spec — calm, not cramped.
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div
          style={{
            fontSize: 11,
            color: "var(--forest)",
            textTransform: "uppercase",
            letterSpacing: 1.4,
            fontWeight: 600,
          }}
        >
          Verdict
        </div>
        <h2
          style={{
            margin: 0,
            fontFamily: "var(--serif, 'Fraunces', Georgia, serif)",
            fontSize: 28,
            lineHeight: 1.25,
            color: "var(--ink)",
            // Italic via Fraunces optical-italic axis is a v8 page rhythm.
            fontWeight: 500,
          }}
        >
          {verdict.headline}
        </h2>
      </header>

      {verdict.evidence.length > 0 && (
        <ul
          aria-label="Supporting evidence"
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
          }}
        >
          {verdict.evidence.map((chip, idx) => (
            <EvidencePill key={`${chip.evidence_id}-${idx}`} chip={chip} />
          ))}
        </ul>
      )}

      <footer
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          marginTop: 4,
          flexWrap: "wrap",
        }}
      >
        <Link
          href={verdict.next_action.route}
          onClick={onClick}
          className="btn primary rn-btn"
          style={{
            display: "inline-block",
            padding: "12px 22px",
            borderRadius: 10,
            background: "var(--forest)",
            color: "var(--forest-soft)",
            textDecoration: "none",
            fontWeight: 600,
            fontSize: 15,
          }}
        >
          {verdict.next_action.label}
        </Link>
      </footer>
    </article>
  );
}

function EvidencePill({ chip }: { chip: EvidenceChip }) {
  const tone =
    chip.kind === "gap"
      ? { border: "#c14a3f", icon: "⚠" }
      : chip.kind === "strength"
        ? { border: "var(--forest-3)", icon: "✓" }
        : { border: "var(--ink-2)", icon: "·" };
  const inner = (
    <li
      className="match-card"
      title={`evidence_id: ${chip.evidence_id}`}
      style={{
        padding: "6px 12px",
        borderRadius: 18,
        background: "var(--bg, #fff)",
        border: `1px solid ${tone.border}`,
        fontSize: 13,
        color: "var(--ink)",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
      }}
    >
      <span aria-hidden="true">{tone.icon}</span>
      <span>{chip.text}</span>
    </li>
  );
  if (chip.source_url) {
    return (
      <Link
        href={chip.source_url}
        style={{ textDecoration: "none" }}
        aria-label={`${chip.text} (open source)`}
      >
        {inner}
      </Link>
    );
  }
  return inner;
}

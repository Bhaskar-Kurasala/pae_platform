"use client";

import { useState } from "react";
import Link from "next/link";

import { readinessCopy } from "@/lib/copy/readiness";
import {
  type DecodeJdResponse,
  useDecodeJd,
} from "@/lib/hooks/use-readiness";

import { jdDecoderAnalytics } from "./analytics";
import { AnalysisGrid } from "./analysis-grid";
import { MatchScoreGauge } from "./match-score-gauge";

interface DecoderCardProps {
  /** When the diagnostic invokes the decoder inline, it passes a
   * pre-filled JD and skips the paste step. */
  initialJdText?: string;
  /** Renders the card in a tighter container without the standalone
   * heading — used by the diagnostic embedding (commit 9). */
  embedded?: boolean;
  /** Called with a short summary string after a successful decode.
   * Used by the diagnostic ↔ decoder bundle to fold the result back
   * into the conversation transcript. */
  onDecoded?: (summary: string) => void;
}

export function DecoderCard({
  initialJdText,
  embedded = false,
  onDecoded,
}: DecoderCardProps) {
  const [jdText, setJdText] = useState(initialJdText ?? "");
  const decode = useDecodeJd();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const c = readinessCopy.jd;
  const result = decode.data as DecodeJdResponse | undefined;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    const trimmed = jdText.trim();
    if (trimmed.length < 60) {
      setSubmitError(c.tooShortError);
      return;
    }
    try {
      const data = await decode.mutateAsync({ jd_text: trimmed });
      jdDecoderAnalytics.decoded({
        jd_analysis_id: data.jd_analysis_id,
        cached: data.cached,
        score: data.match_score.score,
      });
      jdDecoderAnalytics.matchScoreCalculated({
        jd_analysis_id: data.jd_analysis_id,
        score: data.match_score.score,
      });
      if (onDecoded) {
        const role = data.analysis.role || "this role";
        const summary =
          data.match_score.score === null
            ? `Decoded the JD for ${role}. ${data.match_score.headline}`
            : `Decoded the JD for ${role}. Match: ${data.match_score.score}/100. ${data.match_score.headline}`;
        onDecoded(summary);
      }
    } catch (err) {
      setSubmitError(c.error);
      console.error("[jd-decoder] decode failed", err);
    }
  };

  return (
    <article
      className="jd-decoder-card"
      style={{
        display: "grid",
        gap: 16,
        padding: embedded ? 0 : 20,
        borderRadius: 12,
        border: embedded ? "none" : "1px solid var(--forest-soft)",
        background: "transparent",
      }}
    >
      {!embedded && (
        <header>
          <div
            style={{
              fontSize: 12,
              color: "var(--ink-2)",
              textTransform: "uppercase",
              letterSpacing: 1.2,
            }}
          >
            JD Match
          </div>
          <h3
            style={{
              margin: "4px 0 6px",
              fontFamily: "var(--serif, 'Fraunces', Georgia, serif)",
              fontSize: 24,
              color: "var(--ink)",
            }}
          >
            {c.cardTitle}
          </h3>
          <p style={{ margin: 0, color: "var(--ink-2)" }}>{c.cardBlurb}</p>
        </header>
      )}

      <form onSubmit={onSubmit} style={{ display: "grid", gap: 8 }}>
        <label
          htmlFor="jd-decoder-text"
          style={{
            fontSize: 12,
            color: "var(--ink-2)",
            textTransform: "uppercase",
            letterSpacing: 1.2,
          }}
        >
          {c.pasteLabel}
        </label>
        <textarea
          id="jd-decoder-text"
          value={jdText}
          onChange={(e) => setJdText(e.target.value)}
          placeholder={c.pastePlaceholder}
          rows={8}
          style={{
            fontFamily: "var(--font-inter, Inter, system-ui)",
            fontSize: 14,
            padding: "10px 12px",
            border: "1px solid var(--forest-soft)",
            borderRadius: 8,
            background: "var(--bg, #fff)",
            color: "var(--ink)",
            resize: "vertical",
            minHeight: 160,
          }}
          aria-describedby={submitError ? "jd-decoder-error" : undefined}
          required
        />
        {submitError && (
          <div
            id="jd-decoder-error"
            role="alert"
            style={{ color: "#c14a3f", fontSize: 13 }}
          >
            {submitError}
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button
            type="submit"
            className="btn primary"
            disabled={decode.isPending}
          >
            {decode.isPending ? c.submitPendingLabel : c.submitLabel}
          </button>
        </div>
      </form>

      {result && (
        <div
          className="jd-decoder-result"
          style={{ display: "grid", gap: 24 }}
        >
          <div
            style={{
              display: "grid",
              gap: 16,
              gridTemplateColumns: "1fr",
              alignItems: "start",
            }}
          >
            <AnalysisGrid analysis={result.analysis} />
          </div>

          <section
            aria-label="Match score"
            style={{
              display: "grid",
              gap: 12,
              padding: 16,
              borderRadius: 12,
              border: "1px solid var(--forest-soft)",
              background: "var(--forest-soft)",
            }}
          >
            <MatchScoreGauge
              score={result.match_score.score}
              headline={result.match_score.headline}
            />
            {result.match_score.evidence.length > 0 && (
              <ul
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 8,
                  margin: 0,
                  padding: 0,
                  listStyle: "none",
                }}
              >
                {result.match_score.evidence.map((chip, idx) => (
                  <li
                    key={`${chip.evidence_id}-${idx}`}
                    className="match-card"
                    style={{
                      padding: "6px 10px",
                      borderRadius: 16,
                      background: "var(--bg, #fff)",
                      border: `1px solid ${
                        chip.kind === "gap"
                          ? "#c14a3f"
                          : chip.kind === "strength"
                            ? "var(--forest-3)"
                            : "var(--ink-2)"
                      }`,
                      fontSize: 12,
                      color: "var(--ink)",
                    }}
                    title={`evidence_id: ${chip.evidence_id}`}
                  >
                    {chip.kind === "strength" ? "✓ " : chip.kind === "gap" ? "⚠ " : "· "}
                    {chip.text}
                  </li>
                ))}
              </ul>
            )}
            <NextActionButton
              jdAnalysisId={result.jd_analysis_id}
              nextAction={result.match_score.next_action}
            />
          </section>
        </div>
      )}
    </article>
  );
}

function NextActionButton({
  jdAnalysisId,
  nextAction,
}: {
  jdAnalysisId: string;
  nextAction: DecodeJdResponse["match_score"]["next_action"];
}) {
  return (
    <Link
      href={nextAction.route}
      className="btn primary rn-btn"
      onClick={() =>
        jdDecoderAnalytics.nextActionClicked({
          jd_analysis_id: jdAnalysisId,
          action_label: nextAction.label,
          intent: nextAction.intent,
        })
      }
      style={{
        textAlign: "center",
        textDecoration: "none",
        fontWeight: 600,
        padding: "10px 14px",
        borderRadius: 8,
        background: "var(--forest)",
        color: "var(--forest-soft)",
      }}
    >
      {nextAction.label}
    </Link>
  );
}

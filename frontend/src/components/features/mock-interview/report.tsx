"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type MockSessionReport,
  useShareMockSession,
} from "@/lib/hooks/use-mock-interview";
import { mockAnalytics } from "./analytics";
import { COPY } from "./copy";

interface ReportProps {
  report: MockSessionReport;
  /** When true, hides the action buttons (used on the public share page). */
  publicView?: boolean;
}

export function Report({ report, publicView = false }: ReportProps) {
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [shareToken, setShareToken] = useState<string | null>(report.share_token);
  const [shareCopied, setShareCopied] = useState(false);
  const shareMutation = useShareMockSession();

  useEffect(() => {
    mockAnalytics.reportViewed({
      session_id: report.session_id,
      verdict: report.verdict,
    });
  }, [report.session_id, report.verdict]);

  const verdictLabel =
    COPY.report.verdictLabels[report.verdict] || report.verdict;

  const verdictTone = useMemo(() => {
    switch (report.verdict) {
      case "would_pass":
        return "good" as const;
      case "borderline":
        return "warn" as const;
      case "would_not_pass":
        return "low" as const;
      default:
        return "warn" as const;
    }
  }, [report.verdict]);

  const onShare = useCallback(async () => {
    if (publicView) return;
    if (shareToken) {
      const url = `${window.location.origin}/mock-report/${shareToken}`;
      try {
        await navigator.clipboard.writeText(url);
        setShareCopied(true);
        window.setTimeout(() => setShareCopied(false), 2200);
      } catch {
        /* ignore */
      }
      return;
    }
    try {
      const result = await shareMutation.mutateAsync(report.session_id);
      setShareToken(result.share_token);
      const url = `${window.location.origin}${result.public_url}`;
      try {
        await navigator.clipboard.writeText(url);
        setShareCopied(true);
        window.setTimeout(() => setShareCopied(false), 2200);
      } catch {
        /* ignore */
      }
      mockAnalytics.reportShared({ session_id: report.session_id });
    } catch {
      /* ignore */
    }
  }, [publicView, report.session_id, shareMutation, shareToken]);

  const onNextActionClick = useCallback(() => {
    mockAnalytics.nextActionClicked({
      session_id: report.session_id,
      action_label: report.next_action.label,
    });
  }, [report.next_action.label, report.session_id]);

  const rubricEntries = Object.entries(report.rubric_summary || {});
  const showRubricNumbers = !report.needs_human_review && rubricEntries.length > 0;

  return (
    <div style={{ display: "grid", gap: 18 }}>
      {/* Headline + verdict */}
      <section className="match-card" style={{ padding: 22 }}>
        <div className="k">{COPY.report.headlineEyebrow}</div>
        <div className="big" style={{ marginBottom: 12 }}>
          {report.headline}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className={`rd-badge ${verdictTone}`}>{verdictLabel}</span>
          {report.needs_human_review ? (
            <span
              style={{
                fontSize: 12,
                color: "var(--muted)",
                fontStyle: "italic",
              }}
            >
              Confidence: {(report.analyst_confidence * 100).toFixed(0)}%
            </span>
          ) : null}
        </div>

        {report.needs_human_review ? (
          <div
            style={{
              marginTop: 14,
              padding: "10px 14px",
              borderRadius: 10,
              background: "var(--gold-soft)",
              color: "#8d621b",
              fontSize: 13.5,
              lineHeight: 1.55,
            }}
          >
            {COPY.report.confidenceLowBanner}
          </div>
        ) : null}
      </section>

      <div className="rd-2col">
        {/* Rubric summary */}
        <section className="match-card" style={{ padding: 22 }}>
          <div className="k">{COPY.report.rubricEyebrow}</div>
          <div className="big" style={{ marginBottom: 14 }}>
            How each criterion landed
          </div>
          {showRubricNumbers ? (
            <div className="rd-list">
              {rubricEntries.map(([name, score]) => (
                <RubricRow key={name} name={name} score={score} />
              ))}
            </div>
          ) : (
            <div
              style={{
                fontSize: 13.5,
                color: "var(--muted)",
                lineHeight: 1.55,
              }}
            >
              Per-criterion numeric scores aren&rsquo;t shown — confidence was
              below threshold. The qualitative feedback below is still
              actionable.
            </div>
          )}
        </section>

        {/* Patterns */}
        <section className="match-card" style={{ padding: 22 }}>
          <div className="k">{COPY.report.patternsEyebrow}</div>
          <div className="big" style={{ marginBottom: 12 }}>
            What the mic picked up
          </div>
          <PatternsBlock patterns={report.patterns} />
        </section>
      </div>

      <div className="rd-2col">
        {/* Strengths */}
        <section className="match-card" style={{ padding: 22 }}>
          <div className="k">{COPY.report.strengthsEyebrow}</div>
          <div className="big" style={{ marginBottom: 12 }}>
            Worth keeping
          </div>
          <ul style={{ paddingLeft: 18, lineHeight: 1.65 }}>
            {(report.strengths || []).length > 0 ? (
              report.strengths.map((s, i) => <li key={i}>{s}</li>)
            ) : (
              <li style={{ color: "var(--muted)" }}>
                Nothing surfaced this round. Often the case in early sessions —
                the next mock will give the analyst more to work with.
              </li>
            )}
          </ul>
        </section>

        {/* Weaknesses */}
        <section className="match-card" style={{ padding: 22 }}>
          <div className="k">{COPY.report.weaknessesEyebrow}</div>
          <div className="big" style={{ marginBottom: 12 }}>
            Where it didn&rsquo;t land
          </div>
          <ul style={{ paddingLeft: 18, lineHeight: 1.65 }}>
            {(report.weaknesses || []).length > 0 ? (
              report.weaknesses.map((w, i) => <li key={i}>{w}</li>)
            ) : (
              <li style={{ color: "var(--muted)" }}>
                Nothing flagged below threshold.
              </li>
            )}
          </ul>
        </section>
      </div>

      {/* Next action */}
      <section className="match-card" style={{ padding: 22 }}>
        <div className="k">{COPY.report.nextActionEyebrow}</div>
        <div className="big" style={{ marginBottom: 12 }}>
          {report.next_action.label}
        </div>
        <div
          style={{ fontSize: 14, color: "var(--ink)", lineHeight: 1.6 }}
        >
          {report.next_action.detail}
        </div>
        {report.next_action.target_url ? (
          <div className="rd-footer" style={{ marginTop: 16 }}>
            <a
              className="btn primary"
              href={report.next_action.target_url}
              onClick={onNextActionClick}
            >
              Open
            </a>
          </div>
        ) : null}
      </section>

      {/* Transcript replay */}
      <section className="match-card" style={{ padding: 22 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div>
            <div className="k">{COPY.report.transcriptEyebrow}</div>
            <div className="body" style={{ marginTop: 4 }}>
              {report.transcript.length} turns
            </div>
          </div>
          <button
            type="button"
            className="btn ghost"
            onClick={() => setTranscriptOpen((v) => !v)}
          >
            {transcriptOpen
              ? COPY.report.transcriptExpanded
              : COPY.report.transcriptCollapsed}
          </button>
        </div>

        {transcriptOpen ? (
          <div style={{ display: "grid", gap: 8, marginTop: 16 }}>
            {report.transcript.map((t, i) => (
              <div
                key={i}
                style={{
                  background:
                    t.role === "interviewer" ? "#fff" : "var(--forest-soft)",
                  border: "1px solid var(--line)",
                  borderRadius: 10,
                  padding: "10px 12px",
                  fontSize: 13.5,
                  lineHeight: 1.55,
                }}
              >
                <div
                  style={{
                    fontSize: 10,
                    letterSpacing: ".12em",
                    textTransform: "uppercase",
                    color: "var(--muted)",
                    fontWeight: 700,
                    marginBottom: 4,
                  }}
                >
                  {t.role === "interviewer" ? "Interviewer" : "You"} ·{" "}
                  {new Date(t.at).toLocaleTimeString()}
                </div>
                <div style={{ whiteSpace: "pre-wrap" }}>{t.text}</div>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      {!publicView ? (
        <div className="rd-footer" style={{ marginTop: 0 }}>
          <button type="button" className="btn secondary" onClick={onShare}>
            {shareCopied
              ? COPY.report.shareCopied
              : COPY.report.shareButton}
          </button>
          <span
            style={{
              alignSelf: "center",
              fontSize: 12,
              color: "var(--muted)",
            }}
          >
            Total cost: ₹{report.total_cost_inr.toFixed(2)}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function RubricRow({ name, score }: { name: string; score: number }) {
  const tone =
    score >= 7.5 ? "" : score >= 5.5 ? " warn" : " low";
  return (
    <div className="rd-metric">
      <div>
        <b style={{ textTransform: "capitalize" }}>{name.replace(/_/g, " ")}</b>
      </div>
      <strong>{score.toFixed(1)}</strong>
      <div className="rd-bar">
        <div
          className={`rd-bar-fill${tone}`}
          style={{ width: `${Math.min(100, (score / 10) * 100)}%` }}
        />
      </div>
    </div>
  );
}

function PatternsBlock({
  patterns,
}: {
  patterns: MockSessionReport["patterns"];
}) {
  return (
    <div className="rd-list">
      <PatternRow
        label="Filler-word rate"
        value={`${patterns.filler_word_rate} / 100 words`}
        tone={patterns.filler_word_rate < 3 ? "good" : patterns.filler_word_rate < 6 ? "warn" : "low"}
      />
      <PatternRow
        label="Avg time to first word"
        value={
          patterns.avg_time_to_first_word_ms
            ? `${(patterns.avg_time_to_first_word_ms / 1000).toFixed(1)}s`
            : "—"
        }
      />
      <PatternRow
        label="Avg words per answer"
        value={`${patterns.avg_words_per_answer}`}
        tone={
          patterns.avg_words_per_answer >= 60 &&
          patterns.avg_words_per_answer <= 180
            ? "good"
            : "warn"
        }
      />
      <PatternRow
        label="Confidence language"
        value={`${patterns.confidence_language_score}/10`}
        tone={
          patterns.confidence_language_score >= 7
            ? "good"
            : patterns.confidence_language_score >= 5
              ? "warn"
              : "low"
        }
      />
    </div>
  );
}

function PatternRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "warn" | "low";
}) {
  return (
    <div className="rd-li">
      <div>
        <b>{label}</b>
      </div>
      {tone ? (
        <span className={`rd-badge ${tone}`}>{value}</span>
      ) : (
        <span style={{ fontSize: 13, color: "var(--muted)" }}>{value}</span>
      )}
    </div>
  );
}

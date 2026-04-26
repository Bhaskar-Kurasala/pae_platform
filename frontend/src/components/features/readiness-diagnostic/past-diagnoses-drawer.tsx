"use client";

import { useState } from "react";

import { readinessCopy } from "@/lib/copy/readiness";
import { usePastDiagnoses } from "@/lib/hooks/use-readiness";

/**
 * Past diagnoses surface. Lazy: doesn't fetch until the link is opened.
 * Renders a small list with headline + next-action label + status
 * badge (clicked / completed-within-24h).
 */
export function PastDiagnosesDrawer() {
  const [open, setOpen] = useState(false);
  const { data, isLoading, isError } = usePastDiagnoses(open);
  const items = data?.items ?? [];

  return (
    <div
      className="diagnostic-past-drawer"
      style={{ marginTop: 8, fontSize: 13 }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          background: "transparent",
          border: "none",
          color: "var(--forest)",
          padding: "4px 0",
          cursor: "pointer",
          textDecoration: "underline",
          fontSize: 13,
          fontWeight: 500,
        }}
      >
        {readinessCopy.diagnostic.pastDiagnosesLink}{" "}
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div
          style={{
            marginTop: 10,
            padding: 14,
            borderRadius: 10,
            border: "1px solid var(--forest-soft)",
            background: "var(--bg, #fff)",
          }}
        >
          {isLoading && (
            <div style={{ color: "var(--ink-2)" }}>Loading…</div>
          )}
          {isError && (
            <div style={{ color: "#c14a3f" }}>
              Couldn&rsquo;t load past diagnoses.
            </div>
          )}
          {!isLoading && !isError && items.length === 0 && (
            <div style={{ color: "var(--ink-2)" }}>
              No past diagnoses yet.
            </div>
          )}
          {items.length > 0 && (
            <ul
              style={{
                listStyle: "none",
                margin: 0,
                padding: 0,
                display: "flex",
                flexDirection: "column",
                gap: 10,
              }}
            >
              {items.map((d) => (
                <li
                  key={d.session_id}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 4,
                    paddingBottom: 8,
                    borderBottom: "1px solid var(--forest-soft)",
                  }}
                >
                  <div style={{ color: "var(--ink-2)", fontSize: 11 }}>
                    {formatDate(d.started_at)}
                  </div>
                  <div
                    style={{
                      fontFamily:
                        "var(--serif, 'Fraunces', Georgia, serif)",
                      color: "var(--ink)",
                      fontSize: 14,
                    }}
                  >
                    {d.headline ?? "(no verdict — session abandoned)"}
                  </div>
                  {d.next_action_label && (
                    <div
                      style={{
                        display: "flex",
                        gap: 6,
                        alignItems: "center",
                        fontSize: 12,
                        color: "var(--ink-2)",
                      }}
                    >
                      <span>Next action:</span>
                      <span style={{ color: "var(--ink)" }}>
                        {d.next_action_label}
                      </span>
                      <StatusBadge
                        clickedAt={d.next_action_clicked_at}
                        completedAt={d.next_action_completed_at}
                      />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function StatusBadge({
  clickedAt,
  completedAt,
}: {
  clickedAt: string | null;
  completedAt: string | null;
}) {
  if (completedAt) {
    return (
      <span
        style={{
          padding: "1px 8px",
          borderRadius: 10,
          background: "var(--forest-3)",
          color: "var(--forest-soft)",
          fontSize: 11,
          fontWeight: 600,
        }}
      >
        Completed
      </span>
    );
  }
  if (clickedAt) {
    return (
      <span
        style={{
          padding: "1px 8px",
          borderRadius: 10,
          background: "var(--gold)",
          color: "var(--gold-soft)",
          fontSize: 11,
          fontWeight: 600,
        }}
      >
        In progress
      </span>
    );
  }
  return null;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

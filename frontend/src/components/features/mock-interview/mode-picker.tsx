"use client";

import type { MockMode } from "@/lib/hooks/use-mock-interview";
import { COPY } from "./copy";

interface ModePickerProps {
  selected: MockMode | null;
  onSelect: (mode: MockMode) => void;
}

const MODE_ORDER: MockMode[] = [
  "technical_conceptual",
  "live_coding",
  "behavioral",
  "system_design",
];

export function ModePicker({ selected, onSelect }: ModePickerProps) {
  return (
    <div>
      <div className="rd-section-k">{COPY.modePicker.eyebrow}</div>
      <div className="rd-section-t">{COPY.modePicker.title}</div>
      <div
        className="rd-section-c"
        style={{ marginBottom: 18 }}
      >
        {COPY.modePicker.blurb}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
          gap: 14,
        }}
      >
        {MODE_ORDER.map((mode) => {
          const cfg =
            COPY.modePicker.modes[
              mode as keyof typeof COPY.modePicker.modes
            ];
          const disabled = "disabled" in cfg && cfg.disabled === true;
          const active = selected === mode;
          return (
            <button
              key={mode}
              type="button"
              disabled={disabled}
              onClick={() => !disabled && onSelect(mode)}
              className="match-card"
              style={{
                textAlign: "left",
                cursor: disabled ? "not-allowed" : "pointer",
                opacity: disabled ? 0.55 : 1,
                outline: active ? "2px solid var(--forest)" : "none",
                outlineOffset: "2px",
                transition: "outline 120ms ease",
              }}
              aria-pressed={active}
            >
              <div className="k">{cfg.timeEstimate}</div>
              <div className="big">{cfg.title}</div>
              <div className="body">{cfg.blurb}</div>
              <div
                style={{
                  marginTop: 12,
                  fontSize: 12,
                  color: "var(--muted)",
                  fontStyle: "italic",
                  lineHeight: 1.5,
                }}
              >
                Example: &ldquo;{cfg.example}&rdquo;
              </div>
              {disabled ? (
                <div
                  style={{
                    marginTop: 10,
                    display: "inline-block",
                    padding: "3px 8px",
                    borderRadius: 999,
                    background: "var(--gold-soft)",
                    color: "#8d621b",
                    fontSize: 10,
                    letterSpacing: ".08em",
                    fontWeight: 700,
                    textTransform: "uppercase",
                  }}
                >
                  Phase 2
                </div>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

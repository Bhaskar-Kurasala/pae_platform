"use client";

import { useState } from "react";
import type { MockLevel, MockMode } from "@/lib/hooks/use-mock-interview";
import { COPY } from "./copy";

export interface PreSessionValues {
  target_role: string;
  level: MockLevel;
  jd_text?: string;
  voice_enabled: boolean;
}

interface PreSessionSetupProps {
  mode: MockMode;
  defaultRole?: string;
  onCancel: () => void;
  onStart: (values: PreSessionValues) => void;
  isStarting: boolean;
  startError?: string | null;
}

const LEVELS: { value: MockLevel; label: string }[] = [
  { value: "junior", label: "Junior — first 2 years" },
  { value: "mid", label: "Mid — 2–6 years" },
  { value: "senior", label: "Senior — 6+ years" },
];

export function PreSessionSetup({
  mode,
  defaultRole = "Junior Python Developer",
  onCancel,
  onStart,
  isStarting,
  startError,
}: PreSessionSetupProps) {
  const [targetRole, setTargetRole] = useState(defaultRole);
  const [level, setLevel] = useState<MockLevel>("junior");
  const [jdText, setJdText] = useState("");
  // Voice defaults: on for Behavioral/Conceptual, off for Live Coding.
  const [voice, setVoice] = useState(
    mode === "behavioral" || mode === "technical_conceptual",
  );

  const canStart = targetRole.trim().length > 0 && !isStarting;

  return (
    <div className="match-card" style={{ padding: 22 }}>
      <div className="k">Setup</div>
      <div className="big">{COPY.preSession.title}</div>

      <div style={{ display: "grid", gap: 16, marginTop: 18 }}>
        <label style={{ display: "block" }}>
          <div
            style={{
              fontSize: 11,
              letterSpacing: ".12em",
              textTransform: "uppercase",
              color: "var(--muted)",
              fontWeight: 700,
              marginBottom: 6,
            }}
          >
            {COPY.preSession.targetRoleLabel}
          </div>
          <input
            type="text"
            value={targetRole}
            onChange={(e) => setTargetRole(e.target.value)}
            placeholder={COPY.preSession.targetRolePlaceholder}
            className="jd-paste"
            style={{ minHeight: 44, padding: "10px 12px" }}
          />
        </label>

        <div>
          <div
            style={{
              fontSize: 11,
              letterSpacing: ".12em",
              textTransform: "uppercase",
              color: "var(--muted)",
              fontWeight: 700,
              marginBottom: 8,
            }}
          >
            {COPY.preSession.levelLabel}
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {LEVELS.map((lvl) => {
              const active = level === lvl.value;
              return (
                <button
                  key={lvl.value}
                  type="button"
                  onClick={() => setLevel(lvl.value)}
                  className="jd-sample-chip"
                  style={{
                    background: active ? "var(--forest)" : undefined,
                    color: active ? "#fff" : undefined,
                    borderColor: active ? "var(--forest)" : undefined,
                  }}
                >
                  {lvl.label}
                </button>
              );
            })}
          </div>
        </div>

        <label style={{ display: "block" }}>
          <div
            style={{
              fontSize: 11,
              letterSpacing: ".12em",
              textTransform: "uppercase",
              color: "var(--muted)",
              fontWeight: 700,
              marginBottom: 6,
            }}
          >
            {COPY.preSession.jdLabel}
          </div>
          <textarea
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
            placeholder={COPY.preSession.jdPlaceholder}
            className="jd-paste"
            style={{ minHeight: 110 }}
          />
        </label>

        {mode !== "live_coding" ? (
          <label
            style={{
              display: "flex",
              gap: 12,
              alignItems: "flex-start",
              cursor: "pointer",
            }}
          >
            <input
              type="checkbox"
              checked={voice}
              onChange={(e) => setVoice(e.target.checked)}
              style={{ marginTop: 4 }}
            />
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>
                {COPY.preSession.voiceLabel}
              </div>
              <div
                style={{
                  fontSize: 13,
                  color: "var(--muted)",
                  lineHeight: 1.55,
                }}
              >
                {COPY.preSession.voiceHelp}
              </div>
            </div>
          </label>
        ) : null}

        {startError ? (
          <div
            style={{
              padding: "10px 14px",
              borderRadius: 10,
              background: "#f7e1d9",
              color: "var(--rose)",
              fontSize: 13,
            }}
          >
            {startError}
          </div>
        ) : null}

        <div className="rd-footer" style={{ marginTop: 6 }}>
          <button
            type="button"
            className="btn primary"
            disabled={!canStart}
            onClick={() =>
              onStart({
                target_role: targetRole.trim(),
                level,
                jd_text: jdText.trim() || undefined,
                voice_enabled: voice && mode !== "live_coding",
              })
            }
          >
            {isStarting ? "Starting…" : COPY.preSession.startButton}
          </button>
          <button type="button" className="btn ghost" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

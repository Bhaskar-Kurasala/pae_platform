"use client";

import { useCallback, useEffect, useState } from "react";
import {
  type MockMode,
  type StartMockResponse,
  useCompleteMockSession,
  useStartMockSession,
} from "@/lib/hooks/use-mock-interview";
import { mockAnalytics } from "./analytics";
import { COPY } from "./copy";
import { LiveCoding } from "./live-coding";
import { ModePicker } from "./mode-picker";
import { type PreSessionValues, PreSessionSetup } from "./pre-session-setup";
import { Report } from "./report";
import { SessionChat } from "./session-chat";
import {
  type MockSessionReport,
} from "@/lib/hooks/use-mock-interview";

type Stage = "picker" | "setup" | "session" | "report";

interface WorkspaceProps {
  /** Default target role pre-filled in setup. Falls back to "Junior Python Developer". */
  defaultTargetRole?: string;
}

export function MockInterviewWorkspace({ defaultTargetRole }: WorkspaceProps) {
  const [stage, setStage] = useState<Stage>("picker");
  const [mode, setMode] = useState<MockMode | null>(null);
  const [session, setSession] = useState<StartMockResponse | null>(null);
  const [report, setReport] = useState<MockSessionReport | null>(null);
  const [startError, setStartError] = useState<string | null>(null);

  const startMutation = useStartMockSession();
  const completeMutation = useCompleteMockSession();

  const handlePickMode = useCallback((picked: MockMode) => {
    if (picked === "system_design") return;
    setMode(picked);
    setStage("setup");
  }, []);

  const handleStart = useCallback(
    async (values: PreSessionValues) => {
      if (!mode) return;
      setStartError(null);
      try {
        const result = await startMutation.mutateAsync({
          mode,
          ...values,
        });
        setSession(result);
        setStage("session");
        mockAnalytics.sessionStarted({
          mode: result.mode,
          voice_enabled: result.voice_enabled,
          level: result.level,
        });
      } catch (exc) {
        setStartError(
          exc instanceof Error ? exc.message : COPY.errors.startFailed,
        );
      }
    },
    [mode, startMutation],
  );

  const handleComplete = useCallback(
    async (sessionId: string) => {
      try {
        const result = await completeMutation.mutateAsync(sessionId);
        setReport(result.report);
        setStage("report");
        mockAnalytics.sessionCompleted({
          session_id: sessionId,
          total_cost_inr: result.report.total_cost_inr,
        });
      } catch {
        // Even if the report call fails, leave the user with a way out.
        setReport(null);
        setStage("report");
      }
    },
    [completeMutation],
  );

  const handleAbandon = useCallback(
    (sessionId: string, questionsAnswered: number) => {
      mockAnalytics.sessionAbandoned({
        session_id: sessionId,
        questions_answered: questionsAnswered,
      });
      setStage("picker");
      setSession(null);
      setMode(null);
    },
    [],
  );

  const handleReset = useCallback(() => {
    setStage("picker");
    setMode(null);
    setSession(null);
    setReport(null);
    setStartError(null);
  }, []);

  // ── Stage shells ───────────────────────────────────────────────
  if (stage === "picker" || mode === null) {
    return (
      <div style={{ display: "grid", gap: 18 }}>
        <ModePicker selected={mode} onSelect={handlePickMode} />
      </div>
    );
  }

  if (stage === "setup") {
    return (
      <div style={{ display: "grid", gap: 14 }}>
        <PreSessionSetup
          mode={mode}
          defaultRole={defaultTargetRole}
          isStarting={startMutation.isPending}
          startError={startError}
          onCancel={() => setStage("picker")}
          onStart={handleStart}
        />
      </div>
    );
  }

  if (stage === "session" && session) {
    if (mode === "live_coding") {
      return (
        <LiveCoding
          session={session}
          onComplete={handleComplete}
          onAbandon={handleAbandon}
        />
      );
    }
    return (
      <SessionChat
        session={session}
        voiceEnabled={session.voice_enabled}
        onComplete={handleComplete}
        onAbandon={handleAbandon}
      />
    );
  }

  if (stage === "report") {
    return (
      <div style={{ display: "grid", gap: 14 }}>
        {completeMutation.isPending ? (
          <div className="match-card" style={{ padding: 22 }}>
            <div className="k">Generating report</div>
            <div className="big">
              Synthesizing patterns, prior sessions, and per-answer evaluations…
            </div>
          </div>
        ) : null}
        {report ? <Report report={report} /> : null}
        <div className="rd-footer">
          <button type="button" className="btn ghost" onClick={handleReset}>
            New mock interview
          </button>
        </div>
      </div>
    );
  }

  return null;
}

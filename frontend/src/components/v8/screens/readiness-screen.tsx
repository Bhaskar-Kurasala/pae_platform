"use client";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";

export function ReadinessScreen() {
  useSetV8Topbar({
    eyebrow: "Career · Job readiness workspace",
    titleHtml: "Turn learning into <i>interviewable proof</i>.",
    chips: [],
    progress: 82,
  });
  return (
    <section className="screen active">
      <div className="pad">
        <div className="card pad reveal">
          <h3 style={{ fontFamily: "var(--serif)", fontSize: 28, margin: 0 }}>Job readiness</h3>
          <p style={{ color: "var(--muted)", marginTop: 8 }}>Coming up in this migration pass.</p>
        </div>
      </div>
    </section>
  );
}

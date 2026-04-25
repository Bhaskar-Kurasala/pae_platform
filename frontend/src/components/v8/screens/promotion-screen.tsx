"use client";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";

export function PromotionScreen() {
  useSetV8Topbar({
    eyebrow: "Promotion gate",
    titleHtml: "One title change. Earned through <i>evidence</i>.",
    chips: [],
    progress: 78,
  });
  return (
    <section className="screen active">
      <div className="pad">
        <div className="card pad reveal">
          <h3 style={{ fontFamily: "var(--serif)", fontSize: 28, margin: 0 }}>Promotion</h3>
          <p style={{ color: "var(--muted)", marginTop: 8 }}>Coming up in this migration pass.</p>
        </div>
      </div>
    </section>
  );
}

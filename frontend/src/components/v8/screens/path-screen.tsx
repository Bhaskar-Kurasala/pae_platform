"use client";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";

export function PathScreen() {
  useSetV8Topbar({
    eyebrow: "Your path",
    titleHtml: "A believable ladder from your current role to your <i>future one</i>.",
    chips: [],
    progress: 40,
  });
  return (
    <section className="screen active">
      <div className="pad">
        <div className="card pad reveal">
          <h3 style={{ fontFamily: "var(--serif)", fontSize: 28, margin: 0 }}>
            My Path
          </h3>
          <p style={{ color: "var(--muted)", marginTop: 8 }}>
            Coming up in this migration pass.
          </p>
        </div>
      </div>
    </section>
  );
}

"use client";

import { useSetV8Topbar } from "@/components/v8/v8-topbar-context";

export function CatalogScreen() {
  useSetV8Topbar({
    eyebrow: "Catalog · 5 career tracks",
    titleHtml: "Every role is a track. Unlock the <i>next one</i> when ready.",
    chips: [],
    progress: 50,
  });
  return (
    <section className="screen active">
      <div className="pad">
        <div className="card pad reveal">
          <h3 style={{ fontFamily: "var(--serif)", fontSize: 28, margin: 0 }}>Catalog</h3>
          <p style={{ color: "var(--muted)", marginTop: 8 }}>Coming up in this migration pass.</p>
        </div>
      </div>
    </section>
  );
}

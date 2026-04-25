"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "cf-sound";

/** v8 sidebar sound-cues toggle. Persists preference in localStorage. */
export function V8SoundToggle() {
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    try {
      const v = localStorage.getItem(STORAGE_KEY);
      if (v !== null) setEnabled(v === "true");
    } catch {
      /* ignore */
    }
  }, []);

  function toggle() {
    setEnabled((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, String(next));
        if (next) playUiSound("toggle");
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  return (
    <button
      type="button"
      className={`sound-toggle${enabled ? "" : " off"}`}
      onClick={toggle}
      aria-pressed={enabled}
      aria-label={enabled ? "Disable audio cues" : "Enable audio cues"}
      title="Plays subtle UI sounds when you complete reviews, unlock a lesson, or earn a promotion."
    >
      <svg
        viewBox="0 0 14 14"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        aria-hidden
      >
        <path d="M2 5v4h2l3 3V2L4 5H2z" />
        {enabled && <path d="M9 5c1 .8 1 3.2 0 4M11 3.5c2 1.5 2 5.5 0 7" />}
      </svg>
      <span>{enabled ? "Audio cues on" : "Audio cues off"}</span>
    </button>
  );
}

/** Play a tiny WebAudio sine ping. Honored only when sound is enabled. */
export function playUiSound(type: "toggle" | "complete" | "promote") {
  try {
    if (typeof window === "undefined") return;
    const enabled = localStorage.getItem(STORAGE_KEY) !== "false";
    if (!enabled) return;
    const W = window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext };
    const Ctx = W.AudioContext ?? W.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.connect(g);
    g.connect(ctx.destination);
    const freqs = { toggle: 660, complete: 880, promote: 1320 } as const;
    o.frequency.value = freqs[type];
    o.type = "sine";
    g.gain.setValueAtTime(0.06, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25);
    o.start();
    o.stop(ctx.currentTime + 0.25);
  } catch {
    /* ignore — audio is non-critical */
  }
}

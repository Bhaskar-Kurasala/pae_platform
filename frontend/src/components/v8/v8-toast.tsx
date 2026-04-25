"use client";

import { useEffect, useState } from "react";

let setShared: ((message: string) => void) | null = null;

/**
 * Imperative v8-style toast: `v8Toast("Lesson unlocked.")`.
 * Shows a single bottom-right pill that auto-dismisses after ~3 seconds.
 */
export function v8Toast(message: string): void {
  setShared?.(message);
}

export function V8ToastHost() {
  const [message, setMessage] = useState("");
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    setShared = (m: string) => {
      setMessage(m);
      setVisible(false);
      requestAnimationFrame(() => setVisible(true));
    };
    return () => {
      setShared = null;
    };
  }, []);

  useEffect(() => {
    if (!visible) return;
    const id = window.setTimeout(() => setVisible(false), 2900);
    return () => window.clearTimeout(id);
  }, [visible]);

  return (
    <div className={`toast${visible ? " show" : ""}`} role="status" aria-live="polite">
      {message}
    </div>
  );
}

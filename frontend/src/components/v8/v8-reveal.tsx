"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

/**
 * Wires the v8 `.reveal → .reveal.in` IntersectionObserver behavior across
 * the portal. Re-runs on route changes so newly-mounted screens animate in.
 */
export function V8Reveal() {
  const pathname = usePathname();

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      // Skip the observer entirely; CSS already disables transitions.
      document
        .querySelectorAll<HTMLElement>(".reveal")
        .forEach((el) => el.classList.add("in"));
      animateAllCounts();
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            animateCountsIn(entry.target as HTMLElement);
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 },
    );

    // Fire after layout settles for the new route.
    const id = window.setTimeout(() => {
      document
        .querySelectorAll<HTMLElement>(".reveal:not(.in)")
        .forEach((el) => observer.observe(el));
      // Animate counts on visible-on-mount elements (above the fold).
      document
        .querySelectorAll<HTMLElement>(".count")
        .forEach((el) => maybeAnimateCount(el));
    }, 60);

    return () => {
      window.clearTimeout(id);
      observer.disconnect();
    };
  }, [pathname]);

  return null;
}

function animateAllCounts() {
  document.querySelectorAll<HTMLElement>(".count").forEach((el) => maybeAnimateCount(el));
}

function animateCountsIn(root: HTMLElement) {
  root.querySelectorAll<HTMLElement>(".count").forEach((el) => maybeAnimateCount(el));
}

function maybeAnimateCount(el: HTMLElement) {
  if (el.dataset.animated === "true") return;
  el.dataset.animated = "true";
  const targetAttr = el.dataset.to;
  const target = Number(targetAttr ?? el.textContent?.replace(/[^0-9-]/g, "") ?? 0);
  if (!Number.isFinite(target)) return;
  const duration = 900;
  const start = performance.now();

  function frame(now: number) {
    const p = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = String(Math.round(target * eased));
    if (p < 1) requestAnimationFrame(frame);
  }

  requestAnimationFrame(frame);
}

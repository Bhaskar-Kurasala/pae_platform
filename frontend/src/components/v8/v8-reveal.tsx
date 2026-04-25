"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

/**
 * Wires the v8 `.reveal → .reveal.in` IntersectionObserver behavior across
 * the portal. Re-runs on route changes so newly-mounted screens animate in.
 *
 * Also subscribes a MutationObserver so `.reveal` nodes mounted after the
 * initial render (data-loaded sections, conditionally-rendered cards) still
 * receive their entry animation.
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

    const intersection = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in");
            animateCountsIn(entry.target as HTMLElement);
            intersection.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 },
    );

    function observeReveals() {
      document
        .querySelectorAll<HTMLElement>(".reveal:not(.in)")
        .forEach((el) => intersection.observe(el));
    }

    // Observe currently-mounted reveals shortly after route mount.
    const timer = window.setTimeout(() => {
      observeReveals();
      document
        .querySelectorAll<HTMLElement>(".count")
        .forEach((el) => maybeAnimateCount(el));
    }, 60);

    // Watch for new .reveal elements added later (data-loaded content).
    const mutation = new MutationObserver((records) => {
      let dirty = false;
      for (const r of records) {
        r.addedNodes.forEach((n) => {
          if (n.nodeType !== 1) return;
          const el = n as HTMLElement;
          if (el.classList?.contains("reveal") && !el.classList.contains("in")) {
            dirty = true;
          } else if (el.querySelector?.(".reveal:not(.in)")) {
            dirty = true;
          }
        });
      }
      if (dirty) observeReveals();
    });
    mutation.observe(document.body, { childList: true, subtree: true });

    // Failsafe: anything still un-revealed after 1.2s gets force-revealed so
    // off-screen or never-intersected content doesn't stay blurred forever.
    const failsafe = window.setTimeout(() => {
      document
        .querySelectorAll<HTMLElement>(".reveal:not(.in)")
        .forEach((el) => {
          el.classList.add("in");
          animateCountsIn(el);
        });
    }, 1200);

    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(failsafe);
      mutation.disconnect();
      intersection.disconnect();
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

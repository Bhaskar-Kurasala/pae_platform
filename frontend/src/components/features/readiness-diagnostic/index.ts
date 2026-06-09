/**
 * Public surface for the Readiness Diagnostic feature.
 *
 * The page anchor (DiagnosticAnchor) replaces the OverviewView body
 * on the readiness screen when the feature flag is enabled. The
 * sub-components are exported for testability and for the diagnostic
 * ↔ JD decoder bundling work in commit 9.
 */

export { DiagnosticAnchor } from "./diagnostic-anchor";
export { Conversation } from "./conversation";
export { VerdictCard } from "./verdict-card";
export { MemoryBanner } from "./memory-banner";
export { PastDiagnosesDrawer } from "./past-diagnoses-drawer";
export { diagnosticAnalytics } from "./analytics";

/**
 * Feature-flag guard. Backend is the authoritative gate; frontend
 * flag is advisory for UI rendering.
 *
 * As of the 2026-04-26 readiness workspace refactor, default is ON.
 * The flag now functions as a kill-switch — set
 * `NEXT_PUBLIC_FEATURE_READINESS_DIAGNOSTIC=0` to fall back to the
 * legacy placeholder view in environments that need it disabled.
 */
export function isReadinessDiagnosticEnabled(): boolean {
  if (typeof process === "undefined") return true;
  return process.env.NEXT_PUBLIC_FEATURE_READINESS_DIAGNOSTIC !== "0";
}

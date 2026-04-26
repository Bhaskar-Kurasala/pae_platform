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
 */
export function isReadinessDiagnosticEnabled(): boolean {
  if (typeof process === "undefined") return false;
  return process.env.NEXT_PUBLIC_FEATURE_READINESS_DIAGNOSTIC === "1";
}

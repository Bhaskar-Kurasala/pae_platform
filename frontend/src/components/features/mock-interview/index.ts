export { ModePicker } from "./mode-picker";
export { PreSessionSetup } from "./pre-session-setup";
export { SessionChat } from "./session-chat";
export { LiveCoding } from "./live-coding";
export { Report } from "./report";
export { MockInterviewWorkspace } from "./workspace";
export { COPY as MOCK_COPY, ANALYTICS_EVENTS as MOCK_ANALYTICS_EVENTS } from "./copy";
export { mockAnalytics } from "./analytics";

/**
 * Feature flag — defaults to ON. Set NEXT_PUBLIC_MOCK_INTERVIEW_DISABLED=1
 * to hide the entry point (e.g., for emergency rollback). Co-located here
 * because we don't have a central feature-flag service yet.
 */
export const isMockInterviewEnabled = (): boolean => {
  if (typeof process === "undefined") return true;
  return process.env.NEXT_PUBLIC_MOCK_INTERVIEW_DISABLED !== "1";
};

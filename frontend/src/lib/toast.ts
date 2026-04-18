import { toast as sonnerToast } from "sonner";

/**
 * Semantic toast wrapper around Sonner.
 *
 * Why wrap it:
 *  - callsites should say "success" / "error" / "undo" — not pick icons
 *  - defaults (duration, position, accessible roles) live in ONE place
 *  - the undo-action pattern is used enough to deserve its own helper
 *
 * Usage:
 *   import { toast } from "@/lib/toast"
 *   toast.success("Goal saved.")
 *   toast.error("Couldn't save — retry?")
 *   toast.undo("Deleted lesson.", () => restore())
 *   toast.promise(saveGoal(), { loading: "Saving…", success: "Saved!", error: "Failed" })
 */

type Duration = "short" | "base" | "long" | "persistent" | number;

const DURATION_MAP: Record<Exclude<Duration, number>, number> = {
  short: 2_000,
  base: 4_000,
  long: 8_000,
  persistent: Number.POSITIVE_INFINITY,
};

function resolveDuration(d: Duration | undefined): number | undefined {
  if (d === undefined) return undefined;
  return typeof d === "number" ? d : DURATION_MAP[d];
}

export interface ToastOptions {
  description?: string;
  duration?: Duration;
  id?: string | number;
  /** When present, renders a clickable action button. */
  action?: { label: string; onClick: () => void };
  /** When present, renders a cancel button. */
  cancel?: { label: string; onClick?: () => void };
}

function toOpts(o?: ToastOptions) {
  if (!o) return undefined;
  return {
    description: o.description,
    id: o.id,
    duration: resolveDuration(o.duration),
    action: o.action
      ? { label: o.action.label, onClick: () => o.action!.onClick() }
      : undefined,
    cancel: o.cancel
      ? { label: o.cancel.label, onClick: () => o.cancel?.onClick?.() }
      : undefined,
  };
}

export const toast = {
  /** Neutral info toast. */
  message: (message: string, options?: ToastOptions) =>
    sonnerToast(message, toOpts(options)),

  success: (message: string, options?: ToastOptions) =>
    sonnerToast.success(message, toOpts(options)),

  error: (message: string, options?: ToastOptions) =>
    sonnerToast.error(message, toOpts({ duration: "long", ...options })),

  warning: (message: string, options?: ToastOptions) =>
    sonnerToast.warning(message, toOpts(options)),

  info: (message: string, options?: ToastOptions) =>
    sonnerToast.info(message, toOpts(options)),

  loading: (message: string, options?: ToastOptions) =>
    sonnerToast.loading(message, toOpts(options)),

  /**
   * Undo pattern — the canonical "I just did X; want to undo?" toast.
   * The default duration is 6s to give users time to react.
   */
  undo: (
    message: string,
    onUndo: () => void,
    options?: Omit<ToastOptions, "action">,
  ) =>
    sonnerToast(
      message,
      toOpts({
        duration: 6_000,
        ...options,
        action: { label: "Undo", onClick: onUndo },
      }),
    ),

  /** Promise-based toast with loading/success/error states. */
  promise: <T>(
    promise: Promise<T> | (() => Promise<T>),
    messages: {
      loading: string;
      success: string | ((data: T) => string);
      error: string | ((error: unknown) => string);
    },
  ) => sonnerToast.promise(promise, messages),

  dismiss: (id?: string | number) => sonnerToast.dismiss(id),
};

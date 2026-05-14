"use client";

import React, { useState } from "react";
import {
  Bug,
  HelpCircle,
  Heart,
  Lightbulb,
  MessageCircle,
  Send,
  X,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api-client";

type Category = "bug" | "confusing" | "feature_request" | "praise" | "other";
type Severity = "cosmetic" | "annoying" | "blocking";

interface CategoryDef {
  key: Category;
  label: string;
  Icon: React.ComponentType<{ className?: string }>;
  placeholder: string;
}

const CATEGORIES: CategoryDef[] = [
  {
    key: "bug",
    label: "Bug",
    Icon: Bug,
    placeholder: "What went wrong? Steps to reproduce help us a lot.",
  },
  {
    key: "confusing",
    label: "Confusing",
    Icon: HelpCircle,
    placeholder: "What did you expect to happen? What was unclear?",
  },
  {
    key: "feature_request",
    label: "Idea",
    Icon: Lightbulb,
    placeholder: "Tell us what you wish this could do.",
  },
  {
    key: "praise",
    label: "Praise",
    Icon: Heart,
    placeholder: "What's working well for you?",
  },
  {
    key: "other",
    label: "Other",
    Icon: MessageCircle,
    placeholder: "What's on your mind?",
  },
];

const SEVERITIES: { key: Severity; label: string }[] = [
  { key: "cosmetic", label: "Cosmetic" },
  { key: "annoying", label: "Annoying" },
  { key: "blocking", label: "Blocking" },
];

interface FeedbackPayload {
  route: string;
  body: string;
  category: Category;
  severity?: Severity;
  url?: string;
  user_agent?: string;
  viewport_width?: number;
  viewport_height?: number;
  app_version?: string;
  sentiment: null;
}

type Status = "idle" | "sending" | "sent" | "error";

export function FeedbackWidget() {
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<Category>("other");
  const [severity, setSeverity] = useState<Severity>("annoying");
  const [includeContext, setIncludeContext] = useState(true);
  const [status, setStatus] = useState<Status>("idle");
  const pathname = usePathname();

  const activeCategory =
    CATEGORIES.find((c) => c.key === category) ?? CATEGORIES[4];

  const reset = () => {
    setBody("");
    setCategory("other");
    setSeverity("annoying");
    setIncludeContext(true);
    setStatus("idle");
  };

  const close = () => {
    setOpen(false);
    // Slight delay so the user doesn't see state flicker as it closes
    setTimeout(reset, 200);
  };

  const submit = async () => {
    if (!body.trim() || status === "sending") return;
    setStatus("sending");
    const payload: FeedbackPayload = {
      route: pathname ?? "",
      body: body.trim(),
      category,
      sentiment: null,
    };
    if (category === "bug") payload.severity = severity;
    if (includeContext && typeof window !== "undefined") {
      payload.url = window.location.href;
      payload.user_agent = navigator.userAgent;
      payload.viewport_width = window.innerWidth;
      payload.viewport_height = window.innerHeight;
      payload.app_version = process.env.NEXT_PUBLIC_APP_VERSION ?? "";
    }
    try {
      await api.post("/api/v1/feedback", payload);
      setStatus("sent");
      setTimeout(() => {
        setOpen(false);
        setTimeout(reset, 200);
      }, 2500);
    } catch {
      setStatus("error");
    }
  };

  return (
    <>
      <style>{`
        .fb-fab {
          width: 52px;
          height: 52px;
          border-radius: 9999px;
          background: #1D9E75;
          color: #fff;
          display: flex;
          align-items: center;
          justify-content: center;
          box-shadow: 0 8px 24px rgba(29, 158, 117, 0.32),
                      0 2px 6px rgba(0, 0, 0, 0.08);
          transition: transform 160ms ease, box-shadow 160ms ease;
          border: none;
          cursor: pointer;
        }
        .fb-fab:hover {
          transform: scale(1.04);
          box-shadow: 0 12px 28px rgba(29, 158, 117, 0.38),
                      0 3px 8px rgba(0, 0, 0, 0.10);
        }
        .fb-fab:focus-visible {
          outline: 2px solid #1D9E75;
          outline-offset: 3px;
        }
        .fb-popover {
          width: 360px;
          max-width: calc(100vw - 32px);
          background: #FBF7EE;
          border: 1px solid rgba(60, 47, 30, 0.12);
          border-radius: 14px;
          box-shadow: 0 24px 56px rgba(40, 28, 12, 0.18),
                      0 4px 12px rgba(40, 28, 12, 0.08);
          padding: 16px;
          font-family: Inter, system-ui, sans-serif;
          color: #2B2018;
        }
        .fb-title {
          font-family: Fraunces, ui-serif, Georgia, serif;
          font-size: 18px;
          font-weight: 600;
          letter-spacing: -0.01em;
          color: #2B2018;
        }
        .fb-close {
          border: none;
          background: transparent;
          color: #6B5947;
          border-radius: 6px;
          padding: 4px;
          cursor: pointer;
          display: inline-flex;
        }
        .fb-close:hover { background: rgba(60, 47, 30, 0.08); }
        .fb-chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 5px 10px;
          border-radius: 9999px;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          border: 1px solid rgba(60, 47, 30, 0.18);
          background: #fff;
          color: #4A3A2A;
          cursor: pointer;
          transition: all 120ms ease;
          line-height: 1;
        }
        .fb-chip:hover { border-color: rgba(60, 47, 30, 0.35); }
        .fb-chip.is-active {
          background: #1D9E75;
          border-color: #1D9E75;
          color: #fff;
        }
        .fb-textarea {
          width: 100%;
          resize: vertical;
          font-family: Inter, system-ui, sans-serif;
          font-size: 13px;
          line-height: 1.5;
          color: #2B2018;
          padding: 10px 12px;
          border-radius: 8px;
          border: 1px solid rgba(60, 47, 30, 0.18);
          background: #fff;
          outline: none;
        }
        .fb-textarea:focus {
          border-color: #1D9E75;
          box-shadow: 0 0 0 3px rgba(29, 158, 117, 0.18);
        }
        .fb-checkbox-row {
          display: flex;
          align-items: flex-start;
          gap: 8px;
          font-size: 12px;
          color: #5A4736;
          line-height: 1.4;
          cursor: pointer;
          user-select: none;
        }
        .fb-checkbox-row input { margin-top: 2px; accent-color: #1D9E75; }
        .fb-btn {
          font-family: Inter, system-ui, sans-serif;
          font-size: 13px;
          font-weight: 600;
          border-radius: 8px;
          padding: 8px 14px;
          cursor: pointer;
          border: 1px solid transparent;
          transition: background 120ms ease, opacity 120ms ease;
          display: inline-flex;
          align-items: center;
          gap: 6px;
          line-height: 1;
        }
        .fb-btn-primary {
          background: #1D9E75;
          color: #fff;
        }
        .fb-btn-primary:hover:not(:disabled) { background: #178862; }
        .fb-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
        .fb-btn-ghost {
          background: transparent;
          color: #4A3A2A;
          border-color: rgba(60, 47, 30, 0.18);
        }
        .fb-btn-ghost:hover { background: rgba(60, 47, 30, 0.06); }
        .fb-section-label {
          font-size: 10px;
          font-weight: 700;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: #8A7559;
          margin-bottom: 6px;
        }
        .fb-thanks {
          font-size: 13px;
          color: #1D9E75;
          font-weight: 500;
          padding: 8px 4px;
        }
        .fb-error {
          font-size: 13px;
          color: #B23A2A;
          padding: 8px 4px;
        }
      `}</style>
      <div className="fixed bottom-5 right-5 z-50">
        {open ? (
          <div role="dialog" aria-label="Send feedback" className="fb-popover">
            <div className="mb-3 flex items-center justify-between">
              <span className="fb-title">Send feedback</span>
              <button
                onClick={close}
                aria-label="Close feedback"
                className="fb-close"
                type="button"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {status === "sent" ? (
              <p className="fb-thanks">Thanks — we read every one.</p>
            ) : (
              <>
                <div className="mb-3">
                  <div className="fb-section-label">Category</div>
                  <div className="flex flex-wrap gap-1.5">
                    {CATEGORIES.map(({ key, label, Icon }) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setCategory(key)}
                        className={`fb-chip ${
                          category === key ? "is-active" : ""
                        }`}
                        aria-pressed={category === key}
                      >
                        <Icon className="h-3 w-3" />
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                {category === "bug" && (
                  <div className="mb-3">
                    <div className="fb-section-label">Severity</div>
                    <div className="flex flex-wrap gap-1.5">
                      {SEVERITIES.map(({ key, label }) => (
                        <button
                          key={key}
                          type="button"
                          onClick={() => setSeverity(key)}
                          className={`fb-chip ${
                            severity === key ? "is-active" : ""
                          }`}
                          aria-pressed={severity === key}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <textarea
                  className="fb-textarea mb-3"
                  placeholder={activeCategory.placeholder}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={4}
                  aria-label="Feedback message"
                />

                <label className="fb-checkbox-row mb-3">
                  <input
                    type="checkbox"
                    checked={includeContext}
                    onChange={(e) => setIncludeContext(e.target.checked)}
                  />
                  <span>Include this page&rsquo;s URL and your browser info</span>
                </label>

                {status === "error" && (
                  <div className="fb-error mb-2 flex items-center justify-between">
                    <span>Couldn&rsquo;t send. Try again.</span>
                    <button
                      type="button"
                      className="fb-btn fb-btn-ghost"
                      onClick={submit}
                      style={{ padding: "4px 10px", fontSize: "12px" }}
                    >
                      Retry
                    </button>
                  </div>
                )}

                <div className="flex items-center justify-end gap-2">
                  <button
                    type="button"
                    className="fb-btn fb-btn-ghost"
                    onClick={close}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="fb-btn fb-btn-primary"
                    onClick={submit}
                    disabled={!body.trim() || status === "sending"}
                  >
                    <Send className="h-3.5 w-3.5" />
                    {status === "sending" ? "Sending…" : "Send"}
                  </button>
                </div>
              </>
            )}
          </div>
        ) : (
          <button
            type="button"
            className="fb-fab"
            onClick={() => setOpen(true)}
            aria-label="Open feedback widget"
          >
            <MessageCircle className="h-5 w-5" />
          </button>
        )}
      </div>
    </>
  );
}

"use client";

/**
 * Sticky banner shown whenever an admin is viewing the platform as a
 * student (impersonation mode). Mounted in the portal layout so it
 * appears on every screen the admin lands on while impersonating.
 *
 * Visual goal: impossible to miss. Forest background with high contrast,
 * pinned to the top of the viewport, slim height so it doesn't push
 * content. Includes the target's name and an unmistakable "Exit" button
 * that clears the impersonation store + invalidates React Query so the
 * admin's own data re-fetches cleanly.
 */

import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useImpersonationStore } from "@/stores/impersonation-store";

export function ImpersonationBanner() {
  const target = useImpersonationStore((s) => s.target);
  const stop = useImpersonationStore((s) => s.stop);
  const qc = useQueryClient();
  const router = useRouter();

  if (!target) return null;

  const handleExit = () => {
    stop();
    // Wipe the entire React Query cache so the admin's own data is
    // re-fetched under the new (admin) identity. Cheaper and safer
    // than trying to enumerate every query key.
    qc.clear();
    router.replace("/admin");
  };

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 1000,
        background: "var(--forest)",
        color: "white",
        padding: "10px 18px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        fontSize: 13,
        boxShadow: "0 2px 8px rgba(0,0,0,0.15)",
        flexWrap: "wrap",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span aria-hidden style={{ fontSize: 16 }}>
          👁
        </span>
        <span>
          <strong style={{ fontFamily: "var(--font-fraunces)" }}>
            Viewing as {target.studentName}
          </strong>
          <span
            style={{ opacity: 0.85, marginLeft: 8 }}
            data-testid="impersonation-target-email"
          >
            ({target.studentEmail})
          </span>
        </span>
        <span
          style={{
            opacity: 0.7,
            fontSize: 11,
            padding: "2px 8px",
            borderRadius: 999,
            border: "1px solid rgba(255,255,255,0.3)",
            marginLeft: 6,
          }}
        >
          Read-only
        </span>
      </div>
      <button
        type="button"
        onClick={handleExit}
        style={{
          background: "white",
          color: "var(--forest)",
          border: 0,
          padding: "6px 14px",
          borderRadius: 6,
          fontWeight: 600,
          fontSize: 12,
          cursor: "pointer",
        }}
      >
        Exit student view
      </button>
    </div>
  );
}

"use client";

/**
 * <AdminAvatarMenu> — identity + sign out, click-to-open from the
 * cockpit topbar.
 *
 * The cockpit had no exit before this — admins couldn't sign out
 * from /admin without manually clearing cookies. This dropdown
 * surfaces the missing logout, alongside the identity card so the
 * menu has weight rather than being a single-item popup.
 *
 * The trigger is the existing avatar+name block from the cockpit
 * topbar, now click-aware. We restyle it minimally so it still
 * reads as the same identity card admins are used to.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";

interface AdminAvatarMenuProps {
  pageTheme: "light" | "dark";
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

export function AdminAvatarMenu({ pageTheme }: AdminAvatarMenuProps) {
  const { user, logout } = useAuthStore();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const adminInitials = initials(user?.full_name ?? "Admin");

  function handleSignOut() {
    setOpen(false);
    logout();
    router.replace("/login");
  }

  return (
    <div className="cf-avatar-menu" ref={containerRef}>
      <button
        type="button"
        className="cf-avatar-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className="cf-avatar-pill">{adminInitials}</span>
        <span className="cf-avatar-meta">
          <span className="cf-avatar-name">{user?.full_name ?? "Admin"}</span>
          <span className="cf-avatar-role">
            {user?.role === "admin" ? "Founder · Admin" : "Member"}
          </span>
        </span>
      </button>
      {open ? (
        <div className="cf-avatar-popup" role="menu">
          <div className="cf-avatar-header">
            <span className="cf-avatar-pill cf-avatar-pill-lg">
              {adminInitials}
            </span>
            <div>
              <div className="cf-avatar-header-name">
                {user?.full_name ?? "Admin"}
              </div>
              <div className="cf-avatar-header-email">
                {user?.email ?? ""}
              </div>
            </div>
          </div>
          <div className="cf-avatar-divider" />
          <button
            type="button"
            role="menuitem"
            className="cf-avatar-action cf-avatar-action-danger"
            onClick={handleSignOut}
          >
            <LogOut className="cf-avatar-action-icon" />
            <span>Sign out</span>
          </button>
        </div>
      ) : null}
      <AdminAvatarMenuStyles pageTheme={pageTheme} />
    </div>
  );
}

function AdminAvatarMenuStyles({
  pageTheme,
}: {
  pageTheme: "light" | "dark";
}) {
  const isDark = pageTheme === "dark";
  const ink = isDark ? "#f0ece1" : "#10120e";
  const ink2 = isDark ? "#d6d2c6" : "#232720";
  const muted = isDark ? "#9a9588" : "#686559";
  const muted2 = isDark ? "#7a7568" : "#8f897d";
  const line = isDark ? "#2c3830" : "#dbd1bf";
  const popupBg = isDark
    ? "rgba(20, 28, 22, 0.95)"
    : "rgba(255, 255, 255, 0.96)";
  const popupShadow = isDark
    ? "0 24px 60px rgba(0, 0, 0, 0.55)"
    : "0 24px 60px rgba(21, 19, 13, 0.14)";
  const triggerHover = isDark
    ? "rgba(255,255,255,0.04)"
    : "rgba(0,0,0,0.04)";
  const dangerBg = isDark
    ? "rgba(201, 117, 100, 0.12)"
    : "rgba(154, 75, 59, 0.06)";
  const dangerColor = isDark ? "#c97564" : "#9a4b3b";

  return (
    <style>{`
      .cf-avatar-menu {
        position: relative;
        display: inline-block;
      }
      .cf-avatar-trigger {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 4px 10px 4px 4px;
        background: transparent;
        border: 1px solid transparent;
        border-radius: 999px;
        cursor: pointer;
        transition:
          background .18s cubic-bezier(.2,.8,.2,1),
          border-color .18s cubic-bezier(.2,.8,.2,1);
        color: ${ink};
      }
      .cf-avatar-trigger:hover {
        background: ${triggerHover};
        border-color: ${line};
      }
      .cf-avatar-pill {
        display: inline-grid;
        place-items: center;
        width: 30px;
        height: 30px;
        border-radius: 50%;
        background: linear-gradient(135deg, #b8862d, #d6a54d);
        color: #1f160a;
        font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.02em;
        box-shadow: 0 4px 12px rgba(214, 165, 77, 0.25);
        flex-shrink: 0;
      }
      .cf-avatar-pill-lg {
        width: 40px;
        height: 40px;
        font-size: 13px;
      }
      .cf-avatar-meta {
        display: flex;
        flex-direction: column;
        text-align: left;
        line-height: 1.2;
      }
      .cf-avatar-name {
        font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
        font-size: 13px;
        font-weight: 600;
        letter-spacing: -0.005em;
        color: ${ink};
      }
      .cf-avatar-role {
        font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
        font-size: 9.5px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: ${muted2};
        margin-top: 2px;
      }
      .cf-avatar-popup {
        position: absolute;
        top: calc(100% + 8px);
        right: 0;
        min-width: 260px;
        background: ${popupBg};
        border: 1px solid ${line};
        border-radius: 14px;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        box-shadow: ${popupShadow};
        padding: 8px;
        z-index: 60;
        animation: cfAvatarPop .18s cubic-bezier(.2,.8,.2,1) both;
      }
      @keyframes cfAvatarPop {
        from { opacity: 0; transform: translateY(-4px) scale(.98); }
        to { opacity: 1; transform: translateY(0) scale(1); }
      }
      .cf-avatar-header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px 8px 12px;
      }
      .cf-avatar-header-name {
        font-family: var(--font-fraunces), Georgia, serif;
        font-size: 17px;
        font-weight: 500;
        letter-spacing: -0.015em;
        color: ${ink};
        line-height: 1.2;
      }
      .cf-avatar-header-email {
        font-family: var(--font-jetbrains-mono), ui-monospace, monospace;
        font-size: 11px;
        letter-spacing: 0.005em;
        color: ${muted};
        margin-top: 2px;
      }
      .cf-avatar-divider {
        height: 1px;
        background: ${line};
        margin: 4px 0;
      }
      .cf-avatar-action {
        display: flex;
        align-items: center;
        gap: 10px;
        width: 100%;
        padding: 9px 10px;
        background: transparent;
        border: 0;
        border-radius: 10px;
        cursor: pointer;
        font-family: var(--font-inter), 'Inter', system-ui, sans-serif;
        font-size: 14px;
        font-weight: 500;
        letter-spacing: -0.005em;
        color: ${ink2};
        text-align: left;
        transition: background .14s cubic-bezier(.2,.8,.2,1), color .14s cubic-bezier(.2,.8,.2,1);
      }
      .cf-avatar-action:hover {
        background: ${triggerHover};
      }
      .cf-avatar-action-icon {
        width: 15px;
        height: 15px;
        color: ${muted};
        flex-shrink: 0;
      }
      .cf-avatar-action-danger:hover {
        background: ${dangerBg};
        color: ${dangerColor};
      }
      .cf-avatar-action-danger:hover .cf-avatar-action-icon {
        color: ${dangerColor};
      }
    `}</style>
  );
}

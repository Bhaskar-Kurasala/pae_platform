"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useTheme } from "next-themes";
import { MobileBottomNav } from "@/components/layouts/mobile-bottom-nav";
import { SkipToContent } from "@/components/layouts/skip-to-content";
import {
  BookOpen,
  Bookmark,
  Briefcase,
  ChevronRight,
  Code2,
  Dumbbell,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  ScrollText,
  Sun,
  Target,
  TrendingUp,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { UserAvatar } from "@/components/features/user-avatar";
import { Separator } from "@/components/ui/separator";
import { Kbd } from "@/components/ui/kbd";
import { useMyNotifications } from "@/lib/hooks/use-notifications";
import { SocraticSlider } from "@/components/features/socratic-slider";

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
    >
      {isDark ? (
        <Sun className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  );
}

const navItems = [
  { href: "/today", label: "Today", icon: Sun },
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/courses", label: "Courses", icon: BookOpen },
  { href: "/exercises", label: "Exercises", icon: Dumbbell },
  { href: "/studio", label: "Studio", icon: Code2 },
  { href: "/interview", label: "Interview", icon: Target },
  { href: "/progress", label: "Progress", icon: TrendingUp },
  { href: "/receipts", label: "Receipts", icon: ScrollText },
  { href: "/career", label: "Career", icon: Briefcase },
  { href: "/chat", label: "AI Tutor", icon: MessageSquare },
  { href: "/notebook", label: "Notebook", icon: Bookmark },
];

function SidebarContent({ onClose }: { onClose?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuthStore();
  const { data: unread } = useMyNotifications({ unreadOnly: true, limit: 50 });
  // DISC-49 — surface the unread COUNT (not just a dot) so the sidebar
  // reflects the real `useMyNotifications` feed. We scope to weekly-letter
  // notifications to keep the badge specific to Receipts.
  const unreadLetterCount = (unread ?? []).filter(
    (n) => n.notification_type === "weekly_letter",
  ).length;

  function handleLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <div className="flex flex-col h-full">
      {/* Logo */}
      <div className="flex items-center justify-between h-16 px-5">
        <Link href="/dashboard" className="flex items-center gap-2" onClick={onClose}>
          <span className="font-bold text-lg">
            <span className="text-primary">PAE</span>
            <span className="text-foreground"> Platform</span>
          </span>
        </Link>
        {onClose && (
          <button onClick={onClose} aria-label="Close sidebar" className="rounded p-1 hover:bg-muted">
            <X className="h-5 w-5" />
          </button>
        )}
      </div>
      <Separator />

      {/* Command palette hint */}
      <div className="px-3 pt-3 pb-1">
        <div className="flex items-center gap-2 rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
          <span className="flex-1">Jump anywhere</span>
          <Kbd keys="mod+k" />
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
        {navItems.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              aria-label={label}
              onClick={onClose}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                active
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="flex-1">{label}</span>
              {href === "/receipts" && unreadLetterCount > 0 && (
                <span
                  className={cn(
                    "inline-flex min-w-[1.25rem] items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                    active
                      ? "bg-primary-foreground/20 text-primary-foreground"
                      : "bg-primary text-primary-foreground",
                  )}
                  aria-label={`${unreadLetterCount} unread ${unreadLetterCount === 1 ? "letter" : "letters"}`}
                >
                  {unreadLetterCount > 9 ? "9+" : unreadLetterCount}
                </span>
              )}
              {active && <ChevronRight className="h-3 w-3 opacity-60" aria-hidden="true" />}
            </Link>
          );
        })}
      </nav>

      <Separator />

      {/* User footer */}
      <div className="p-4 flex items-center gap-3">
        <UserAvatar name={user?.full_name ?? "User"} avatarUrl={user?.avatar_url} className="h-8 w-8 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate">{user?.full_name ?? "User"}</p>
          <p className="text-xs text-muted-foreground truncate">{user?.email}</p>
        </div>
        <SocraticSlider />
        <ThemeToggle />
        <button
          onClick={handleLogout}
          aria-label="Sign out"
          className="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

export function PortalLayout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [dragX, setDragX] = useState<number | null>(null);
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);
  const mainRef = useRef<HTMLElement | null>(null);

  // P3 #131 — edge-swipe to open drawer + swipe-to-close inside drawer.
  function handleEdgeTouchStart(e: React.TouchEvent) {
    const t = e.touches[0];
    if (t.clientX < 24 && !sidebarOpen) {
      touchStartRef.current = { x: t.clientX, y: t.clientY };
    }
  }
  function handleEdgeTouchMove(e: React.TouchEvent) {
    const start = touchStartRef.current;
    if (!start) return;
    const t = e.touches[0];
    const dx = t.clientX - start.x;
    const dy = Math.abs(t.clientY - start.y);
    if (dy < 60 && dx > 40) {
      setSidebarOpen(true);
      touchStartRef.current = null;
    }
  }
  function handleEdgeTouchEnd() {
    touchStartRef.current = null;
  }

  function handleDrawerTouchStart(e: React.TouchEvent) {
    const t = e.touches[0];
    touchStartRef.current = { x: t.clientX, y: t.clientY };
    setDragX(0);
  }
  function handleDrawerTouchMove(e: React.TouchEvent) {
    const start = touchStartRef.current;
    if (!start) return;
    const t = e.touches[0];
    const dx = Math.min(0, t.clientX - start.x);
    setDragX(dx);
  }
  function handleDrawerTouchEnd() {
    if (dragX !== null && dragX < -60) setSidebarOpen(false);
    setDragX(null);
    touchStartRef.current = null;
  }

  // DISC-61 — ESC closes the mobile drawer. Radix dialogs inside content have
  // their own ESC handlers and call stopPropagation, so nested modals stay
  // isolated from this listener.
  useEffect(() => {
    if (!sidebarOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setSidebarOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sidebarOpen]);

  // P3 #136 — when a textarea/input on mobile gains focus, scroll it into view
  // above the on-screen keyboard.
  useEffect(() => {
    const mq = window.matchMedia("(pointer: coarse)");
    if (!mq.matches) return;
    function onFocusIn(e: FocusEvent) {
      const el = e.target as HTMLElement | null;
      if (!el) return;
      if (
        el.tagName === "TEXTAREA" ||
        (el.tagName === "INPUT" && (el as HTMLInputElement).type !== "checkbox")
      ) {
        setTimeout(() => {
          el.scrollIntoView({ block: "center", behavior: "smooth" });
        }, 180);
      }
    }
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, []);

  return (
    <div
      className="flex h-screen bg-background overflow-hidden"
      onTouchStart={handleEdgeTouchStart}
      onTouchMove={handleEdgeTouchMove}
      onTouchEnd={handleEdgeTouchEnd}
    >
      <SkipToContent />
      {/* Desktop sidebar */}
      <aside className="hidden md:flex w-64 flex-col border-r bg-card shrink-0">
        <SidebarContent />
      </aside>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setSidebarOpen(false)}
            aria-hidden="true"
          />
          <aside
            className="absolute left-0 top-0 bottom-0 w-72 bg-card border-r shadow-xl transition-transform"
            style={
              dragX !== null
                ? { transform: `translateX(${dragX}px)`, transitionDuration: "0ms" }
                : undefined
            }
            onTouchStart={handleDrawerTouchStart}
            onTouchMove={handleDrawerTouchMove}
            onTouchEnd={handleDrawerTouchEnd}
          >
            <SidebarContent onClose={() => setSidebarOpen(false)} />
          </aside>
        </div>
      )}

      {/* Main area */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Mobile top bar */}
        <header className="md:hidden flex items-center gap-3 px-4 h-14 border-b bg-card shrink-0">
          <button
            onClick={() => setSidebarOpen(true)}
            aria-label="Open sidebar"
            className="rounded p-1 hover:bg-muted"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="font-bold">
            <span className="text-primary">PAE</span> Platform
          </span>
        </header>

        <main
          ref={mainRef}
          id="main-content"
          tabIndex={-1}
          className="flex-1 overflow-auto pb-[calc(env(safe-area-inset-bottom)+64px)] md:pb-0 focus:outline-none"
        >
          {children}
        </main>

        <MobileBottomNav />
      </div>
    </div>
  );
}

"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import {
  AlertTriangle,
  BookOpen,
  Code2,
  Dumbbell,
  Flame,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Microscope,
  Moon,
  ScrollText,
  Sun,
  Target,
  TrendingUp,
  UserCog,
  Users,
  Zap,
} from "lucide-react";
import {
  CommandPalette,
  type CommandItem,
} from "@/components/ui/command-palette";
import { useAuthStore } from "@/stores/auth-store";

/**
 * Power-user command palette wired globally. Opens on ⌘K / Ctrl+K.
 *
 * Items are built from the auth state: students see portal routes, admins see
 * admin routes, and a few actions (toggle theme, sign out) are always available.
 * Keywords are set generously so users can search by feeling ("dark", "churn",
 * "ide", "palette").
 */
export function GlobalCommandPalette() {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const { user, isAuthenticated, logout } = useAuthStore();

  const isDark = resolvedTheme === "dark";
  const isAdmin = user?.role === "admin";

  const items = useMemo<CommandItem[]>(() => {
    const go = (href: string) => () => router.push(href);

    const portal: CommandItem[] = [
      {
        id: "nav-today",
        group: "Navigate",
        label: "Today",
        hint: "Daily intention + agenda",
        keywords: ["home", "start", "daily"],
        icon: <Sun className="h-4 w-4" />,
        onSelect: go("/today"),
      },
      {
        id: "nav-dashboard",
        group: "Navigate",
        label: "Dashboard",
        hint: "Your learning overview",
        keywords: ["overview", "main"],
        icon: <LayoutDashboard className="h-4 w-4" />,
        onSelect: go("/dashboard"),
      },
      {
        id: "nav-courses",
        group: "Navigate",
        label: "Courses",
        keywords: ["catalog", "lessons", "learn"],
        icon: <BookOpen className="h-4 w-4" />,
        onSelect: go("/courses"),
      },
      {
        id: "nav-exercises",
        group: "Navigate",
        label: "Exercises",
        keywords: ["practice", "drill", "problems"],
        icon: <Dumbbell className="h-4 w-4" />,
        onSelect: go("/exercises"),
      },
      {
        id: "nav-studio",
        group: "Navigate",
        label: "Studio",
        hint: "Code editor",
        keywords: ["ide", "editor", "write code"],
        icon: <Code2 className="h-4 w-4" />,
        onSelect: go("/studio"),
      },
      {
        id: "nav-interview",
        group: "Navigate",
        label: "Interview",
        hint: "Mock interview mode",
        keywords: ["interview", "system design", "faang"],
        icon: <Target className="h-4 w-4" />,
        onSelect: go("/interview"),
      },
      {
        id: "nav-progress",
        group: "Navigate",
        label: "Progress",
        keywords: ["stats", "growth", "mastery"],
        icon: <TrendingUp className="h-4 w-4" />,
        onSelect: go("/progress"),
      },
      {
        id: "nav-receipts",
        group: "Navigate",
        label: "Receipts",
        hint: "Weekly letters + autopsy",
        keywords: ["letter", "autopsy", "review"],
        icon: <ScrollText className="h-4 w-4" />,
        onSelect: go("/receipts"),
      },
      {
        id: "nav-chat",
        group: "Navigate",
        label: "AI Tutor",
        hint: "Chat with the tutor",
        keywords: ["chat", "help", "question", "socratic"],
        icon: <MessageSquare className="h-4 w-4" />,
        onSelect: go("/chat"),
      },
      {
        id: "action-autopsy",
        group: "Actions",
        label: "Run portfolio autopsy",
        hint: "Critique a project post-mortem",
        keywords: ["autopsy", "critique", "retro", "postmortem"],
        icon: <Microscope className="h-4 w-4" />,
        onSelect: go("/receipts#autopsy"),
      },
    ];

    const admin: CommandItem[] = [
      {
        id: "admin-overview",
        group: "Admin",
        label: "Admin overview",
        keywords: ["admin", "stats", "dashboard"],
        icon: <LayoutDashboard className="h-4 w-4" />,
        onSelect: go("/admin"),
      },
      {
        id: "admin-students",
        group: "Admin",
        label: "Students",
        keywords: ["students", "users", "roster"],
        icon: <Users className="h-4 w-4" />,
        onSelect: go("/admin/students"),
      },
      {
        id: "admin-confusion",
        group: "Admin",
        label: "Confusion heatmap",
        hint: "Where students are stuck",
        keywords: ["confusion", "heatmap", "stuck", "help"],
        icon: <Flame className="h-4 w-4" />,
        onSelect: go("/admin/confusion"),
      },
      {
        id: "admin-atrisk",
        group: "Admin",
        label: "At-risk students",
        hint: "Likely to churn",
        keywords: ["at-risk", "churn", "drop off", "risk"],
        icon: <AlertTriangle className="h-4 w-4" />,
        onSelect: go("/admin/at-risk"),
      },
      // Removed admin-courses / admin-analytics / admin-settings —
      // those routes don't have page.tsx files (see comment in
      // admin-layout.tsx). Re-add the entry alongside the actual
      // page when each is built.
      {
        id: "admin-agents",
        group: "Admin",
        label: "Agents health",
        keywords: ["agents", "health", "errors"],
        icon: <Zap className="h-4 w-4" />,
        onSelect: go("/admin/agents"),
      },
    ];

    const settings: CommandItem[] = [
      {
        id: "toggle-theme",
        group: "Preferences",
        label: isDark ? "Switch to light mode" : "Switch to dark mode",
        keywords: ["theme", "dark", "light", "appearance"],
        icon: isDark ? (
          <Sun className="h-4 w-4" />
        ) : (
          <Moon className="h-4 w-4" />
        ),
        onSelect: () => setTheme(isDark ? "light" : "dark"),
      },
    ];

    const account: CommandItem[] = isAuthenticated
      ? [
          {
            id: "account-profile",
            group: "Account",
            label: "Edit profile",
            keywords: ["profile", "account", "settings", "me"],
            icon: <UserCog className="h-4 w-4" />,
            onSelect: go("/settings"),
          },
          {
            id: "account-signout",
            group: "Account",
            label: "Sign out",
            keywords: ["logout", "sign out", "exit"],
            icon: <LogOut className="h-4 w-4" />,
            onSelect: () => {
              logout();
              router.replace("/login");
            },
          },
        ]
      : [
          {
            id: "account-signin",
            group: "Account",
            label: "Sign in",
            keywords: ["login", "sign in"],
            icon: <UserCog className="h-4 w-4" />,
            onSelect: go("/login"),
          },
        ];

    return [
      ...(isAuthenticated ? portal : []),
      ...(isAdmin ? admin : []),
      ...settings,
      ...account,
    ];
  }, [router, isDark, setTheme, isAuthenticated, isAdmin, logout]);

  return (
    <CommandPalette
      open={open}
      onOpenChange={setOpen}
      items={items}
      placeholder="Search pages, actions, settings…"
    />
  );
}

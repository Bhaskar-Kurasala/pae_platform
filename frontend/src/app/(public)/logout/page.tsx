"use client";

/**
 * /logout — convenience route.
 *
 * Direct navigation to /logout (from a link, email, external integration,
 * or bookmark) clears the auth state and redirects to /login. The canonical
 * in-app sign-out flows through the user-menu "Sign out" button which calls
 * useAuthStore().logout() directly; this route is the same behaviour exposed
 * at a stable URL.
 *
 * Audit finding (production-readiness MCP audit, 2026-05-13):
 *   Pre-existing direct navigation to /logout returned 404 because no
 *   route was registered. This file closes that gap.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuthStore } from "@/stores/auth-store";

export default function LogoutPage() {
  const router = useRouter();
  const logout = useAuthStore((state) => state.logout);

  useEffect(() => {
    logout();
    // Replace (not push) so the back button doesn't return to /logout.
    router.replace("/login");
  }, [logout, router]);

  return (
    <div
      role="status"
      aria-live="polite"
      className="min-h-[40vh] flex items-center justify-center text-sm text-muted-foreground"
    >
      Signing you out…
    </div>
  );
}

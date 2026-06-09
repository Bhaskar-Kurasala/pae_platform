"use client";

/**
 * Admin section root layout — every /admin/* route renders the same
 * <AdminTopbar> (brand, page switcher, search, live indicator,
 * theme toggle, avatar menu). One nav system, no surface-switch when
 * an operator clicks across cockpit / students / audit log.
 *
 * The legacy <AdminLayout> sidebar was retired in this pass — eight
 * vertically-stacked icon links is fine for a sysadmin tool but
 * felt out of place against the cockpit's editorial v8/cockpit
 * chrome. The page switcher in the topbar covers the same
 * destinations more compactly and groups them Operate/System.
 *
 * Behaviour:
 *  • The cockpit (/admin) renders its OWN <AdminTopbar liveLabel="…">
 *    so it can stamp the "synced HH:MM" indicator that depends on the
 *    cockpit's data payload. The layout suppresses the default
 *    topbar for that one route to avoid double-rendering.
 *  • Every other admin route renders the default topbar this layout
 *    injects, so we don't have to touch 8 sub-pages.
 */

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { AdminTopbar } from "./_components/admin-topbar";

export default function AdminRootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, isAuthenticated, _hasHydrated, refreshMe } = useAuthStore();
  const router = useRouter();
  const pathname = usePathname() ?? "";
  const refreshAttempted = useRef(false);

  // The cockpit owns its topbar so it can pass a live `synced HH:MM`
  // indicator. Every other admin route inherits the default topbar
  // this layout injects.
  const isCockpit = pathname === "/admin";

  useEffect(() => {
    if (!_hasHydrated) return;
    if (!isAuthenticated) {
      router.replace("/login?next=%2Fadmin");
      return;
    }
    // Zombie-auth guard (DISC-52): isAuthenticated=true but user=null
    // means login's follow-up /me call failed or persistence was
    // partial. Try one refresh; if that fails, clear and redirect.
    if (isAuthenticated && !user && !refreshAttempted.current) {
      refreshAttempted.current = true;
      void refreshMe().then((ok) => {
        if (!ok) router.replace("/login?next=%2Fadmin");
      });
      return;
    }
    if (user && user.role !== "admin") {
      router.replace("/today");
    }
  }, [_hasHydrated, isAuthenticated, user, router, refreshMe]);

  if (!_hasHydrated || !isAuthenticated || user?.role !== "admin") {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  if (isCockpit) {
    return <>{children}</>;
  }
  return (
    <>
      <AdminTopbar />
      <main>{children}</main>
    </>
  );
}

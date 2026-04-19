"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { AdminLayout } from "@/components/layouts/admin-layout";
import { useAuthStore } from "@/stores/auth-store";

export default function AdminRootLayout({ children }: { children: React.ReactNode }) {
  const { user, isAuthenticated, _hasHydrated, refreshMe } = useAuthStore();
  const router = useRouter();
  const refreshAttempted = useRef(false);

  useEffect(() => {
    if (!_hasHydrated) return;
    if (!isAuthenticated) {
      router.replace("/login?next=%2Fadmin");
      return;
    }
    // Zombie-auth guard (DISC-52): isAuthenticated=true but user=null means
    // login's follow-up /me call failed or persistence was partial. Try one
    // refresh; if that fails, clear and redirect to login.
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

  return <AdminLayout>{children}</AdminLayout>;
}

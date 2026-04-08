"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { PortalLayout } from "@/components/layouts/portal-layout";
import { useAuthStore } from "@/stores/auth-store";

export default function PortalRootLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuthStore();
  const router = useRouter();

  useEffect(() => {
    if (!isAuthenticated) {
      router.replace("/login");
    }
  }, [isAuthenticated, router]);

  if (!isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  return <PortalLayout>{children}</PortalLayout>;
}

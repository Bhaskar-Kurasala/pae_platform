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

  if (!isAuthenticated) return null;

  return <PortalLayout>{children}</PortalLayout>;
}

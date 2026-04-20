import { Suspense } from "react";
import { StudioLayout } from "@/components/features/studio/studio-layout";
import { StudioPageInner } from "./studio-page-inner";
import { StudioPageHeader } from "./studio-page-header";

export const metadata = {
  title: "Studio · PAE Platform",
};

export default function StudioPage() {
  return (
    <div className="flex h-full flex-col">
      {/*
        StudioPageHeader is a client component that owns the challenge-drawer
        toggle state while keeping this server component boundary intact.
      */}
      <StudioPageHeader />
      <div className="flex-1 overflow-hidden">
        {/*
          StudioPageInner reads useSearchParams() to handle the optional
          ?code= deep-link param from "Try in Studio" buttons in chat.
          Suspense is required by Next.js around useSearchParams() calls.
          The fallback renders a plain StudioLayout with no initial code.
        */}
        <Suspense fallback={<StudioLayout />}>
          <StudioPageInner />
        </Suspense>
      </div>
    </div>
  );
}

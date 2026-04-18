import { StudioLayout } from "@/components/features/studio/studio-layout";

export const metadata = {
  title: "Studio · PAE Platform",
};

export default function StudioPage() {
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border bg-card px-4 py-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Studio
          </p>
          <h1 className="text-lg font-semibold leading-tight">Code · Tutor · Trace</h1>
        </div>
      </div>
      <div className="flex-1 overflow-hidden">
        <StudioLayout />
      </div>
    </div>
  );
}

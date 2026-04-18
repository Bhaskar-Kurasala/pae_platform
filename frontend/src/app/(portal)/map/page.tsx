"use client";

import { SkillListFallback } from "@/components/features/skill-map/skill-list-fallback";
import { SkillMap } from "@/components/features/skill-map/skill-map";
import { useIsDesktop } from "@/lib/hooks/use-media-query";

export default function SkillMapPage() {
  const isDesktop = useIsDesktop();

  return (
    <div className="flex h-[calc(100vh-4rem)] w-full flex-col">
      <header className="border-b border-border px-6 py-4">
        <p className="text-xs font-medium uppercase tracking-[0.12em] text-muted-foreground">
          Skill Map
        </p>
        <h1 className="mt-1 text-xl font-semibold tracking-tight">
          Everything you can learn here
        </h1>
      </header>
      <div className="flex-1 overflow-auto">
        {isDesktop ? <SkillMap /> : <SkillListFallback />}
      </div>
    </div>
  );
}

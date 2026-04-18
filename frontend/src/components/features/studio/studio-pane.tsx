"use client";

import type { LucideIcon } from "lucide-react";

interface StudioPaneProps {
  title: string;
  icon: LucideIcon;
  action?: React.ReactNode;
  children: React.ReactNode;
}

export function StudioPane({ title, icon: Icon, action, children }: StudioPaneProps) {
  return (
    <section className="flex h-full flex-col overflow-hidden bg-card">
      <header className="flex h-10 shrink-0 items-center justify-between border-b border-border bg-muted/40 px-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{title}</span>
        </div>
        {action}
      </header>
      <div className="flex-1 overflow-auto">{children}</div>
    </section>
  );
}

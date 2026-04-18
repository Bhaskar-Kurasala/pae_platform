"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ClusterCollapseButtonProps {
  clusterId: string;
  label: string;
  collapsed: boolean;
  skillCount: number;
  onToggle: (clusterId: string) => void;
}

export function ClusterCollapseButton({
  clusterId,
  label,
  collapsed,
  skillCount,
  onToggle,
}: ClusterCollapseButtonProps) {
  return (
    <Button
      variant="ghost"
      size="sm"
      className="flex items-center gap-1 text-xs font-medium text-muted-foreground"
      onClick={() => onToggle(clusterId)}
      aria-label={`${collapsed ? "Expand" : "Collapse"} ${label} cluster`}
    >
      {collapsed ? (
        <ChevronRight className="h-3 w-3" />
      ) : (
        <ChevronDown className="h-3 w-3" />
      )}
      {label}
      <span className="ml-1 rounded-full bg-muted px-1.5 py-0.5 text-[10px]">
        {skillCount}
      </span>
    </Button>
  );
}

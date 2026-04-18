"use client";

import { useMemo, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { MasteryLevel, SkillNode } from "@/lib/api-client";
import {
  useMySkillStates,
  useSkillGraph,
  useSkillPath,
  useTouchSkill,
  useSavedSkillPath,
  useSaveSkillPath,
} from "@/lib/hooks/use-skills";
import { PathLegend } from "./path-overlay";
import { SkillNodeCard, type SkillNodeData } from "./skill-node-card";
import { SkillSidePanel } from "./skill-side-panel";
import { layoutSkillGraph } from "./layout";
import { MasteryLegend } from "./mastery-legend";
import { ClusterCollapseButton } from "./cluster-collapse-button";

const nodeTypes: NodeTypes = { skill: SkillNodeCard };

/** Derive a human-readable cluster label from a layer index. */
function layerLabel(layer: number): string {
  if (layer === 0) return "Foundations";
  if (layer === 1) return "Core concepts";
  if (layer === 2) return "Intermediate";
  if (layer === 3) return "Advanced";
  return `Level ${layer + 1}`;
}

export function SkillMap() {
  const { data: graph, isLoading, isError } = useSkillGraph();
  const { data: states } = useMySkillStates();
  const { data: path } = useSkillPath();
  const touchMutation = useTouchSkill();
  const savePathMutation = useSaveSkillPath();
  const { data: savedPath } = useSavedSkillPath();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [collapsedClusters, setCollapsedClusters] = useState<Set<string>>(
    new Set(),
  );

  const toggleCluster = (clusterId: string) => {
    setCollapsedClusters((prev) => {
      const next = new Set(prev);
      if (next.has(clusterId)) {
        next.delete(clusterId);
      } else {
        next.add(clusterId);
      }
      return next;
    });
  };

  const pathSlugs = useMemo(
    () => (path ? new Set(path.slugs) : null),
    [path],
  );

  const masteryById = useMemo(() => {
    const map = new Map<string, { mastery: MasteryLevel; confidence: number }>();
    for (const s of states ?? []) {
      map.set(s.skill_id, {
        mastery: s.mastery_level,
        confidence: s.confidence,
      });
    }
    return map;
  }, [states]);

  const { rfNodes, rfEdges, nodeById, layerClusters } = useMemo(() => {
    if (!graph) {
      return {
        rfNodes: [] as Node<SkillNodeData>[],
        rfEdges: [] as Edge[],
        nodeById: new Map<string, SkillNode>(),
        layerClusters: [] as { layer: number; label: string; count: number }[],
      };
    }
    const positioned = layoutSkillGraph(graph.nodes, graph.edges);
    const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));

    // Build layer → skill count map for cluster headers
    const layerCountMap = new Map<number, number>();
    for (const n of positioned) {
      layerCountMap.set(n.layer, (layerCountMap.get(n.layer) ?? 0) + 1);
    }
    const layerClusters = Array.from(layerCountMap.entries())
      .sort(([a], [b]) => a - b)
      .map(([layer, count]) => ({ layer, label: layerLabel(layer), count }));

    // Build prereq map: skill_id → list of prerequisite skill IDs
    const prereqsByTarget = new Map<string, string[]>();
    for (const e of graph.edges) {
      if (e.edge_type !== "prereq") continue;
      const list = prereqsByTarget.get(e.to_skill_id) ?? [];
      list.push(e.from_skill_id);
      prereqsByTarget.set(e.to_skill_id, list);
    }

    const MASTERED_LEVELS_SET = new Set(["proficient", "mastered"]);

    // Filter out nodes from collapsed clusters
    const visibleNodes = positioned.filter(
      (n) => !collapsedClusters.has(String(n.layer)),
    );
    const visibleNodeIds = new Set(visibleNodes.map((n) => n.id));

    const rfNodes: Node<SkillNodeData>[] = visibleNodes.map((n) => {
      const prereqIds = prereqsByTarget.get(n.id) ?? [];
      const hasUnmetPrereqs = prereqIds.some(
        (pid) => !MASTERED_LEVELS_SET.has(masteryById.get(pid)?.mastery ?? "unknown"),
      );
      return {
        id: n.id,
        type: "skill",
        position: { x: n.x, y: n.y },
        data: {
          name: n.name,
          slug: n.slug,
          difficulty: n.difficulty,
          mastery: masteryById.get(n.id)?.mastery ?? "unknown",
          onPath: pathSlugs ? pathSlugs.has(n.slug) : true,
          hasUnmetPrereqs,
        },
      };
    });

    const rfEdges: Edge[] = graph.edges
      .filter(
        (e) => visibleNodeIds.has(e.from_skill_id) && visibleNodeIds.has(e.to_skill_id),
      )
      .map((e, i) => {
        const fromSlug = nodeById.get(e.from_skill_id)?.slug;
        const toSlug = nodeById.get(e.to_skill_id)?.slug;
        const edgeOnPath =
          !pathSlugs ||
          (!!fromSlug && !!toSlug && pathSlugs.has(fromSlug) && pathSlugs.has(toSlug));
        const baseColor = e.edge_type === "prereq" ? "#6b7280" : "#cbd5e1";
        return {
          id: `${e.from_skill_id}-${e.to_skill_id}-${e.edge_type}-${i}`,
          source: e.from_skill_id,
          target: e.to_skill_id,
          animated: false,
          style: {
            stroke: baseColor,
            strokeDasharray: e.edge_type === "related" ? "4 4" : undefined,
            opacity: edgeOnPath ? 1 : 0.15,
          },
          markerEnd:
            e.edge_type === "prereq"
              ? { type: MarkerType.ArrowClosed, color: baseColor }
              : undefined,
        };
      });
    return { rfNodes, rfEdges, nodeById, layerClusters };
  }, [graph, masteryById, pathSlugs, collapsedClusters]);

  const handleSavePath = () => {
    if (!graph) return;
    // Save currently path-highlighted skill IDs (or all if no path filter)
    const skillIds = graph.nodes
      .filter((n) => (pathSlugs ? pathSlugs.has(n.slug) : true))
      .map((n) => n.id);
    savePathMutation.mutate(skillIds);
  };

  if (isLoading) {
    return (
      <div
        className="flex h-full items-center justify-center text-sm text-muted-foreground"
        aria-busy="true"
      >
        Loading skill map…
      </div>
    );
  }
  if (isError || !graph) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-destructive">
        Could not load the skill map.
      </div>
    );
  }

  const selected = selectedId ? nodeById.get(selectedId) : null;
  const selectedState = selectedId ? masteryById.get(selectedId) : undefined;
  const allSkills = graph.nodes;

  return (
    <div className="relative flex h-full w-full flex-col" data-slot="skill-map">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-background px-4 py-2">
        <MasteryLegend />
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {/* Cluster collapse controls */}
          {layerClusters.map(({ layer, label, count }) => (
            <ClusterCollapseButton
              key={layer}
              clusterId={String(layer)}
              label={label}
              collapsed={collapsedClusters.has(String(layer))}
              skillCount={count}
              onToggle={toggleCluster}
            />
          ))}
          {/* Save path button */}
          <button
            type="button"
            onClick={handleSavePath}
            disabled={savePathMutation.isPending}
            aria-label="Save current learning path"
            className="rounded-md border border-border bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:opacity-60"
          >
            {savePathMutation.isPending
              ? "Saving…"
              : savePathMutation.isSuccess
                ? "Saved ✓"
                : "Save path"}
          </button>
        </div>
        {savedPath && (
          <span className="w-full text-right text-[10px] text-muted-foreground">
            Saved path: {savedPath.skill_ids.length} skills
          </span>
        )}
      </div>

      {/* Graph canvas */}
      <div className="relative flex-1">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => setSelectedId(node.id)}
          onPaneClick={() => setSelectedId(null)}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} size={1} />
          <Controls position="bottom-right" showInteractive={false} />
        </ReactFlow>
        {path && (
          <PathLegend
            motivation={path.motivation}
            highlighted={path.slugs.length}
            total={graph.nodes.length}
          />
        )}
        {selected && (
          <SkillSidePanel
            skill={selected}
            mastery={selectedState?.mastery ?? "unknown"}
            confidence={selectedState?.confidence ?? 0}
            allSkills={allSkills}
            masteryById={masteryById}
            onClose={() => setSelectedId(null)}
            onMarkTouched={() => touchMutation.mutate(selected.id)}
            isTouching={touchMutation.isPending}
            onSkillSelect={(id) => setSelectedId(id)}
          />
        )}
      </div>
    </div>
  );
}

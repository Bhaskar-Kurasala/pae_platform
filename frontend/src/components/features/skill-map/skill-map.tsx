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
} from "@/lib/hooks/use-skills";
import { PathLegend } from "./path-overlay";
import { SkillNodeCard, type SkillNodeData } from "./skill-node-card";
import { SkillSidePanel } from "./skill-side-panel";
import { layoutSkillGraph } from "./layout";

const nodeTypes: NodeTypes = { skill: SkillNodeCard };

export function SkillMap() {
  const { data: graph, isLoading, isError } = useSkillGraph();
  const { data: states } = useMySkillStates();
  const { data: path } = useSkillPath();
  const touchMutation = useTouchSkill();
  const [selectedId, setSelectedId] = useState<string | null>(null);

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

  const { rfNodes, rfEdges, nodeById } = useMemo(() => {
    if (!graph) {
      return {
        rfNodes: [] as Node<SkillNodeData>[],
        rfEdges: [] as Edge[],
        nodeById: new Map<string, SkillNode>(),
      };
    }
    const positioned = layoutSkillGraph(graph.nodes, graph.edges);
    const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
    const rfNodes: Node<SkillNodeData>[] = positioned.map((n) => ({
      id: n.id,
      type: "skill",
      position: { x: n.x, y: n.y },
      data: {
        name: n.name,
        slug: n.slug,
        difficulty: n.difficulty,
        mastery: masteryById.get(n.id)?.mastery ?? "unknown",
        onPath: pathSlugs ? pathSlugs.has(n.slug) : true,
      },
    }));
    const rfEdges: Edge[] = graph.edges.map((e, i) => {
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
    return { rfNodes, rfEdges, nodeById };
  }, [graph, masteryById, pathSlugs]);

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

  return (
    <div className="relative h-full w-full" data-slot="skill-map">
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
          onClose={() => setSelectedId(null)}
          onMarkTouched={() => touchMutation.mutate(selected.id)}
          isTouching={touchMutation.isPending}
        />
      )}
    </div>
  );
}

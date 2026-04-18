import type { SkillEdge, SkillNode } from "@/lib/api-client";

export interface PositionedNode extends SkillNode {
  x: number;
  y: number;
  layer: number;
}

/**
 * Layered layout: each node's layer = longest prereq-chain depth ending at it.
 * Nodes within a layer spread evenly on the x-axis.
 */
export function layoutSkillGraph(
  nodes: SkillNode[],
  edges: SkillEdge[],
): PositionedNode[] {
  const prereqParents = new Map<string, string[]>();
  for (const e of edges) {
    if (e.edge_type !== "prereq") continue;
    const list = prereqParents.get(e.to_skill_id) ?? [];
    list.push(e.from_skill_id);
    prereqParents.set(e.to_skill_id, list);
  }

  const layerOf = new Map<string, number>();
  const visiting = new Set<string>();

  function depth(id: string): number {
    const cached = layerOf.get(id);
    if (cached !== undefined) return cached;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const parents = prereqParents.get(id) ?? [];
    const d = parents.length === 0 ? 0 : 1 + Math.max(...parents.map(depth));
    visiting.delete(id);
    layerOf.set(id, d);
    return d;
  }

  for (const n of nodes) depth(n.id);

  const byLayer = new Map<number, SkillNode[]>();
  for (const n of nodes) {
    const d = layerOf.get(n.id) ?? 0;
    const bucket = byLayer.get(d) ?? [];
    bucket.push(n);
    byLayer.set(d, bucket);
  }

  const H_SPACING = 240;
  const V_SPACING = 140;
  const out: PositionedNode[] = [];
  for (const [layer, bucket] of byLayer) {
    bucket.sort((a, b) => a.slug.localeCompare(b.slug));
    const offset = -((bucket.length - 1) * H_SPACING) / 2;
    bucket.forEach((n, i) => {
      out.push({
        ...n,
        layer,
        x: offset + i * H_SPACING,
        y: layer * V_SPACING,
      });
    });
  }
  return out;
}

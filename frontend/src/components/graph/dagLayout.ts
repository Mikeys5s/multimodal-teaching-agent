import type { GraphEdge, GraphNode } from '@/lib/types'

/**
 * 手写 DAG 分层布局（不引图形库）。
 *
 * ① **最长路径分层**：node 层级 = 其**所有前置的最深层级 + 1**，由 Kahn 拓扑序保证
 *    算某个节点时它的前置都已定层；入度为 0 的节点落在第 0 层。
 * ② **层内重心排序**：反复用「前驱/后继在当前层内的平均位置」重排同层节点
 *    （下扫 4 轮 + 上扫 4 轮），把连边交叉压下来；孤立节点用自身序号当重心，
 *    排序稳定，不会把无依赖的节点搅乱。
 * ③ 坐标：层 → x（左→右，即先修在前），层内序号 → y，每层整体纵向居中。
 *
 * 布局是**纯函数**，只吃 `GraphNode[]`/`GraphEdge[]`，便于单测与前端筛选后重算。
 */

export const NODE_W = 176
export const NODE_H = 54
/** 层间距 / 同层节点间距 / 画布留白 */
const COL_GAP = 88
const ROW_GAP = 26
const PADDING = 40
/** 重心排序迭代次数 */
const SWEEPS = 4

export interface LayoutNode {
  node: GraphNode
  /** 拓扑层级，0 = 无前置的起点 */
  layer: number
  /** 层内序号 */
  order: number
  /** 节点中心坐标 */
  x: number
  y: number
}

export interface LayoutEdge {
  edge: GraphEdge
  from: LayoutNode
  to: LayoutNode
  /** 指向同层或更浅层 —— 正常情况下不该出现（后端保证无环），画出来是给人看的告警 */
  backEdge: boolean
}

export interface GraphLayout {
  nodes: LayoutNode[]
  edges: LayoutEdge[]
  width: number
  height: number
  layerCount: number
}

const EMPTY_LAYOUT: GraphLayout = { nodes: [], edges: [], width: 0, height: 0, layerCount: 0 }

export function layoutGraph(rawNodes: GraphNode[], rawEdges: GraphEdge[]): GraphLayout {
  if (rawNodes.length === 0) return EMPTY_LAYOUT

  const ids = new Set(rawNodes.map((n) => n.id))
  // 剪掉指向不存在节点的悬挂边，避免整张图画不出来
  const edges = rawEdges.filter((e) => ids.has(e.source) && ids.has(e.target))

  const preds = new Map<string, string[]>()
  const succs = new Map<string, string[]>()
  const indeg = new Map<string, number>()
  for (const n of rawNodes) {
    preds.set(n.id, [])
    succs.set(n.id, [])
    indeg.set(n.id, 0)
  }
  for (const e of edges) {
    succs.get(e.source)?.push(e.target)
    preds.get(e.target)?.push(e.source)
    indeg.set(e.target, (indeg.get(e.target) ?? 0) + 1)
  }

  /* ---------------- ① 最长路径分层（Kahn 拓扑序） ---------------- */
  const layer = new Map<string, number>()
  for (const n of rawNodes) layer.set(n.id, 0)

  const remaining = new Map(indeg)
  const queue = rawNodes.filter((n) => (indeg.get(n.id) ?? 0) === 0).map((n) => n.id)
  const settled: string[] = []

  while (queue.length > 0) {
    const id = queue.shift() as string
    settled.push(id)
    for (const next of succs.get(id) ?? []) {
      layer.set(next, Math.max(layer.get(next) ?? 0, (layer.get(id) ?? 0) + 1))
      const left = (remaining.get(next) ?? 0) - 1
      remaining.set(next, left)
      if (left === 0) queue.push(next)
    }
  }

  // 兜底：后端保证 DAG，但万一有环也不能丢节点 —— 剩下的按「已定层的更深」估一层并继续
  if (settled.length < rawNodes.length) {
    const done = new Set(settled)
    for (const n of rawNodes) {
      if (done.has(n.id)) continue
      const knownPreds = (preds.get(n.id) ?? []).filter((p) => done.has(p))
      layer.set(n.id, knownPreds.length > 0 ? Math.max(...knownPreds.map((p) => layer.get(p) ?? 0)) + 1 : 1)
      done.add(n.id)
    }
  }

  const layerCount = Math.max(...rawNodes.map((n) => layer.get(n.id) ?? 0)) + 1
  const rows: LayoutNode[][] = Array.from({ length: layerCount }, () => [] as LayoutNode[])
  rawNodes.forEach((node, index) => {
    const l = layer.get(node.id) ?? 0
    rows[l].push({ node, layer: l, order: index, x: 0, y: 0 })
  })

  /* ---------------- ② 层内重心排序 ---------------- */
  const position = new Map<string, number>()
  const syncPosition = () => {
    for (const row of rows) row.forEach((item, i) => position.set(item.node.id, i))
  }
  const barycenter = (item: LayoutNode, neighbors: Map<string, string[]>, fallback: number) => {
    const list = neighbors.get(item.node.id) ?? []
    let sum = 0
    let count = 0
    for (const id of list) {
      const idx = position.get(id)
      if (idx !== undefined) {
        sum += idx
        count += 1
      }
    }
    return count === 0 ? fallback : sum / count
  }
  const sortRow = (rowIndex: number, neighbors: Map<string, string[]>) => {
    rows[rowIndex] = rows[rowIndex]
      .map((item, idx) => ({ item, key: barycenter(item, neighbors, idx) }))
      .sort((a, b) => a.key - b.key)
      .map((entry) => entry.item)
    syncPosition()
  }

  syncPosition()
  for (let sweep = 0; sweep < SWEEPS; sweep += 1) {
    // 下扫：按前驱位置排
    for (let i = 1; i < rows.length; i += 1) sortRow(i, preds)
    // 上扫：按后继位置排
    for (let i = rows.length - 2; i >= 0; i -= 1) sortRow(i, succs)
  }

  /* ---------------- ③ 落坐标 ---------------- */
  const rowSpan = NODE_H + ROW_GAP
  let tallest = 0
  for (const row of rows) tallest = Math.max(tallest, row.length * rowSpan - ROW_GAP)
  const height = tallest + PADDING * 2
  const width = PADDING * 2 + layerCount * NODE_W + (layerCount - 1) * COL_GAP

  const nodes: LayoutNode[] = []
  rows.forEach((row, layerIndex) => {
    const rowHeight = row.length * rowSpan - ROW_GAP
    const top = PADDING + (tallest - rowHeight) / 2
    row.forEach((item, order) => {
      item.order = order
      item.x = PADDING + layerIndex * (NODE_W + COL_GAP) + NODE_W / 2
      item.y = top + order * rowSpan + NODE_H / 2
      nodes.push(item)
    })
  })

  const byId = new Map(nodes.map((item) => [item.node.id, item]))
  const layoutEdges: LayoutEdge[] = []
  for (const edge of edges) {
    const from = byId.get(edge.source)
    const to = byId.get(edge.target)
    if (!from || !to) continue
    layoutEdges.push({ edge, from, to, backEdge: to.layer <= from.layer })
  }

  return { nodes, edges: layoutEdges, width, height, layerCount }
}

/** 从节点中心指向目标时，与节点矩形边框的交点（箭头落在框上，而不是压在名字上） */
export function rectBoundary(from: LayoutNode, to: LayoutNode): { x: number; y: number } {
  const dx = to.x - from.x
  const dy = to.y - from.y
  if (dx === 0 && dy === 0) return { x: from.x, y: from.y }
  const tx = dx === 0 ? Number.POSITIVE_INFINITY : NODE_W / 2 / Math.abs(dx)
  const ty = dy === 0 ? Number.POSITIVE_INFINITY : NODE_H / 2 / Math.abs(dy)
  const t = Math.min(Number.isFinite(Math.min(tx, ty)) ? Math.min(tx, ty) : 0, 0.5)
  return { x: from.x + dx * t, y: from.y + dy * t }
}

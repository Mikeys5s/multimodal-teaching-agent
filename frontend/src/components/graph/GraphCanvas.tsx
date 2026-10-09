import { Maximize2, Minus, Plus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'

import { DIFFICULTY_COLOR, DIFFICULTY_LABEL } from '@/lib/format'
import { dupBadgeLabel, kpDisplayTitle, kpRawName, shouldExposeRawName } from '@/lib/kpTitle'
import type { GraphEdge, GraphNode } from '@/lib/types'
import { NODE_H, NODE_W, layoutGraph, rectBoundary } from './dagLayout'

export interface GraphCanvasProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  selectedId: string | null
  onSelect: (id: string | null) => void
}

const MIN_SCALE = 0.1
const MAX_SCALE = 3
const ZOOM_STEP = 1.25
const LABEL_MAX_WIDTH = 116

/** 中文按 12.5px、西文按 7px 估算宽度做截断（SVG <text> 不会自动换行/省略） */
function truncateName(name: string): string {
  let width = 0
  let out = ''
  for (const char of name) {
    const charWidth = /[\u2e80-\u9fff\uff00-\uffef]/.test(char) ? 12.5 : 7
    if (width + charWidth > LABEL_MAX_WIDTH) return `${out}…`
    width += charWidth
    out += char
  }
  return out
}

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

/** 图例用：难度 1–5 */
const DIFFICULTY_LEVELS = [1, 2, 3, 4, 5] as const

/**
 * DAG 画布（纯 SVG 手写，含自实现的平移/缩放，不引图形库）。
 * 边：hard 实线、soft 虚线；节点按 difficulty 取色（见左下角图例）；
 * needs_review 节点用虚线描边 + 右上角琥珀色角标标出。
 */
export function GraphCanvas({ nodes, edges, selectedId, onSelect }: GraphCanvasProps) {
  const layout = useMemo(() => layoutGraph(nodes, edges), [nodes, edges])

  const containerRef = useRef<HTMLDivElement>(null)
  const [view, setView] = useState({ x: 24, y: 24, k: 1 })
  const [hoverId, setHoverId] = useState<string | null>(null)
  /** 键盘焦点所在的节点 —— 用来画一个可见的焦点环（SVG 的 <g> 没有默认焦点样式） */
  const [keyboardId, setKeyboardId] = useState<string | null>(null)
  const drag = useRef({ x: 0, y: 0, moved: 0, active: false })

  /**
   * 适应画布（全景）：整图收进视口。大图时会缩得很小，适合看结构，不适合读文字。
   */
  const fitView = useCallback(() => {
    const el = containerRef.current
    if (!el || layout.width === 0 || layout.height === 0) return
    const k = clamp(Math.min((el.clientWidth - 48) / layout.width, (el.clientHeight - 48) / layout.height), MIN_SCALE, 1.1)
    setView({ k, x: (el.clientWidth - layout.width * k) / 2, y: (el.clientHeight - layout.height * k) / 2 })
  }, [layout])

  /**
   * 初始视图：优先「可读」而非「看全」——
   * 全景缩放若低于 0.5（图很宽），改为 0.5 倍并左对齐到先修起点层，用户向右平移探索；
   * 「适应画布」按钮仍提供全景。
   */
  const fitReadable = useCallback(() => {
    const el = containerRef.current
    if (!el || layout.width === 0 || layout.height === 0) return
    const kFit = Math.min((el.clientWidth - 48) / layout.width, (el.clientHeight - 48) / layout.height)
    if (kFit >= 0.5) {
      fitView()
      return
    }
    const k = clamp(0.5, MIN_SCALE, 1.1)
    setView({
      k,
      x: 24,
      y: Math.max(24, (el.clientHeight - layout.height * k) / 2),
    })
  }, [layout, fitView])

  useEffect(() => {
    fitReadable()
  }, [fitReadable])

  const zoomAt = useCallback((factor: number, cx: number, cy: number) => {
    setView((prev) => {
      const k = clamp(prev.k * factor, MIN_SCALE, MAX_SCALE)
      // 让光标下的世界坐标点在缩放前后保持不动
      const wx = (cx - prev.x) / prev.k
      const wy = (cy - prev.y) / prev.k
      return { k, x: cx - wx * k, y: cy - wy * k }
    })
  }, [])

  const zoomAtCenter = useCallback(
    (factor: number) => {
      const el = containerRef.current
      if (!el) return
      zoomAt(factor, el.clientWidth / 2, el.clientHeight / 2)
    },
    [zoomAt],
  )

  /** 视图是否有节点：从「筛选后为空」回到有节点时，容器是重新挂载的 DOM */
  const hasNodes = nodes.length > 0

  // 滚轮缩放：React 的 onWheel 在部分浏览器上是 passive 的，这里挂原生监听以便 preventDefault
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const rect = el.getBoundingClientRect()
      zoomAt(Math.exp(-event.deltaY * 0.0015), event.clientX - rect.left, event.clientY - rect.top)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomAt, hasNodes])

  const handlePointerDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest('[data-node-id]')) return
    drag.current = { x: event.clientX, y: event.clientY, moved: 0, active: true }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const handlePointerMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!drag.current.active) return
    const dx = event.clientX - drag.current.x
    const dy = event.clientY - drag.current.y
    drag.current.x = event.clientX
    drag.current.y = event.clientY
    drag.current.moved += Math.abs(dx) + Math.abs(dy)
    setView((prev) => ({ ...prev, x: prev.x + dx, y: prev.y + dy }))
  }

  const handlePointerUp = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!drag.current.active) return
    drag.current.active = false
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    // 真正的点击（没怎么移动）才当作「点空白处取消选中」
    if (drag.current.moved < 4) onSelect(null)
  }

  const focusId = hoverId ?? selectedId
  const related = useMemo(() => {
    const set = new Set<string>()
    if (!focusId) return set
    set.add(focusId)
    for (const edge of edges) {
      if (edge.source === focusId) set.add(edge.target)
      if (edge.target === focusId) set.add(edge.source)
    }
    return set
  }, [edges, focusId])

  if (nodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-slate-400">
        当前筛选条件下没有节点，试试清空筛选。
      </div>
    )
  }

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden bg-slate-50/40">
      <svg
        className="h-full w-full cursor-grab touch-none select-none active:cursor-grabbing"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        role="group"
        aria-label="知识点依赖有向无环图：可拖拽平移、滚轮缩放；按 Tab 遍历知识点，Enter 或空格查看前置与例题"
      >
        <defs>
          {/* 硬前置：实心箭头（形态线索 1） */}
          <marker id="xizhi-arrow-hard" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" refX="8.5" refY="4.5" orient="auto">
            <path d="M0 0 L9 4.5 L0 9 z" fill="#64748b" />
          </marker>
          <marker id="xizhi-arrow-hard-active" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" refX="8.5" refY="4.5" orient="auto">
            <path d="M0 0 L9 4.5 L0 9 z" fill="#2563eb" />
          </marker>
          {/* 软前置：空心箭头（与硬前置的形态区分，不靠颜色） */}
          <marker id="xizhi-arrow-soft" markerUnits="userSpaceOnUse" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0.8 0.8 L7.2 4 L0.8 7.2 z" fill="#ffffff" stroke="#94a3b8" strokeWidth="1.2" />
          </marker>
          <marker id="xizhi-arrow-soft-active" markerUnits="userSpaceOnUse" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0.8 0.8 L7.2 4 L0.8 7.2 z" fill="#ffffff" stroke="#2563eb" strokeWidth="1.2" />
          </marker>
        </defs>

        <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
          {/* 边（先画，压在节点下面）。
              硬/软前置用三重线索区分：线型（实线 vs 点线）+ 箭头形态（实心 vs 空心）+ 颜色深浅；
              选中节点时关联边变为品牌蓝加粗，非关联边压淡。 */}
          <g>
            {layout.edges.map(({ edge, from, to, backEdge }) => {
              const a = rectBoundary(from, to)
              const b = rectBoundary(to, from)
              const hard = edge.relation_type === 'hard'
              const relatedEdge = focusId !== null && (edge.source === focusId || edge.target === focusId)
              const dimmed = focusId !== null && !relatedEdge
              const stroke = backEdge
                ? '#ef4444'
                : relatedEdge
                  ? '#2563eb'
                  : hard
                    ? '#64748b'
                    : '#94a3b8'
              return (
                <line
                  key={`${edge.source}->${edge.target}`}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke={stroke}
                  strokeWidth={relatedEdge ? 2.4 : hard ? 1.8 : 1.4}
                  strokeDasharray={backEdge ? '8 4' : hard ? undefined : '2 5'}
                  strokeLinecap={hard && !backEdge ? 'butt' : 'round'}
                  markerEnd={`url(#xizhi-arrow-${hard ? 'hard' : 'soft'}${relatedEdge && !backEdge ? '-active' : ''})`}
                  opacity={dimmed ? 0.12 : 1}
                />
              )
            })}
          </g>

          {/* 节点 */}
          <g>
            {layout.nodes.map(({ node, x, y }) => {
              const color = DIFFICULTY_COLOR[node.difficulty] ?? '#94a3b8'
              const selected = node.id === selectedId
              const focused = node.id === keyboardId
              const dimmed = focusId !== null && !related.has(node.id)
              // 决赛任务 2：节点标签用可读标题（后端未提供时回落 name，行为与改前一致）
              const label = kpDisplayTitle(node)
              const rawName = shouldExposeRawName(node) ? kpRawName(node) : null
              // 决赛任务 1：重复组角标。节点接口当前不带该字段 → 拿不到时为 null，不显示
              const dupLabel = dupBadgeLabel(node)
              return (
                <g
                  key={node.id}
                  data-node-id={node.id}
                  transform={`translate(${x - NODE_W / 2} ${y - NODE_H / 2})`}
                  className="cursor-pointer transition-opacity focus:outline-none"
                  opacity={dimmed ? 0.3 : 1}
                  role="button"
                  tabIndex={0}
                  aria-pressed={selected}
                  aria-label={`知识点 ${label}，难度 ${node.difficulty}（${
                    DIFFICULTY_LABEL[node.difficulty]
                  }）${node.needs_review ? '，待复核' : ''}${
                    dupLabel ? `，${dupLabel}，已合并显示` : ''
                  }，查看前置与例题`}
                  onClick={() => onSelect(node.id)}
                  onKeyDown={(event) => {
                    // Enter / 空格 —— 与原生 button 一致（否则键盘用户点不开详情）
                    if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
                      event.preventDefault()
                      onSelect(node.id)
                    }
                  }}
                  onFocus={() => setKeyboardId(node.id)}
                  onBlur={() => setKeyboardId((prev) => (prev === node.id ? null : prev))}
                  onPointerEnter={() => setHoverId(node.id)}
                  onPointerLeave={() => setHoverId((prev) => (prev === node.id ? null : prev))}
                >
                  <title>
                    {label} · 难度 {node.difficulty}（{DIFFICULTY_LABEL[node.difficulty]}）
                    {node.needs_review ? ' · 待复核' : ''}
                    {dupLabel ? ` · ${dupLabel}，已合并显示` : ''}
                    {rawName ? ` · 原名：${rawName}` : ''}（点击查看前置与例题）
                  </title>
                  {focused && (
                    <rect
                      x={-6}
                      y={-6}
                      width={NODE_W + 12}
                      height={NODE_H + 12}
                      rx={18}
                      fill="none"
                      stroke="#2563eb"
                      strokeWidth={2}
                      strokeDasharray="5 3"
                    />
                  )}
                  {selected && (
                    <rect x={-4} y={-4} width={NODE_W + 8} height={NODE_H + 8} rx={16} fill="none" stroke="#2563eb" strokeWidth={2.5} opacity={0.4} />
                  )}
                  {/* 「地标卡」节点：白底 + 左侧难度色轨 + 难度数字徽章；
                      待复核 = 琥珀虚线描边 + ! 角标（形态+图标+文字三重线索） */}
                  <rect
                    x={0}
                    y={0}
                    width={NODE_W}
                    height={NODE_H}
                    rx={12}
                    fill={selected ? '#eff6ff' : '#ffffff'}
                    stroke={selected ? '#2563eb' : node.needs_review ? '#d97706' : color}
                    strokeWidth={selected ? 2 : 1.4}
                    strokeDasharray={node.needs_review && !selected ? '5 4' : undefined}
                  />
                  <rect x={5} y={7} width={4} height={NODE_H - 14} rx={2} fill={color} />
                  <text x={17} y={NODE_H / 2 + 4.5} fontSize={12.5} fontWeight={500} fill="#0f172a">
                    {truncateName(label)}
                  </text>
                  <rect x={NODE_W - 32} y={NODE_H / 2 - 9} width={20} height={18} rx={6} fill={color} />
                  <text x={NODE_W - 22} y={NODE_H / 2 + 4} fontSize={11} fontWeight={600} fill="#ffffff" textAnchor="middle">
                    {node.difficulty}
                  </text>
                  {node.needs_review && (
                    <g transform={`translate(${NODE_W - 6} -4)`}>
                      <circle r={8.5} fill="#d97706" stroke="#ffffff" strokeWidth={1.5} />
                      <text y={3.5} fontSize={10} fontWeight={700} fill="#ffffff" textAnchor="middle">
                        !
                      </text>
                    </g>
                  )}
                </g>
              )
            })}
          </g>
        </g>
      </svg>

      {/* 缩放控件（触控目标手机 ≥40px） */}
      <div className="absolute right-3 top-3 flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white/95 p-1 shadow-card">
        <button
          className="flex h-10 w-10 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-700 sm:h-7 sm:w-7"
          onClick={() => zoomAtCenter(1 / ZOOM_STEP)}
          aria-label="缩小"
          title="缩小"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <span className="w-11 text-center text-xs tabular-nums text-slate-500">
          {Math.round(view.k * 100)}%
        </span>
        <button
          className="flex h-10 w-10 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-700 sm:h-7 sm:w-7"
          onClick={() => zoomAtCenter(ZOOM_STEP)}
          aria-label="放大"
          title="放大"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button
          className="flex h-10 w-10 items-center justify-center rounded text-slate-500 hover:bg-slate-100 hover:text-slate-700 sm:h-7 sm:w-7"
          onClick={fitView}
          aria-label="适应画布"
          title="适应画布"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="pointer-events-none absolute bottom-3 right-3 hidden rounded-md bg-white/85 px-2 py-1 text-xs text-slate-400 sm:block">
        拖拽平移 · 滚轮缩放 · 点节点看详情 · Tab 遍历节点、Enter 打开
      </div>

      {/* 图例：难度色 + 硬/软前置（线型 + 箭头形态双线索）+ 待复核 */}
      <div className="pointer-events-none absolute bottom-3 left-3 rounded-lg border border-slate-200 bg-white/95 px-3 py-2.5 shadow-card">
        <div className="mb-1.5 text-xs font-medium text-slate-500">节点色轨 = 难度</div>
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          {DIFFICULTY_LEVELS.map((level) => (
            <span key={level} className="flex items-center gap-1 text-xs text-slate-600">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: DIFFICULTY_COLOR[level] }} />
              {level}·{DIFFICULTY_LABEL[level]}
            </span>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-3.5 gap-y-1 text-xs text-slate-600">
          <span className="flex items-center gap-1.5">
            <svg width="22" height="8" aria-hidden>
              <line x1="0" y1="4" x2="16" y2="4" stroke="#64748b" strokeWidth="1.8" />
              <path d="M15 1 L21 4 L15 7 z" fill="#64748b" />
            </svg>
            硬前置（实线实心箭头）
          </span>
          <span className="flex items-center gap-1.5">
            <svg width="22" height="8" aria-hidden>
              <line x1="0" y1="4" x2="15" y2="4" stroke="#94a3b8" strokeWidth="1.4" strokeDasharray="2 4" strokeLinecap="round" />
              <path d="M14.5 1.5 L20 4 L14.5 6.5 z" fill="#ffffff" stroke="#94a3b8" />
            </svg>
            软前置（点线空心箭头）
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded border-[1.5px] border-dashed border-warning bg-warning-soft" />
            待复核
          </span>
        </div>
      </div>
    </div>
  )
}

import { RefreshCw, ShieldCheck, SlidersHorizontal } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { GraphCanvas } from '@/components/graph/GraphCanvas'
import { GraphStatsPanel } from '@/components/graph/GraphStatsPanel'
import { KnowledgePointAside } from '@/components/graph/KnowledgePointAside'
import { KnowledgePointDrawer } from '@/components/graph/KnowledgePointDrawer'
import { ReviewDrawer } from '@/components/graph/ReviewDrawer'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, InlineError, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'
import type { GraphNode } from '@/lib/types'

const MAX_NODES_OPTIONS = [100, 200, 400]
/** 章节下拉的标题来源：知识点列表（图谱节点只带 chapter_id，没有章节名） */
const CHAPTER_PROBE_PAGE_SIZE = 100

/**
 * 知识图谱页（P3 · D7 交付）。
 * 对应路由 /graph 与端点 GET /api/knowledge-graph、GET /api/knowledge-points、
 * GET /api/knowledge-points/{id}（api-spec §4、§8）。
 * 页面主张：把「教学依赖图必须无环」这个工程不变量做成评委可见的信任信号。
 * 构图（Learning Atlas v2）：页头 → 统计顶线条 → 筛选胶囊 → 深蓝画布 + 右侧证据面板（桌面）。
 */
export default function Graph() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [chapterId, setChapterId] = useState('')
  const [maxNodes, setMaxNodes] = useState(200)
  const [reviewOnly, setReviewOnly] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [reviewOpen, setReviewOpen] = useState(false)
  /** 手机端筛选面板折叠（桌面常驻展开） */
  const [filtersOpen, setFiltersOpen] = useState(false)

  /**
   * 深链：`/graph?kp_id=xxx` —— 首页「从这看起 · 看我们怎么处理重复数据」用它直达某个知识点。
   * 详情按 id 单独拉取，**不依赖该节点是否落在当前 200 个之内**，所以这里直接开详情。
   */
  const deepLinkKpId = searchParams.get('kp_id')
  useEffect(() => {
    if (deepLinkKpId) setSelectedId(deepLinkKpId)
  }, [deepLinkKpId])

  const graphReq = useRequest(
    () => api.getKnowledgeGraph({ chapter_id: chapterId || undefined, max_nodes: maxNodes }),
    [chapterId, maxNodes],
  )
  // 章节筛选的服务端参数只吃 chapter_id，标题得从知识点列表里取（失败不影响图谱本身）
  const chapterProbe = useRequest(() => api.listKnowledgePoints({ page_size: CHAPTER_PROBE_PAGE_SIZE }), [])
  // 复核队列条数：决定「人工校验」入口上显示多少条待裁决（空队列时入口仍在，便于口播这条能力）
  const reviewQueueReq = useRequest(() => api.listReviewQueue({ limit: 200 }), [])

  const graph = graphReq.data

  const chapterOptions = useMemo(() => {
    const map = new Map<string, string>()
    for (const kp of chapterProbe.data?.items ?? []) {
      const label = `${kp.chapter.number} ${kp.chapter.title}`.trim()
      if (label && !map.has(kp.chapter.id)) map.set(kp.chapter.id, label)
    }
    for (const node of graph?.nodes ?? []) {
      if (!map.has(node.chapter_id)) map.set(node.chapter_id, node.chapter_id)
    }
    return Array.from(map.entries())
  }, [chapterProbe.data, graph])

  const reviewCount = useMemo(
    () => (graph?.nodes ?? []).filter((node) => node.needs_review).length,
    [graph],
  )

  // 客户端筛选：只看 needs_review；边同步收敛到剩余节点之间
  const viewNodes = useMemo<GraphNode[]>(() => {
    if (!graph) return []
    return reviewOnly ? graph.nodes.filter((node) => node.needs_review) : graph.nodes
  }, [graph, reviewOnly])

  const viewEdges = useMemo(() => {
    if (!graph) return []
    const keep = new Set(viewNodes.map((node) => node.id))
    return graph.edges.filter((edge) => keep.has(edge.source) && keep.has(edge.target))
  }, [graph, viewNodes])

  const filtered = reviewOnly || chapterId !== ''
  const pendingReviewCount = reviewQueueReq.data?.total ?? 0

  const clearFilters = () => {
    setChapterId('')
    setReviewOnly(false)
    setSelectedId(null)
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      {/* 页头：编辑式标题 + 人工复核主操作 */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="atlas-eyebrow">
            <span className="idx">03</span> RELATIONSHIP ATLAS / DAG
          </div>
          <h2 className="atlas-h1 mt-2">知识之间，存在方向。</h2>
          <p className="mt-2 max-w-[560px] text-[13px] leading-relaxed text-atlas-muted">
            从概念、前置与来源构成的关系网中，找到下一步。选中任一节点查看证据。
          </p>
        </div>
        <button
          type="button"
          onClick={() => setReviewOpen(true)}
          className="inline-flex h-11 items-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-semibold text-white shadow-[0_8px_20px_rgba(49,92,255,0.22)] transition-all duration-160 hover:bg-brand-700 hover:-translate-y-0.5"
        >
          <ShieldCheck className="h-4 w-4" aria-hidden />
          人工复核
          {pendingReviewCount > 0 && (
            <span className="rounded-md bg-white/20 px-1.5 py-0.5 text-xs leading-none">
              {pendingReviewCount}
            </span>
          )}
        </button>
      </div>

      {/* 统计顶线条（中文化信任信号） */}
      {graph && (
        <GraphStatsPanel
          stats={graph.stats}
          viewNodeCount={viewNodes.length}
          viewEdgeCount={viewEdges.length}
          filtered={filtered}
        />
      )}

      {graphReq.error && graph && <InlineError>{graphReq.error}</InlineError>}

      {/* 加载 / 错误 / 空态 */}
      {graphReq.loading && !graph && (
        <section className="xizhi-card">
          <LoadingState label="正在加载知识图谱…" />
        </section>
      )}

      {graphReq.error && !graph && (
        <section className="xizhi-card p-4">
          <ErrorState message={graphReq.error} onRetry={() => void graphReq.reload()} />
          <p className="mt-3 text-center text-xs text-slate-400">
            若为首次运行，请确认后端已启动（可访问 /api/health 自检），再点「重试」。
          </p>
        </section>
      )}

      {graph && graph.nodes.length === 0 && (
        <section className="xizhi-card">
          <EmptyState
            title="图谱还是空的"
            description="还没有抽取到知识点。先到素材工作台上传教材并触发知识点抽取，系统会把前置依赖抽成 DAG 后再回到这里。"
            action={<Button onClick={() => navigate('/materials')}>去 /materials 上传素材</Button>}
          />
        </section>
      )}

      {graph && graph.nodes.length > 0 && (
        <>
          {/* 筛选行：胶囊式控件（手机折叠为可展开面板） */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              className="flex min-h-11 items-center gap-1.5 text-xs font-medium text-slate-600 sm:hidden"
              onClick={() => setFiltersOpen((prev) => !prev)}
              aria-expanded={filtersOpen}
              aria-controls="graph-filters"
            >
              <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
              筛选
              {filtered && <span className="rounded-full bg-brand-50 px-1.5 py-0.5 text-xs text-brand-700">已启用</span>}
              <span className="text-slate-400">{filtersOpen ? '▲' : '▼'}</span>
            </button>

            <div
              id="graph-filters"
              className={`flex-wrap items-center gap-2 ${filtersOpen ? 'flex w-full' : 'hidden'} sm:flex sm:w-auto`}
            >
              <label className="inline-flex items-center gap-1.5 rounded-full border border-[#d2ccbf] bg-atlas-sheet px-3 py-1.5 text-xs text-[#536073]">
                章节
                <select
                  value={chapterId}
                  onChange={(event) => {
                    setChapterId(event.target.value)
                    setSelectedId(null)
                  }}
                  aria-label="按章节筛选"
                  className="max-w-[180px] bg-transparent text-xs text-atlas-ink outline-none"
                >
                  <option value="">全部章节</option>
                  {chapterOptions.map(([id, label]) => (
                    <option key={id} value={id}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="inline-flex items-center gap-1.5 rounded-full border border-[#d2ccbf] bg-atlas-sheet px-3 py-1.5 text-xs text-[#536073]">
                节点上限
                <select
                  value={maxNodes}
                  onChange={(event) => {
                    setMaxNodes(Number(event.target.value))
                    setSelectedId(null)
                  }}
                  aria-label="节点上限"
                  className="bg-transparent text-xs text-atlas-ink outline-none"
                >
                  {MAX_NODES_OPTIONS.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>

              <button
                type="button"
                aria-pressed={reviewOnly}
                onClick={() => {
                  setReviewOnly((prev) => !prev)
                  setSelectedId(null)
                }}
                className={[
                  'inline-flex min-h-8 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition-colors duration-120',
                  reviewOnly
                    ? 'border-atlas-ink bg-atlas-ink text-white'
                    : 'border-[#d2ccbf] bg-atlas-sheet text-[#536073] hover:border-[#b7b0a3]',
                ].join(' ')}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-coral" aria-hidden />
                仅看待复核（{reviewCount}）
              </button>

              {filtered && (
                <button
                  className="min-h-8 text-xs text-brand-600 hover:underline"
                  onClick={clearFilters}
                >
                  清空筛选
                </button>
              )}
            </div>

            <Button
              variant="secondary"
              size="sm"
              loading={graphReq.loading}
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              onClick={() => void graphReq.reload()}
            >
              刷新
            </Button>
          </div>

          {/* 画布 + 桌面证据面板 */}
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_300px]">
            <section
              aria-label="知识点依赖有向无环图"
              className="relative h-[62vh] min-h-[420px] overflow-hidden rounded-2xl border border-atlas-ink3 shadow-navy"
            >
              <GraphCanvas
                nodes={viewNodes}
                edges={viewEdges}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            </section>
            <div className="hidden h-[62vh] min-h-[420px] lg:block">
              <KnowledgePointAside kpId={selectedId} onClose={() => setSelectedId(null)} />
            </div>
          </div>
        </>
      )}

      {/* 移动/窄屏：详情走底部抽屉 */}
      {selectedId && (
        <div className="lg:hidden">
          <KnowledgePointDrawer kpId={selectedId} onClose={() => setSelectedId(null)} />
        </div>
      )}

      {reviewOpen && (
        <ReviewDrawer
          onClose={() => {
            setReviewOpen(false)
            void reviewQueueReq.reload()
          }}
          onDecided={() => {
            // 采纳一条候选边后：图重新拉（needs_review 角标会更新），
            // 且因为该边已进正式图，/path 的学习路径会随之变化 —— 这就是纪律④ 要演的因果。
            void graphReq.reload()
            void reviewQueueReq.reload()
          }}
        />
      )}
    </div>
  )
}

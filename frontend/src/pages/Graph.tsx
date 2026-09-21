import { RefreshCw, ShieldCheck, SlidersHorizontal } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { GraphCanvas } from '@/components/graph/GraphCanvas'
import { GraphStatsPanel } from '@/components/graph/GraphStatsPanel'
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
 */
export default function Graph() {
  const navigate = useNavigate()

  const [chapterId, setChapterId] = useState('')
  const [maxNodes, setMaxNodes] = useState(200)
  const [reviewOnly, setReviewOnly] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [reviewOpen, setReviewOpen] = useState(false)

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

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      {/* 筛选栏 */}
      <section className="xizhi-card flex flex-wrap items-center gap-x-5 gap-y-3 px-4 py-3">
        <div className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
          <SlidersHorizontal className="h-3.5 w-3.5" aria-hidden />
          筛选
        </div>

        <label className="flex items-center gap-2 text-xs text-slate-500">
          章节
          <select
            value={chapterId}
            onChange={(event) => {
              setChapterId(event.target.value)
              setSelectedId(null)
            }}
            className="h-8 rounded-lg border border-slate-300 bg-white px-2 text-xs text-slate-700"
          >
            <option value="">全部章节</option>
            {chapterOptions.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2 text-xs text-slate-500">
          节点上限
          <select
            value={maxNodes}
            onChange={(event) => {
              setMaxNodes(Number(event.target.value))
              setSelectedId(null)
            }}
            className="h-8 rounded-lg border border-slate-300 bg-white px-2 text-xs text-slate-700"
          >
            {MAX_NODES_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>

        <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-600">
          <input
            type="checkbox"
            checked={reviewOnly}
            onChange={(event) => {
              setReviewOnly(event.target.checked)
              setSelectedId(null)
            }}
            className="h-3.5 w-3.5 accent-amber-500"
          />
          只看待复核节点（{reviewCount}）
        </label>

        {/* 人工校验入口 —— 主创新点「AI 预抽取 + 人工校验」的可点击证据（见 ReviewDrawer 注释） */}
        <button
          type="button"
          onClick={() => setReviewOpen(true)}
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-brand-200 bg-brand-50 px-2.5 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-100"
        >
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
          人工校验
          {pendingReviewCount > 0 && (
            <span className="rounded-full bg-brand-600 px-1.5 py-0.5 text-[11px] leading-none text-white">
              {pendingReviewCount}
            </span>
          )}
        </button>

        {filtered && (
          <button
            className="text-xs text-brand-600 hover:underline"
            onClick={() => {
              setChapterId('')
              setReviewOnly(false)
              setSelectedId(null)
            }}
          >
            清空筛选
          </button>
        )}
      </section>

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
          <GraphStatsPanel
            stats={graph.stats}
            viewNodeCount={viewNodes.length}
            viewEdgeCount={viewEdges.length}
            filtered={filtered}
          />

          <section className="xizhi-card overflow-hidden">
            <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
              <div className="flex items-baseline gap-3">
                <h2 className="text-sm font-semibold text-slate-800">知识点依赖 DAG</h2>
                <span className="text-xs text-slate-400">
                  节点按拓扑层级自左向右排布（先修在左）· 当前视图 {viewNodes.length} 个知识点 /{' '}
                  {viewEdges.length} 条边
                </span>
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
            </header>

            <div className="h-[560px] w-full">
              <GraphCanvas
                nodes={viewNodes}
                edges={viewEdges}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            </div>
          </section>
        </>
      )}

      {selectedId && <KnowledgePointDrawer kpId={selectedId} onClose={() => setSelectedId(null)} />}

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

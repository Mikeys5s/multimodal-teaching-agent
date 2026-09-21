import { AlertTriangle, Check, GitBranch, ShieldCheck, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'
import { formatScore } from '@/lib/format'
import type { ReviewDecision, ReviewEdgeItem } from '@/lib/types'

const CHANNEL_LABEL: Record<string, string> = {
  structure: '结构线索',
  semantic: '语义通道',
  both: '双通道（结构 + 语义）',
}

const RELATION_LABEL: Record<string, string> = {
  hard: '硬前置（不会就学不动）',
  soft: '软前置（有帮助，非必需）',
}

export interface ReviewDrawerProps {
  onClose: () => void
  /** 每次裁决成功后调用 —— 让 /graph 重新拉图，做到「采纳后图与路径随之变化」 */
  onDecided: () => void
}

/**
 * 人工校验工作台（复核抽屉）—— 主创新点「**AI 预抽取 + 人工校验**」的可点击证据。
 *
 * ## 为什么它必须存在
 *
 * 后端 `/api/review/*` 三个端点在 #51 就绪，但**前端一直没有消费它们** →
 * `docs/deliverable-plan.md` 纪律④ 要求的「导入候选边 → 采纳一条 → 学习路径随之变化」
 * 只能用 Swagger 演，而那句正是答辩口径「**AI 干粗活 + 人做裁决**」的可视证据。
 *
 * ## 三段式里的第三段
 *
 * ```
 * ① 构建期（离线）  LearnBuddy / 本地 3B 判"真前置" → 候选硬边
 * ② 导入（运行期）  POST /api/review/import-edges  → 一律 needs_review=1（**候选，不是结论**）
 * ③ 人工裁决（就是这里）
 *      采纳 → needs_review=0，进正式图  → 学习路径随之变化
 *      驳回 → pruned=1（**软删除，留痕**）→ 队列里消失，但边还在，可追溯"人做过判断"
 * ```
 *
 * ## 一个刻意的设计：驳回不物理删除
 *
 * 答辩时说「**我们检出了 N 条不合理依赖，并由人驳回**」比「图很干净」更有说服力 ——
 * 前者是过程证据，后者只是一个状态。所以驳回后我**不把它从页面上抹掉**，
 * 而是就地标成「已驳回」并在本次会话内保留（刷新后才会消失，符合后端语义）。
 */
export function ReviewDrawer({ onClose, onDecided }: ReviewDrawerProps) {
  const queueReq = useRequest(() => api.listReviewQueue({ limit: 200 }), [])
  const [pending, setPending] = useState<string | null>(null)
  /**
   * 驳回原因**按行存**（key = `prereq->kp`）。
   *
   * ⚠️ 不能用单个 `note` state：那样 A 行输入的字会同时出现在 B 行的输入框里，
   * 驳回 B 行时还会把 A 行写的原因带过去 —— 一份理由挂到错误的边上，
   * 而这一幕恰好会出现在录制镜头里。（9/21 自查时发现并修掉。）
   */
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  /** 本次会话内已裁决的边（复合键 → 结果）—— 用于「就地留痕」，不抹掉证据 */
  const [done, setDone] = useState<Record<string, ReviewDecision>>({})
  const [acceptedCount, setAcceptedCount] = useState(0)
  const [rejectedCount, setRejectedCount] = useState(0)

  const keyOf = (item: ReviewEdgeItem) => `${item.prereq_kp_id}->${item.kp_id}`

  const items = useMemo(() => queueReq.data?.items ?? [], [queueReq.data])
  const remaining = items.filter((item) => !done[keyOf(item)])

  async function decide(item: ReviewEdgeItem, decision: ReviewDecision) {
    const key = keyOf(item)
    setPending(key)
    setError(null)
    // 只取**本行**的备注 —— 这就是按行存的理由
    const note = (notes[key] ?? '').trim()
    try {
      await api.decideReviewEdge({
        kp_id: item.kp_id,
        prereq_kp_id: item.prereq_kp_id,
        decision,
        note: decision === 'reject' && note ? note : undefined,
      })
      setDone((prev) => ({ ...prev, [key]: decision }))
      setNotes((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
      if (decision === 'accept') setAcceptedCount((n) => n + 1)
      else setRejectedCount((n) => n + 1)
      // 关键：让外层的图重新拉一次 —— 采纳一条 hard 边后，/path 的学习路径会随之变化
      onDecided()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setPending(null)
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />

      <div className="relative flex h-full w-[560px] max-w-full flex-col border-l border-slate-200 bg-white shadow-2xl">
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
              <ShieldCheck className="h-4 w-4 text-brand-600" aria-hidden />
              人工校验 · 复核队列
            </h2>
            <p className="mt-1 text-xs text-slate-400">
              候选依赖边必须由人采纳才进正式图 —— 这就是「AI 干粗活 + 人做裁决」里的裁决。
            </p>
          </div>
          <button
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            onClick={onClose}
            aria-label="关闭复核队列"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        {/* 本次会话的裁决统计 —— 视频里一眼能看到「人做了几次判断」 */}
        {(acceptedCount > 0 || rejectedCount > 0) && (
          <div className="flex shrink-0 items-center gap-4 border-b border-slate-100 bg-slate-50/70 px-5 py-2 text-xs">
            <span className="text-emerald-700">本次已采纳 {acceptedCount} 条</span>
            <span className="text-rose-700">本次已驳回 {rejectedCount} 条</span>
            <span className="text-slate-400">图与学习路径已随之刷新</span>
          </div>
        )}

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {queueReq.loading && !queueReq.data && <LoadingState label="正在取复核队列…" />}

          {queueReq.error && !queueReq.data && (
            <ErrorState message={queueReq.error} onRetry={() => void queueReq.reload()} />
          )}

          {queueReq.data && items.length === 0 && (
            <EmptyState
              title="复核队列是空的"
              description="图上没有未经人确认的依赖。要么候选边已经全部裁决完，要么这一批还没有导入 —— 候选边由构建期（离线）产出后经 /api/review/import-edges 导入。"
            />
          )}

          {items.length > 0 && (
            <>
              <div className="mb-3 flex items-center justify-between text-xs text-slate-500">
                <span>
                  队列共 {queueReq.data?.total ?? items.length} 条，本页待处理{' '}
                  <span className="font-medium text-slate-700">{remaining.length}</span> 条
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  loading={queueReq.loading}
                  onClick={() => void queueReq.reload()}
                >
                  重新拉取
                </Button>
              </div>

              {error && (
                <div className="mb-3 flex items-start gap-2 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span>裁决失败：{error}</span>
                </div>
              )}

              <ul className="space-y-3">
                {items.map((item) => {
                  const key = keyOf(item)
                  const decided = done[key]
                  const busy = pending === key
                  return (
                    <li
                      key={key}
                      className={[
                        'rounded-xl border p-3 transition',
                        decided === 'accept'
                          ? 'border-emerald-200 bg-emerald-50/50'
                          : decided === 'reject'
                            ? 'border-rose-200 bg-rose-50/40'
                            : 'border-slate-200',
                      ].join(' ')}
                    >
                      {/* 依赖方向：前置 → 后置。用箭头而不是文字，避免读反 */}
                      <div className="flex flex-wrap items-center gap-1.5 text-sm">
                        <span className="font-medium text-slate-700">{item.prereq_name || item.prereq_kp_id}</span>
                        <span className="text-slate-400">→</span>
                        <span className="font-medium text-slate-700">{item.kp_name || item.kp_id}</span>
                        <span
                          className={[
                            'ml-1 rounded-full px-2 py-0.5 text-[11px]',
                            item.relation_type === 'hard'
                              ? 'bg-brand-50 text-brand-700'
                              : 'bg-slate-100 text-slate-500',
                          ].join(' ')}
                        >
                          {RELATION_LABEL[item.relation_type] ?? item.relation_type}
                        </span>
                      </div>

                      <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{item.reason || '（无理由）'}</p>

                      {item.evidence_quote && (
                        <blockquote className="mt-1.5 border-l-2 border-slate-200 pl-2 text-[11px] leading-relaxed text-slate-500">
                          {item.evidence_quote}
                        </blockquote>
                      )}

                      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
                        <span className="inline-flex items-center gap-1">
                          <GitBranch className="h-3 w-3" aria-hidden />
                          {CHANNEL_LABEL[item.source_channel] ?? item.source_channel}
                        </span>
                        <span>
                          置信度 {item.confidence == null ? '未给' : formatScore(item.confidence)}
                        </span>
                        {item.kind !== 'edge' && <span>类型 {item.kind}</span>}
                      </div>

                      {decided ? (
                        <p
                          className={[
                            'mt-2 text-xs font-medium',
                            decided === 'accept' ? 'text-emerald-700' : 'text-rose-700',
                          ].join(' ')}
                        >
                          {decided === 'accept'
                            ? '✓ 已采纳 —— 该依赖已进入正式图，学习路径随之变化'
                            : '× 已驳回 —— 保留为「人做过判断」的证据（软删除，不物理删除）'}
                        </p>
                      ) : (
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <Button
                            size="sm"
                            loading={busy}
                            icon={<Check className="h-3.5 w-3.5" />}
                            onClick={() => void decide(item, 'accept')}
                          >
                            采纳进正式图
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={busy}
                            icon={<X className="h-3.5 w-3.5" />}
                            onClick={() => void decide(item, 'reject')}
                          >
                            驳回
                          </Button>
                          <input
                            value={notes[key] ?? ''}
                            onChange={(event) =>
                              setNotes((prev) => ({ ...prev, [key]: event.target.value }))
                            }
                            placeholder="驳回原因（可选，会写进理由里便于追溯）"
                            className="h-8 min-w-[200px] flex-1 rounded-lg border border-slate-300 px-2 text-xs text-slate-700"
                          />
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </div>

        <footer className="shrink-0 border-t border-slate-100 px-5 py-3 text-[11px] leading-relaxed text-slate-400">
          导入时已做环校验：会让依赖图成环的候选边整批拒收，所以这里采纳任何一条都不会引入环
          —— 「教学依赖图必须无环」是工程不变量，不靠人工把关。
        </footer>
      </div>
    </div>
  )
}

import { CornerDownRight, RefreshCw } from 'lucide-react'
import { useMemo } from 'react'

import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/Feedback'
import { KpIdChip } from '@/components/ui/KpIdChip'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'
import { DIFFICULTY_LABEL, difficultyColor } from '@/lib/format'
import { kpDisplayTitle, kpTitleAttr } from '@/lib/kpTitle'
import type { Difficulty, LearningPathStep } from '@/lib/types'

export interface PathTimelineProps {
  kpId: string
  kpName: string
  /** 把路径上的某一步设为新的目标知识点，继续往前/往后看 */
  onRetarget: (kpId: string, kpName: string) => void
}

interface PathSummary {
  total: number
  startPoints: number
  minDifficulty: Difficulty
  maxDifficulty: Difficulty
  /** 本条路径是否**所有**步骤都没拿到后端 reason —— 决定“排序依据”怎么措辞 */
  allReasonMissing: boolean
}

function summarize(steps: LearningPathStep[]): PathSummary {
  let minDifficulty: Difficulty = 5
  let maxDifficulty: Difficulty = 1
  let startPoints = 0
  let reasonCount = 0
  for (const step of steps) {
    if (step.difficulty < minDifficulty) minDifficulty = step.difficulty
    if (step.difficulty > maxDifficulty) maxDifficulty = step.difficulty
    if (step.is_start_point) startPoints += 1
    if (step.reason && step.reason.trim() !== '') reasonCount += 1
  }
  return {
    total: steps.length,
    startPoints,
    minDifficulty,
    maxDifficulty,
    allReasonMissing: steps.length > 0 && reasonCount === 0,
  }
}

/**
 * 学习路径时间线（api-spec §4.4「地图与路径」）。
 *
 * 三条不可省略的呈现约定：
 *   ① 按 `order` 编号自上而下排列 —— 顺序本身就是结论；
 *   ② 每一步的 `reason` 有则**逐条展示**（来自 P10 产出在硬前置边上的 reason），
 *      让「为什么它排在前面」可解释；reason 缺失时**不编造**，
 *      改说一句由路径顺序本身可核对的话（本步须先于下一步），并在顶部一次性披露；
 *   ③ `is_start_point` 是拓扑排序里入度为 0 的节点，用独立徽标 + 底色标出。
 */
export function PathTimeline({ kpId, kpName, onRetarget }: PathTimelineProps) {
  const pathReq = useRequest(() => api.getLearningPath(kpId), [kpId])
  const steps = pathReq.data ?? []

  const summary = useMemo(() => summarize(steps), [steps])

  return (
    <div className="flex min-h-0 flex-col">
      {/* 面板头：目标与汇总 */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-atlas-line px-5 py-3.5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <h3 className="text-base font-semibold leading-6 text-atlas-ink">学习路径</h3>
            <span className="truncate text-xs text-atlas-muted" title={kpName}>
              目标：{kpName}
            </span>
          </div>
          {steps.length > 0 && (
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-atlas-muted">
              <span>共 {summary.total} 步</span>
              <span className="text-slate-300">|</span>
              <span>其中 {summary.startPoints} 个起点</span>
              <span className="text-slate-300">|</span>
              <span title="路径沿硬前置依赖反向回溯后做拓扑排序，先修在前、后修在后">
                顺序：先修 → 后修
              </span>
              <span className="text-slate-300">|</span>
              <span>
                难度 {summary.minDifficulty}–{summary.maxDifficulty}
                {summary.minDifficulty === summary.maxDifficulty
                  ? `（${DIFFICULTY_LABEL[summary.minDifficulty]}）`
                  : ''}
              </span>
            </div>
          )}
        </div>
        <Button
          variant="secondary"
          size="sm"
          className="shrink-0"
          loading={pathReq.loading}
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={() => void pathReq.reload()}
        >
          刷新
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {pathReq.error && <ErrorState message={pathReq.error} onRetry={() => void pathReq.reload()} />}

        {!pathReq.error && pathReq.loading && steps.length === 0 && (
          <LoadingState label="正在回溯硬前置并做拓扑排序…" />
        )}

        {!pathReq.error && !pathReq.loading && steps.length === 0 && (
          <EmptyState
            title="这个知识点没有可回溯的前置路径"
            description="它本身可能就是一个零前置的起点，或者前置关系还没有被抽取出来。可以换一个目标知识点，或到「图谱」页确认依赖边是否已生成。"
          />
        )}

        {steps.length > 0 && (
          <>
            {/* 诚实披露：reason 全缺时只在这里说一次，不逐条喊"质量有问题"。
                实测口径（2026-10-10）：11 条多步路径 / 26 步，reason 非空 0 —— 是后端口径，不是单点缺陷。 */}
            {summary.allReasonMissing && steps.length > 1 && (
              <p className="mb-4 rounded-lg border border-atlas-line bg-atlas-paper px-3 py-2 text-xs leading-relaxed text-slate-500">
                本路径每一步的「排序依据」（后端 <span className="font-mono">reason</span>）当前未返回 ——
                顺序由硬前置依赖的拓扑排序确定，下面每步标注的是<span className="text-slate-600">可核对的先后关系</span>
                （本步须先于下一步）；后端补上 <span className="font-mono">reason</span> 后会自动改回原文展示。
              </p>
            )}

            <ol className="relative">
              {steps.map((step, index) => {
                const color = difficultyColor(step.difficulty)
                const isTarget = index === steps.length - 1
                const nextStep = index < steps.length - 1 ? steps[index + 1] : null
                return (
                  <li
                    key={step.kp_id}
                    className="xizhi-rise relative grid grid-cols-[46px_minmax(0,1fr)] gap-3.5 pb-5 last:pb-0 sm:grid-cols-[46px_minmax(0,1fr)_auto]"
                    style={{ animationDelay: `${Math.min(index * 80, 640)}ms` }}
                  >
                    {/* 连接线 */}
                    {index < steps.length - 1 && (
                      <span className="absolute bottom-0 left-[22px] top-[46px] w-px bg-[#c7c0b3]" aria-hidden />
                    )}
                    {/* 序号圆牌（里程碑）：起点=绿、目标=深蓝底荧光字 */}
                    <span
                      className={[
                        'relative z-10 grid h-[46px] w-[46px] place-items-center rounded-full border font-serif text-lg italic',
                        isTarget
                          ? 'border-2 border-brand-600 bg-atlas-ink text-lime shadow-[0_0_0_5px_#dfe7ff]'
                          : step.is_start_point
                            ? 'border-[#84b09b] bg-[#e2f0e8] text-[#2d815e]'
                            : 'border-[#c8c0b1] bg-atlas-sheet text-[#7c858d]',
                      ].join(' ')}
                      title={`第 ${step.order} 步 / 共 ${steps.length} 步`}
                      aria-label={`路径第 ${step.order} 步，共 ${steps.length} 步`}
                    >
                      {String(step.order).padStart(2, '0')}
                    </span>

                    {/* 步骤主文 */}
                    <div className="min-w-0 border-b border-[#ebe5d9] pb-4 [.xizhi-rise:last-child_&]:border-0">
                      <div className="text-[10px] uppercase tracking-[0.1em] text-[#82909a]">
                        {isTarget ? 'LEARNING TARGET / 目标' : step.is_start_point ? 'START / 起点' : 'PREREQUISITE / 先修'}
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span
                          className="text-sm font-semibold tracking-tight text-atlas-ink"
                          title={kpTitleAttr(step)}
                        >
                          {kpDisplayTitle(step)}
                        </span>
                        <span
                          className="rounded-full px-2 py-0.5 text-xs font-medium"
                          style={{ color, backgroundColor: `${color}14`, border: `1px solid ${color}40` }}
                        >
                          难度 {step.difficulty} · {DIFFICULTY_LABEL[step.difficulty]}
                        </span>
                      </div>

                      {/* 排序依据：后端给了 reason 就原样展示；缺失时给可核对的先后关系 */}
                      <p className="mt-1.5 text-xs leading-relaxed text-slate-600">
                        {step.reason ? (
                          <>
                            <span className="font-medium text-slate-500">排序依据：</span>
                            {step.reason}
                          </>
                        ) : nextStep ? (
                          <>
                            本步是第 {nextStep.order} 步「{kpDisplayTitle(nextStep)}」的先修 —— 未学完本步，下一步不成立。
                          </>
                        ) : (
                          <>路径终点：完成本步即可学当前目标知识点。</>
                        )}
                      </p>
                    </div>

                    {/* 右列元信息：溯源锚 + 设为目标 */}
                    <div className="col-start-2 flex items-center gap-2 sm:col-start-auto sm:flex-col sm:items-end sm:justify-start sm:pt-1">
                      <KpIdChip kpId={step.kp_id} />
                      <button
                        type="button"
                        className="inline-flex min-h-11 items-center gap-1 text-xs text-brand-600 hover:underline sm:min-h-0"
                        title="以这一步为新的目标知识点，重新生成路径"
                        onClick={() => onRetarget(step.kp_id, kpDisplayTitle(step))}
                      >
                        <CornerDownRight className="h-3 w-3" aria-hidden />
                        设为目标
                      </button>
                    </div>
                  </li>
                )
              })}
            </ol>
          </>
        )}
      </div>
    </div>
  )
}

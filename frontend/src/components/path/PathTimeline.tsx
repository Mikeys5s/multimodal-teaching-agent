import { CornerDownRight, Flag, RefreshCw, Target } from 'lucide-react'
import { useMemo } from 'react'

import { Badge } from '@/components/ui/Badge'
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

export function PathTimeline({ kpId, kpName, onRetarget }: PathTimelineProps) {
  const pathReq = useRequest(() => api.getLearningPath(kpId), [kpId])
  const steps = pathReq.data ?? []

  const summary = useMemo(() => summarize(steps), [steps])

  return (
    <section className="xizhi-card">
      <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <h2 className="text-base font-semibold leading-6 text-slate-800">学习路径时间线</h2>
            <span className="truncate text-xs text-slate-400" title={kpName}>
              目标：{kpName}
            </span>
          </div>
          {steps.length > 0 && (
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
              <span>共 {summary.total} 步</span>
              <span className="text-slate-300">|</span>
              <span>其中 {summary.startPoints} 个起点</span>
              <span className="text-slate-300">|</span>
              <span title="路径沿硬前置依赖反向回溯后做拓扑排序，先修在前、后修在后">
                顺序：先修 → 后修
              </span>
              <span className="text-slate-300">|</span>
              <span>
                难度范围 {summary.minDifficulty}–{summary.maxDifficulty}
                {summary.minDifficulty === summary.maxDifficulty
                  ? `（${DIFFICULTY_LABEL[summary.minDifficulty]}）`
                  : `（${DIFFICULTY_LABEL[summary.minDifficulty]} → ${DIFFICULTY_LABEL[summary.maxDifficulty]}）`}
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
      </header>

      <div className="p-4">
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
              <p className="mb-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-500">
                本路径每一步的「排序依据」（后端 <span className="font-mono">reason</span>）当前未返回 ——
                顺序由硬前置依赖的拓扑排序确定，下面每步标注的是<span className="text-slate-600">可核对的先后关系</span>
                （本步须先于下一步）；后端补上 <span className="font-mono">reason</span> 后会自动改回原文展示。
              </p>
            )}
            <ol className="relative space-y-2.5">
            {steps.map((step, index) => {
              const color = difficultyColor(step.difficulty)
              const isTarget = index === steps.length - 1
              const nextStep = index < steps.length - 1 ? steps[index + 1] : null
              return (
                <li
                  key={step.kp_id}
                  className="xizhi-rise relative pl-11"
                  style={{ animationDelay: `${Math.min(index * 60, 600)}ms` }}
                >
                  {/* 节点序号（里程碑）：语义 = 第 N 步 / 共 M 步 */}
                  <span
                    className="absolute left-0 top-2 flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold tabular-nums"
                    title={`第 ${step.order} 步 / 共 ${steps.length} 步`}
                    aria-label={`路径第 ${step.order} 步，共 ${steps.length} 步`}
                    style={
                      isTarget
                        ? { color: '#ffffff', backgroundColor: '#2563eb', borderColor: '#2563eb' }
                        : { color, backgroundColor: `${color}14`, borderColor: `${color}66` }
                    }
                  >
                    {step.order}
                  </span>
                  {/* 连接线 */}
                  {index < steps.length - 1 && (
                    <span className="absolute left-[13px] top-9 bottom-[-14px] w-px bg-slate-200" aria-hidden />
                  )}

                  <div
                    className={[
                      'rounded-lg border px-3 py-2.5',
                      isTarget
                        ? 'border-brand-500 bg-brand-50/50 ring-1 ring-brand-200'
                        : step.is_start_point
                          ? 'border-warning-line bg-warning-soft'
                          : 'border-slate-200 bg-white',
                    ].join(' ')}
                  >
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      {/* 决赛任务 2：路径步骤名同样走可读标题；原名收进 title 悬停可见 */}
                      <span
                        className="text-sm font-medium text-slate-800"
                        title={kpTitleAttr(step)}
                      >
                        {kpDisplayTitle(step)}
                      </span>
                      {isTarget && (
                        <Badge color="#1d4ed8" dot>
                          目标
                        </Badge>
                      )}
                      {step.is_start_point && (
                        <Badge color="#92400e" dot>
                          起点
                        </Badge>
                      )}
                      <Badge color={color}>
                        难度 {step.difficulty} · {DIFFICULTY_LABEL[step.difficulty]}
                      </Badge>
                      <button
                        type="button"
                        className="ml-auto inline-flex min-h-11 items-center gap-1 text-xs text-brand-600 hover:underline sm:min-h-0"
                        title="以这一步为新的目标知识点，重新生成路径"
                        onClick={() => onRetarget(step.kp_id, kpDisplayTitle(step))}
                      >
                        <CornerDownRight className="h-3 w-3" aria-hidden />
                        设为目标
                      </button>
                    </div>

                    {/* 排序依据：后端给了 reason 就原样展示；
                        reason 缺失时**不编造、也不每步喊"质量有问题"** ——
                        改说一句由路径顺序本身可核对的话（本步须先于下一步）。 */}
                    <p className="mt-1.5 text-xs leading-relaxed text-slate-600">
                      <span className="font-medium text-slate-500">
                        {step.reason ? '排序依据：' : '先后关系：'}
                      </span>
                      {step.reason ? (
                        step.reason
                      ) : nextStep ? (
                        <>
                          本步是第 {nextStep.order} 步「{kpDisplayTitle(nextStep)}」的先修 —— 未学完本步，下一步不成立。
                        </>
                      ) : (
                        <>路径终点：完成本步即可学当前目标知识点。</>
                      )}
                    </p>

                    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-400">
                      {/* 方案 C②：kp_id 降级为行尾可查小标签（悬停见完整 id、点击复制） */}
                      <KpIdChip kpId={step.kp_id} />
                      {step.is_start_point && (
                        <span className="inline-flex items-center gap-1 text-warning">
                          <Flag className="h-3 w-3" aria-hidden />
                          入度为 0，可从零基础起步
                        </span>
                      )}
                      {isTarget && (
                        <span className="inline-flex items-center gap-1 text-brand-700">
                          <Target className="h-3 w-3" aria-hidden />
                          当前学习目标
                        </span>
                      )}
                    </div>
                  </div>
                </li>
              )
            })}
            </ol>
          </>
        )}
      </div>
    </section>
  )
}

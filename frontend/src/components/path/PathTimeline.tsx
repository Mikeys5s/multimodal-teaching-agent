import { CornerDownRight, Flag, RefreshCw } from 'lucide-react'
import { useMemo } from 'react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'
import { DIFFICULTY_LABEL, difficultyColor } from '@/lib/format'
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
}

function summarize(steps: LearningPathStep[]): PathSummary {
  let minDifficulty: Difficulty = 5
  let maxDifficulty: Difficulty = 1
  let startPoints = 0
  for (const step of steps) {
    if (step.difficulty < minDifficulty) minDifficulty = step.difficulty
    if (step.difficulty > maxDifficulty) maxDifficulty = step.difficulty
    if (step.is_start_point) startPoints += 1
  }
  return { total: steps.length, startPoints, minDifficulty, maxDifficulty }
}

/**
 * 学习路径时间线（api-spec §4.4「地图与路径」）。
 *
 * 三条不可省略的呈现约定：
 *   ① 按 `order` 编号自上而下排列 —— 顺序本身就是结论；
 *   ② 每一步的 `reason` **逐条展示**（来自 P10 产出在硬前置边上的 reason），
 *      让「为什么它排在前面」可解释，而不是黑盒拓扑排序的结果；
 *   ③ `is_start_point` 是拓扑排序里入度为 0 的节点，用独立徽标 + 底色标出，
 *      让「这里可以零基础起步」在界面上一眼可见。
 */
export function PathTimeline({ kpId, kpName, onRetarget }: PathTimelineProps) {
  const pathReq = useRequest(() => api.getLearningPath(kpId), [kpId])
  const steps = pathReq.data ?? []

  const summary = useMemo(() => summarize(steps), [steps])

  return (
    <section className="xizhi-card">
      <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-3">
            <h2 className="text-sm font-semibold text-slate-800">学习路径时间线</h2>
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
          <ol className="relative space-y-2.5">
            {steps.map((step, index) => {
              const color = difficultyColor(step.difficulty)
              return (
                <li key={step.kp_id} className="relative pl-11">
                  {/* 节点序号 */}
                  <span
                    className="absolute left-0 top-2 flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold tabular-nums"
                    style={{ color, backgroundColor: `${color}14`, borderColor: `${color}66` }}
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
                      step.is_start_point ? 'border-amber-200 bg-amber-50/60' : 'border-slate-200 bg-white',
                    ].join(' ')}
                  >
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="text-sm font-medium text-slate-800">{step.name}</span>
                      {step.is_start_point && (
                        <Badge color="#f59e0b" dot>
                          起点
                        </Badge>
                      )}
                      <Badge color={color}>
                        难度 {step.difficulty} · {DIFFICULTY_LABEL[step.difficulty]}
                      </Badge>
                      <button
                        type="button"
                        className="ml-auto inline-flex items-center gap-1 text-[11px] text-brand-600 hover:underline"
                        title="以这一步为新的目标知识点，重新生成路径"
                        onClick={() => onRetarget(step.kp_id, step.name)}
                      >
                        <CornerDownRight className="h-3 w-3" aria-hidden />
                        设为目标
                      </button>
                    </div>

                    {/* reason 逐条展示：排序可解释的关键，不省略、不折叠 */}
                    <p className="mt-1.5 text-xs leading-relaxed text-slate-600">
                      <span className="font-medium text-slate-500">排序依据：</span>
                      {step.reason ? (
                        step.reason
                      ) : (
                        <span className="text-slate-400">后端未给出这一步的排序依据，建议复核该前置边的质量。</span>
                      )}
                    </p>

                    <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
                      <span className="font-mono">{step.kp_id}</span>
                      {step.is_start_point && (
                        <span className="inline-flex items-center gap-1 text-amber-700">
                          <Flag className="h-3 w-3" aria-hidden />
                          入度为 0，可从零基础起步
                        </span>
                      )}
                    </div>
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </div>
    </section>
  )
}

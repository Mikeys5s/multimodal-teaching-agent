import { RefreshCw, Workflow } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { InlineError, Spinner } from '@/components/ui/Feedback'
import type { QaState } from '@/lib/types'

import { MAX_HINT_LEVEL, SOCRATIC_LADDER, SOCRATIC_STATE_COLOR, SOCRATIC_STATE_LABEL, TURN_TYPE_LABEL } from './labels'

/** 小圆点进度：索引小于等于 current 的为「已到达」 */
function Dots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: total + 1 }, (_, index) => (
        <span
          key={index}
          className={[
            'h-2 w-2 rounded-full',
            index <= current ? 'bg-brand-600' : 'border border-slate-300 bg-white',
          ].join(' ')}
        />
      ))}
    </div>
  )
}

/**
 * 苏格拉底状态机可视化 —— 数据来自 `GET /api/qa/sessions/{id}/state`。
 *
 * api-spec §5.3 明确写了这个面板的意义：状态机是产品核心差异化，
 * 但它是「看不见的逻辑」；把它暴露成接口 + 可视化，策略才「看得见」。
 */
export function StateMachinePanel({
  state,
  loading,
  error,
  enabled,
  onRefresh,
}: {
  state: QaState | null
  loading: boolean
  error: string | null
  enabled: boolean
  onRefresh: () => void
}) {
  const reachedIndex = state ? SOCRATIC_LADDER.findIndex((step) => step.state === state.state) : -1

  return (
    <section className="xizhi-card">
      <header className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <Workflow className="h-3.5 w-3.5 text-brand-600" aria-hidden />
          <h2 className="text-sm font-semibold text-slate-800">苏格拉底状态机</h2>
          {loading && <Spinner className="h-3 w-3" />}
        </div>
        <Button
          variant="ghost"
          size="sm"
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          disabled={!enabled || loading}
          onClick={onRefresh}
        >
          刷新
        </Button>
      </header>

      <div className="space-y-3 p-4">
        {!enabled ? (
          <p className="text-xs leading-relaxed text-slate-400">
            提问开始后会实时显示状态机：当前状态、下一步动作、提示级别与失败计数。
          </p>
        ) : error ? (
          <InlineError>{error}</InlineError>
        ) : state ? (
          <>
            {/* 当前状态 + 下一步动作 */}
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge color={SOCRATIC_STATE_COLOR[state.state]} dot>
                  {SOCRATIC_STATE_LABEL[state.state]}
                </Badge>
                <span className="font-mono text-[10px] text-slate-400">{state.state}</span>
              </div>
              <div className="text-xs text-slate-600">
                下一步动作：<span className="font-medium">{TURN_TYPE_LABEL[state.next_action]}</span>
              </div>
              <div className="text-xs text-slate-500">
                当前知识点：<span className="font-mono">{state.current_kp_id ?? '未命中'}</span>
              </div>
            </div>

            {/* 引导阶梯 */}
            <div className="space-y-1.5">
              <div className="text-[11px] font-medium text-slate-500">引导阶梯（首轮不给答案）</div>
              <ol className="space-y-1">
                {SOCRATIC_LADDER.map((step, index) => {
                  const reached = reachedIndex >= 0 && index <= reachedIndex
                  return (
                    <li
                      key={step.state}
                      className={[
                        'flex items-center justify-between rounded-md border px-2 py-1 text-[11px]',
                        index === reachedIndex
                          ? 'border-brand-200 bg-brand-50 text-brand-700'
                          : reached
                            ? 'border-slate-200 bg-slate-50 text-slate-600'
                            : 'border-dashed border-slate-200 text-slate-400',
                      ].join(' ')}
                    >
                      <span className="font-medium">
                        {index + 1}. {step.label}
                      </span>
                      <span>{step.hint}</span>
                    </li>
                  )
                })}
              </ol>
            </div>

            {/* 提示级别 */}
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-slate-500">
                提示级别 hint_level
              </span>
              <div className="flex items-center gap-2">
                <Dots current={Math.min(state.hint_level, MAX_HINT_LEVEL)} total={MAX_HINT_LEVEL} />
                <span className="text-xs text-slate-600">
                  {state.hint_level} / {MAX_HINT_LEVEL}
                </span>
              </div>
            </div>

            {/* 失败计数与降级阈值 —— 明写规则，让观看者知道这是设计而非随机 */}
            <div className="rounded-lg border border-amber-200 bg-amber-50/70 p-2.5">
              <div className="flex items-center justify-between text-xs text-amber-800">
                <span>连续失败次数</span>
                <span className="font-medium">
                  {state.consecutive_failures} / {state.explain_threshold}
                </span>
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-amber-700">
                连续失败达到 explain_threshold（{state.explain_threshold}）次会强制降级为直接讲解 ——
                这是代码层兜底，不依赖模型自觉。
              </p>
            </div>

            {state.state === 'S4_EXPLAIN' && (
              <p className="rounded-md bg-amber-100/70 px-2 py-1.5 text-[11px] font-medium text-amber-800">
                当前已处于「直接讲解」状态：引导次数用尽，改给完整分步讲解。
              </p>
            )}
          </>
        ) : (
          <Spinner className="h-3.5 w-3.5" />
        )}

        <p className="border-t border-slate-100 pt-2.5 text-[11px] leading-relaxed text-slate-400">
          「首轮只反问、不给答案」是设计要求：先暴露理解偏差，再逐级给提示；
          提示用尽才降级讲解。越界的提问直接走拒答，不生成材料外内容。
        </p>
      </div>
    </section>
  )
}

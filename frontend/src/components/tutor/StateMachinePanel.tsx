import { RefreshCw, Workflow } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { InlineError, Spinner } from '@/components/ui/Feedback'
import type { QaState } from '@/lib/types'

import { MAX_HINT_LEVEL, SOCRATIC_LADDER, SOCRATIC_STATE_COLOR, SOCRATIC_STATE_LABEL, TURN_TYPE_LABEL } from './labels'

/** 小圆点进度：索引小于等于 current 的为「已到达」（深蓝底上用荧光色） */
function Dots({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-1.5">
      {Array.from({ length: total + 1 }, (_, index) => (
        <span
          key={index}
          className={[
            'h-2 w-2 rounded-full',
            index <= current ? 'bg-lime' : 'border border-white/25 bg-transparent',
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
 * Learning Atlas v2：深蓝原则板（GUIDING PRINCIPLE）形态。
 */
export function StateMachinePanel({
  state,
  loading,
  error,
  enabled,
  onRefresh,
  currentKpName = null,
}: {
  state: QaState | null
  loading: boolean
  error: string | null
  enabled: boolean
  onRefresh: () => void
  /**
   * 当前知识点的**可读名**（来自最新一轮 `diagnosis.stuck_at.evidence_kp_name`
   * 或 `knowledge_points[0].name`）。
   * ⭐ 2026-10-08 新增：`/state` 只给 `current_kp_id`，直接渲染会出现
   * `kp_ada1063f_000_000_035`。传了名字就显示名字、id 收进 tooltip；
   * 没传则回落 id（行为与改前一致）。
   */
  currentKpName?: string | null
}) {
  const reachedIndex = state ? SOCRATIC_LADDER.findIndex((step) => step.state === state.state) : -1

  return (
    <section className="relative overflow-hidden rounded-2xl bg-atlas-ink2 p-4 text-[#f5f2e9]">
      <div
        aria-hidden
        className="pointer-events-none absolute -right-16 -top-12 h-36 w-36 rounded-full border border-lime/25 shadow-[0_0_0_16px_rgba(217,237,131,0.05)]"
      />
      <header className="relative z-10 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <Workflow className="h-3.5 w-3.5 text-lime" aria-hidden />
          <h3 className="text-xs font-semibold uppercase tracking-[0.1em] text-[#a7b4c4]">
            GUIDING PRINCIPLE
          </h3>
          {loading && <Spinner className="h-3 w-3" />}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="!text-[#a7b4c4] hover:!bg-white/10 hover:!text-white"
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          disabled={!enabled || loading}
          aria-label="刷新状态机"
          onClick={onRefresh}
        />
      </header>

      <div className="relative z-10 mt-3 space-y-3">
        {/* 引导原则（常驻说明） */}
        <div>
          <h4 className="text-base font-semibold tracking-tight">不直接代答</h4>
          <p className="mt-1 text-xs leading-relaxed text-[#b5bfca]">
            首轮只反问，不给答案。连续两次答不上来，再逐级给提示，最后才直接讲解。
          </p>
        </div>

        {!enabled ? (
          <p className="border-t border-white/10 pt-2.5 text-xs leading-relaxed text-[#8d99a8]">
            提问开始后，这里会实时显示状态机：当前状态、下一步动作、提示级别与失败计数。
          </p>
        ) : error ? (
          <div className="text-xs [&_div]:!border-danger-line [&_div]:!bg-danger-soft">
            <InlineError>{error}</InlineError>
          </div>
        ) : state ? (
          <>
            {/* 当前状态 + 下一步动作 */}
            <div className="space-y-1.5 border-t border-white/10 pt-2.5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge color={SOCRATIC_STATE_COLOR[state.state]} dot>
                  {SOCRATIC_STATE_LABEL[state.state]}
                </Badge>
                <span className="font-mono text-xs text-[#8d99a8]">{state.state}</span>
              </div>
              <div className="text-xs text-[#c3ccd7]">
                下一步动作：<span className="font-medium text-white">{TURN_TYPE_LABEL[state.next_action]}</span>
              </div>
              <div className="text-xs text-[#8d99a8]">
                当前知识点：
                {/* 有可读名就显示名字；id 收进 tooltip（评审/排查时仍拿得到） */}
                <span
                  className={currentKpName ? 'text-[#c3ccd7]' : 'font-mono text-[#c3ccd7]'}
                  title={state.current_kp_id ? `知识点 id：${state.current_kp_id}` : undefined}
                >
                  {currentKpName?.trim() || state.current_kp_id || '未命中'}
                </span>
              </div>
            </div>

            {/* 引导阶梯 */}
            <div className="space-y-1.5">
              <div className="text-xs font-medium text-[#a7b4c4]">引导阶梯（首轮不给答案）</div>
              <ol className="space-y-1">
                {SOCRATIC_LADDER.map((step, index) => {
                  const reached = reachedIndex >= 0 && index <= reachedIndex
                  return (
                    <li
                      key={step.state}
                      className={[
                        'flex items-center justify-between rounded-md border px-2 py-1 text-xs',
                        index === reachedIndex
                          ? 'border-lime/40 bg-lime/10 text-lime'
                          : reached
                            ? 'border-white/15 bg-white/5 text-[#c3ccd7]'
                            : 'border-dashed border-white/15 text-[#7d8a99]',
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
              <span className="text-xs text-[#a7b4c4]">提示级别 hint_level</span>
              <div className="flex items-center gap-2">
                <Dots current={Math.min(state.hint_level, MAX_HINT_LEVEL)} total={MAX_HINT_LEVEL} />
                <span className="text-xs text-[#c3ccd7]">
                  {state.hint_level} / {MAX_HINT_LEVEL}
                </span>
              </div>
            </div>

            {/* 失败计数与降级阈值 —— 明写规则，让观看者知道这是设计而非随机 */}
            <div className="rounded-lg border border-white/15 bg-white/5 p-2.5">
              <div className="flex items-center justify-between text-xs text-[#c3ccd7]">
                <span>连续失败次数</span>
                <span className="font-medium text-white">
                  {state.consecutive_failures} / {state.explain_threshold}
                </span>
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-[#8d99a8]">
                连续失败达到 explain_threshold（{state.explain_threshold}）次会强制降级为直接讲解 ——
                这是代码层兜底，不依赖模型自觉。
              </p>
            </div>

            {state.state === 'S4_EXPLAIN' && (
              <p className="rounded-md bg-warning-soft px-2 py-1.5 text-xs font-medium text-warning">
                当前已处于「直接讲解」状态：引导次数用尽，改给完整分步讲解。
              </p>
            )}
          </>
        ) : (
          <Spinner className="h-3.5 w-3.5" />
        )}

        <p className="border-t border-white/10 pt-2.5 text-[11px] leading-relaxed text-[#7d8a99]">
          「首轮只反问、不给答案」是设计要求：先暴露理解偏差，再逐级给提示；
          提示用尽才降级讲解。越界的提问直接走拒答，不生成材料外内容。
        </p>
      </div>
    </section>
  )
}

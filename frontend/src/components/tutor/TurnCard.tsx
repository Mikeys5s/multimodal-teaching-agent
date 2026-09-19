import { AlertTriangle, Ban } from 'lucide-react'

import { Spinner } from '@/components/ui/Feedback'
import type { SseDelta, SseDiagnosis, SseDone, SseRetrieved, SseState } from '@/lib/types'

import { DiagnosisPanel } from './DiagnosisPanel'
import { StateBadge } from './StateBadge'
import { TraceCard } from './TraceCard'

/** 一轮问答在界面上的全部可见状态（由 SSE 事件逐条填满） */
export interface TurnView {
  key: string
  question: string
  retrieved: SseRetrieved | null
  state: SseState | null
  answer: string
  diagnosis: SseDiagnosis | null
  done: SseDone | null
  /** 用户主动中断 */
  stopped: boolean
  /**
   * 流**正常结束**（没抛错）但一路没收到 `done` —— 后端收尾异常，回答可能不完整。
   * 必须显式提示，否则这一轮会静默停在半途（界面看起来像卡住）。
   */
  incomplete: boolean
}

export function createTurn(key: string, question: string): TurnView {
  return {
    key,
    question,
    retrieved: null,
    state: null,
    answer: '',
    diagnosis: null,
    done: null,
    stopped: false,
    incomplete: false,
  }
}

/** 追加 delta 文本（**追加**而非替换 —— 一个回答由多个 delta 事件拼成） */
export function appendDelta(turn: TurnView, delta: SseDelta): TurnView {
  return { ...turn, answer: turn.answer + delta.text }
}

function formatLatency(latencyMs: number | null): string {
  if (latencyMs === null || !Number.isFinite(latencyMs)) return '—'
  return latencyMs < 1000 ? `${latencyMs} ms` : `${(latencyMs / 1000).toFixed(2)} s`
}

function formatTokens(usage: SseDone['usage']): string {
  if (!usage) return '—'
  const input = usage.input_tokens ?? '—'
  const output = usage.output_tokens ?? '—'
  return `输入 ${input} / 输出 ${output}`
}

/**
 * 单轮问答卡片。渲染顺序刻意体现「**先检索、再回答**」：
 *   提问 → ①溯源卡片（retrieved）→ ②状态徽标 + 流式正文（delta）→ ③三件产出（diagnosis）→ 完成信息（done）
 * 这个顺序与 api-spec §5.2 规定的事件顺序完全一致。
 */
export function TurnCard({ turn, active }: { turn: TurnView; active: boolean }) {
  const streamingAnswer = active && !turn.done && !turn.stopped && !turn.incomplete
  // 空流（一路没有任何事件）时也要让这一轮可见，否则界面上只剩一个提问气泡、看不出发生过什么
  const showAnswerBlock = Boolean(turn.state) || turn.answer !== '' || active || turn.incomplete

  return (
    <article className="space-y-2">
      {/* 学生提问 */}
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-br-sm bg-brand-600 px-3.5 py-2 text-sm leading-relaxed text-white">
          {turn.question}
        </div>
      </div>

      {/* 第 1 步 · 溯源（收到 retrieved 立刻渲染，先于任何 delta 文本） */}
      <TraceCard retrieved={turn.retrieved} pending={active} />

      {/* 第 2 步 · 组织回答 */}
      {showAnswerBlock && (
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium text-slate-500">第 2 步 · 组织回答</span>
            {turn.state ? <StateBadge state={turn.state} /> : active ? <Spinner className="h-3 w-3" /> : null}
          </div>

          {turn.answer !== '' ? (
            <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
              {turn.answer}
              {streamingAnswer && (
                <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-brand-500 align-text-bottom" />
              )}
            </div>
          ) : active ? (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <Spinner className="h-3.5 w-3.5" />
              正在组织回答…
            </div>
          ) : (
            <p className="text-xs text-slate-400">本轮没有收到任何回答内容。</p>
          )}

          {turn.stopped && (
            <div className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-amber-100/80 px-2 py-0.5 text-xs font-medium text-amber-800">
              <Ban className="h-3 w-3" aria-hidden />
              已手动中断本轮回答
            </div>
          )}

          {turn.incomplete && (
            <div className="mt-2 flex items-start gap-1.5 rounded-md bg-amber-100/80 px-2 py-1 text-xs font-medium text-amber-800">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
              <span>
                流已结束，但本轮始终没有收到结束事件（done），回答可能不完整。可重新提问，
                或核对后端 SSE 的收尾逻辑（会话条上的 Last-Event-ID 可作续推游标）。
              </span>
            </div>
          )}
        </div>
      )}

      {/* 第 3 步 · 三件产出 */}
      {turn.diagnosis && <DiagnosisPanel diagnosis={turn.diagnosis} />}

      {/* 完成信息 */}
      {turn.done && (
        <footer className="flex flex-wrap items-center gap-3 px-1 text-[11px] text-slate-400">
          <span>本轮结束</span>
          <span className="font-mono">{turn.done.turn_id}</span>
          <span>耗时 {formatLatency(turn.done.latency_ms)}</span>
          <span>tokens {formatTokens(turn.done.usage)}</span>
          <span className="font-mono">seq {turn.done.seq}</span>
        </footer>
      )}
    </article>
  )
}

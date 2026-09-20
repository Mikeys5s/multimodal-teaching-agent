import { AlertTriangle, CircleDashed, RefreshCw, ShieldCheck } from 'lucide-react'
import { useMemo } from 'react'

import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'
import type { Question, QuestionType } from '@/lib/types'

/** 与 UncertainNotes / 预览抽屉同一阈值：低于此值显式标注，不掩盖解析短板 */
const LOW_CONFIDENCE = 0.85

const QUESTION_TYPE_LABEL: Record<QuestionType, string> = {
  single_choice: '单选题',
  multi_choice: '多选题',
  fill_blank: '填空题',
  short_answer: '简答题',
}

/** 选项前缀；材料选项通常不超过 8 个，超出则退回序号 */
const OPTION_LABELS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']

/**
 * `options_json` 是**选项数组的 JSON 字符串**（不是数组）—— 见 types.ts 的 Question。
 * 解析失败时不静默丢弃：返回 `broken` 让调用方给出提示。
 */
function parseOptions(raw: string | null): { options: string[] | null; broken: boolean } {
  if (!raw) return { options: null, broken: false }
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return { options: null, broken: true }
    return {
      options: parsed.map((item) => (typeof item === 'string' ? item : JSON.stringify(item))),
      broken: false,
    }
  } catch {
    return { options: null, broken: true }
  }
}

/**
 * ★「材料里就没给答案」的主动声明（answer_missing === true）。
 *
 * 语义要点：这不是数据缺失、不是加载失败 —— 材料原文本来没有答案。
 * 所以文案是**主动声明 + 明确的取舍立场**（「宁缺毋错」），而不是道歉式的
 * 「暂无数据」；样式上给足重量的边框与图标，让它在卡片里无法被忽略。
 * 真正的数据异常走 `AnswerGap`（样式更弱、措辞指向解析异常）。
 */
function MissingAnswerNotice() {
  return (
    <div className="mt-2 rounded-lg border border-amber-300 border-l-4 bg-amber-50 px-3 py-2.5">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" aria-hidden />
        <div className="min-w-0">
          <div className="text-sm font-semibold text-amber-900">材料原文未给出答案</div>
          <div className="mt-0.5 text-xs leading-relaxed text-amber-700">
            这道题在素材原文里就没有答案，我们不做推测补全 —— 宁可留白，也不编一个看起来合理的答案。
          </div>
        </div>
      </div>
    </div>
  )
}

/** `answer_md === null && answer_missing === false`：这才是「数据缺了一块」，措辞与样式都更弱 */
function AnswerGap() {
  return (
    <div className="mt-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/70 px-3 py-2">
      <div className="flex items-start gap-2">
        <CircleDashed className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
        <div className="min-w-0">
          <div className="text-xs font-medium text-slate-500">答案字段为空</div>
          <div className="mt-0.5 text-[11px] leading-relaxed text-slate-400">
            该题未被标记为「材料未给答案」，属数据异常，建议重新解析后再核对。
          </div>
        </div>
      </div>
    </div>
  )
}

function AnswerBlock({ answerMd }: { answerMd: string }) {
  return (
    <div className="mt-2 rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2">
      <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-emerald-700">
        <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
        答案（来自材料原文）
      </div>
      <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{answerMd}</div>
    </div>
  )
}

function QuestionCard({ question, index }: { question: Question; index: number }) {
  const { options, broken } = useMemo(() => parseOptions(question.options_json), [question.options_json])

  const lowConfidence =
    question.extraction_confidence !== null && question.extraction_confidence < LOW_CONFIDENCE

  return (
    <article className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-card">
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <span className="flex h-5 w-5 items-center justify-center rounded bg-slate-100 text-[11px] font-medium tabular-nums text-slate-500">
          {index + 1}
        </span>
        <span className="rounded-md bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700">
          {QUESTION_TYPE_LABEL[question.question_type] ?? question.question_type}
        </span>
        <span className="text-xs text-slate-400">
          {question.source_page !== null ? `第 ${question.source_page} 页` : '未标注页码'}
        </span>
        {lowConfidence && (
          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700">
            抽取置信度 {Math.round((question.extraction_confidence ?? 0) * 100)}% · 建议人工核对
          </span>
        )}
        <span className="ml-auto text-[11px] text-slate-300">{question.id}</span>
      </header>

      <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">{question.stem_md}</div>

      {options && (
        <ul className="mt-2 space-y-1">
          {options.map((option, optionIndex) => (
            <li key={optionIndex} className="flex items-start gap-2 text-sm text-slate-700">
              <span className="mt-px shrink-0 font-medium text-slate-400">
                {OPTION_LABELS[optionIndex] ?? `${optionIndex + 1}.`}
              </span>
              <span className="min-w-0 whitespace-pre-wrap">{option}</span>
            </li>
          ))}
        </ul>
      )}

      {broken && (
        <div className="mt-2 text-[11px] text-amber-700">
          选项数据无法解析（options_json 不是合法 JSON 数组），此处不展示选项。
        </div>
      )}

      {question.answer_missing ? (
        <MissingAnswerNotice />
      ) : question.answer_md ? (
        <AnswerBlock answerMd={question.answer_md} />
      ) : (
        <AnswerGap />
      )}
    </article>
  )
}

export interface QuestionsPanelProps {
  materialId: string
}

/**
 * 「抽出的题目」面板（数据源：GET /api/materials/{id}/questions，api-spec §3.3）。
 *
 * 本面板的核心是 `answer_missing` 的呈现：材料里本来没有答案时，要让它看起来
 * 像「材料没给」，而不是像「数据缺了一块」。三种答案状态的文案与权重见上方组件。
 *
 * 面板自带 loading / 错误 / 空态，请求失败只影响本区块 —— 抽屉的 Markdown 预览照常可用。
 */
export function QuestionsPanel({ materialId }: QuestionsPanelProps) {
  const questionsReq = useRequest(() => api.listQuestions(materialId), [materialId])
  const questions = questionsReq.data ?? []

  const stats = useMemo(() => {
    const missing = questions.filter((q) => q.answer_missing).length
    return { total: questions.length, missing }
  }, [questions])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        {stats.missing > 0 ? (
          <div className="flex items-start gap-1.5 text-xs text-amber-700">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" aria-hidden />
            <span>
              共 {stats.total} 题，其中{' '}
              <span className="font-semibold text-amber-800">{stats.missing} 题材料未给答案</span>
              （不推测补全）
            </span>
          </div>
        ) : (
          <div className="text-xs text-slate-400">
            {questions.length === 0
              ? questionsReq.loading
                ? '正在加载题目…'
                : '共 0 题'
              : `共 ${stats.total} 题 · 答案均来自材料原文`}
          </div>
        )}

        <Button
          variant="secondary"
          size="sm"
          loading={questionsReq.loading}
          disabled={questions.length === 0}
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={() => void questionsReq.reload()}
        >
          刷新
        </Button>
      </div>

      {questionsReq.loading && questions.length === 0 && <LoadingState label="正在加载抽出的题目…" />}

      {questionsReq.error && (
        <ErrorState message={questionsReq.error} onRetry={() => void questionsReq.reload()} />
      )}

      {!questionsReq.loading && !questionsReq.error && questions.length === 0 && (
        <EmptyState
          title="这份素材还没抽出题目"
          description="该素材可能仍在解析中，或原文本身不含题目。解析完成后可在此查看题面与答案出处。"
        />
      )}

      {questions.map((question, index) => (
        <QuestionCard key={question.id} question={question} index={index} />
      ))}
    </div>
  )
}

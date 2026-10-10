import { Plus, RefreshCw, SendHorizontal, Square, Trash2, Upload } from 'lucide-react'
import { useCallback, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ReportPanel } from '@/components/tutor/ReportPanel'
import { StateMachinePanel } from '@/components/tutor/StateMachinePanel'
import { TurnCard, appendDelta, createTurn } from '@/components/tutor/TurnCard'
import type { TurnView } from '@/components/tutor/TurnCard'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, InlineError, InlineWarning, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { ApiError } from '@/lib/api'
import { api } from '@/lib/endpoints'
import { streamAsk } from '@/lib/sse'
import type { SsePartialSeq, SseProtocolWarning } from '@/lib/sse'
import type { QaSessionCreated } from '@/lib/types'

/** 演示用的学生标识（后端必填字段 student_label） */
const STUDENT_LABEL = 'demo'

/**
 * 答疑辅导页（Stage 3 · D8）。
 *
 * 三条产品主线在这一个页面里可见：
 *   ① 「先检索再回答」—— retrieved 事件先到，溯源卡片先于正文渲染（api-spec §5.2）；
 *   ② 苏格拉底状态机 —— state 事件 + GET /state 双通道可视化（api-spec §5.3）；
 *   ③ 三件产出 —— diagnosis 事件给出「涉及知识点 / 卡在哪一步 / 下一步练习」。
 */
/**
 * 示例问题 —— **实测挑出来的，不是想出来的**。
 *
 * 判据（2026-09-23 线上实测）：每条都命中 ≥ 5 个知识点，
 * 且首轮都是反问（符合 SPEC A3-4「首轮不给答案」）。
 *
 * ⚠️ **最后一条是越界问题**，故意留的 ——
 * 它演示的是「幻觉率 0」：材料里没有就**明确说不答、不猜**。
 */
const SAMPLE_QUESTIONS: { q: string; label: string; scope?: 'out' }[] = [
  { q: '三次握手为什么不是两次？', label: 'Ch05 · 三次握手' },
  { q: '子网掩码是怎么用的？', label: 'Ch03 · 子网划分' },
  { q: '慢启动为什么叫慢启动？', label: 'Ch06 · 拥塞控制' },
  { q: '校验和是怎么算的？', label: 'Ch03 · 校验和' },
  { q: '距离向量和链路状态路由的区别是什么？', label: 'Ch03 · 路由' },
  { q: '滑动窗口是怎么控制流量的？', label: 'Ch05 · 滑动窗口' },
  { q: '怎么做红烧肉？', label: '越界 · 应拒答', scope: 'out' },
]

export default function Tutor() {
  const navigate = useNavigate()
  const materialsReq = useRequest(() => api.listMaterials({ page_size: 100 }), [])

  /**
   * 创建会话的响应**只有 `session_id`**（api-spec §5.1）——
   * 所以这里只持有它，学生标识与材料范围一律用**本次请求自己的入参**展示，
   * 不去读响应里根本不存在的字段（那样会在运行时读到 `undefined`）。
   */
  const [session, setSession] = useState<QaSessionCreated | null>(null)
  const [turns, setTurns] = useState<TurnView[]>([])
  const [question, setQuestion] = useState('')
  const [streamingKey, setStreamingKey] = useState<string | null>(null)
  /** 会话内单调递增的最后事件序号 —— 断线续推（Last-Event-ID）依赖它，跨轮次保留 */
  const [lastSeq, setLastSeq] = useState<number | null>(null)
  /** 后端 SSE 契约漂移（如 id: 与 data.seq 不一致）：必须让人看见，但不阻断本轮回答 */
  const [protocolWarning, setProtocolWarning] = useState<SseProtocolWarning | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const sessionId = session?.session_id ?? null
  const stateReq = useRequest(() => api.getQaState(sessionId as string), [sessionId], {
    immediate: sessionId !== null,
  })
  const reportReq = useRequest(() => api.getQaReport(sessionId as string), [sessionId], {
    immediate: sessionId !== null,
  })
  const clearState = stateReq.setData
  const clearReport = reportReq.setData

  const materials = materialsReq.data?.items ?? []
  const totalMaterials = materialsReq.data?.total ?? materials.length
  const streaming = streamingKey !== null

  /**
   * 当前知识点的**可读名** —— 给状态机面板用。
   * `GET /qa/sessions/{id}/state` 只返回 `current_kp_id`，直接渲染就是 `kp_xxx`（学生看不懂）。
   * 从最新一轮往回找：优先卡点证据名，其次第一个命中知识点名；都没有则回落 id。
   */
  const currentKpName = useMemo(() => {
    for (let index = turns.length - 1; index >= 0; index -= 1) {
      const diagnosis = turns[index]?.diagnosis
      if (!diagnosis) continue
      const evidence = diagnosis.stuck_at?.evidence_kp_name?.trim()
      if (evidence) return evidence
      const first = diagnosis.knowledge_points?.[0]?.name?.trim()
      if (first) return first
    }
    return null
  }, [turns])

  /** 最新一轮的检索命中 —— 「回答所依据的材料」面板的数据源（retrieved 事件先于回答到达） */
  const latestRetrieved = useMemo(() => {
    for (let index = turns.length - 1; index >= 0; index -= 1) {
      const retrieved = turns[index]?.retrieved
      if (retrieved) return retrieved
    }
    return null
  }, [turns])

  const resetLocal = useCallback(() => {
    setSession(null)
    setTurns([])
    setLastSeq(null)
    setStreamingKey(null)
    setProtocolWarning(null)
    clearState(null)
    clearReport(null)
  }, [clearState, clearReport])

  /** 新建会话：material_scope 传空数组 = 全部材料；新会话的 seq 从头开始，这是**唯一**允许清零的地方 */
  const startSession = useCallback(async (): Promise<string | null> => {
    setBusy(true)
    setError(null)
    abortRef.current?.abort()
    try {
      const created = await api.createQaSession({ material_scope: [], student_label: STUDENT_LABEL })
      setSession(created)
      setTurns([])
      setLastSeq(null)
      setStreamingKey(null)
      setProtocolWarning(null)
      return created.session_id
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建答疑会话失败，请稍后重试。')
      return null
    } finally {
      setBusy(false)
    }
  }, [])

  const handleAsk = async () => {
    const text = question.trim()
    // streaming：上一轮还没结束（Ctrl/⌘ + Enter 绕过按钮的 disabled）时不再起第二条流
    if (text === '' || busy || streaming) return

    setError(null)
    setProtocolWarning(null)
    setQuestion('')

    let sid = sessionId
    if (!sid) {
      sid = await startSession()
      if (!sid) {
        setQuestion(text)
        return
      }
    }

    const key = `${Date.now()}-${turns.length}`
    setTurns((prev) => [...prev, createTurn(key, text)])
    const patch = (updater: (turn: TurnView) => TurnView) =>
      setTurns((prev) => prev.map((turn) => (turn.key === key ? updater(turn) : turn)))

    const controller = new AbortController()
    abortRef.current = controller
    setStreamingKey(key)

    try {
      const result = await streamAsk({
        sessionId: sid,
        question: text,
        // ★ 跨轮次续推：带上本会话最后收到的 seq
        lastEventId: lastSeq,
        signal: controller.signal,
        handlers: {
          onRetrieved: (event) => patch((turn) => ({ ...turn, retrieved: event })),
          onState: (event) => patch((turn) => ({ ...turn, state: event })),
          onDelta: (event) => patch((turn) => appendDelta(turn, event)),
          onDiagnosis: (event) => patch((turn) => ({ ...turn, diagnosis: event })),
          onDone: (event) => patch((turn) => ({ ...turn, done: event })),
          // 契约漂移（id: 与 data.seq 不一致）不阻断回答，但要显式告诉使用者
          onProtocolWarning: (warning) => setProtocolWarning(warning),
        },
      })

      // ★ seq 只有一个来源：streamAsk 的返回值（已含「收到过的最大的 seq」）。
      //   不要再在 onEvent 里自己维护一份 —— 两套推进逻辑迟早会分叉。
      setLastSeq(result.lastSeq)

      // 流正常结束却没收到 done：显式标记，别让这一轮静默停在半途
      patch((turn) => (turn.done ? turn : { ...turn, incomplete: true }))
    } catch (err) {
      if ((err as Error)?.name === 'AbortError') {
        patch((turn) => ({ ...turn, stopped: true }))
      } else {
        // 中断 / 出错时也保住**已经推进到的** seq，重试才能从断点续推
        const partial = (err as Partial<SsePartialSeq> | null)?.lastSeq
        if (typeof partial === 'number') {
          setLastSeq((prev) => (prev === null ? partial : Math.max(prev, partial)))
        }
        setError(err instanceof ApiError ? err.message : '答疑请求失败，请稍后重试。')
      }
    } finally {
      setStreamingKey(null)
      abortRef.current = null
      // 每轮结束后刷新状态机与诊断报告
      void stateReq.reload()
      void reportReq.reload()
    }
  }

  const handleAbort = () => {
    abortRef.current?.abort()
    abortRef.current = null
  }

  const handleDeleteSession = async () => {
    if (!session) return
    if (!window.confirm('确认删除当前答疑会话？会话的全部轮次与诊断记录都会被删除。')) return
    setError(null)
    abortRef.current?.abort()
    try {
      await api.deleteQaSession(session.session_id)
      resetLocal()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除会话失败，请稍后重试。')
    }
  }

  /* ---------- 页面级状态：后端未启动 / 没有材料 ---------- */

  if (materialsReq.error) {
    return (
      <div className="mx-auto max-w-3xl">
        <ErrorState message={materialsReq.error} onRetry={() => void materialsReq.reload()} />
      </div>
    )
  }

  // 首帧 data 还是 null（effect 尚未发起请求），不能直接当成「没有材料」而闪一下空态
  if (!materialsReq.data) {
    return <LoadingState label="正在读取材料清单…" />
  }

  if (totalMaterials === 0) {
    return (
      <div className="mx-auto max-w-3xl">
        <div className="xizhi-card">
          <EmptyState
            title="还没有可用的学习材料"
            description="答疑严格基于你上传的材料作答：先检索材料里的知识点与原文块，检索不到就直接拒答，不会使用材料以外的知识。请先到素材工作台上传讲稿或教材，再回来提问。"
            action={
              <Button icon={<Upload className="h-3.5 w-3.5" />} onClick={() => navigate('/materials')}>
                去上传素材
              </Button>
            }
          />
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      {/* 页头：编辑式标题 + 会话级操作 */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="atlas-eyebrow">
            <span className="idx">05</span> SOCRATIC TUTOR / GUIDED QUESTIONING
          </div>
          <h2 className="atlas-h1 mt-2">先追问，再解释。</h2>
          <p className="mt-2 max-w-[560px] text-[13px] leading-relaxed text-atlas-muted">
            围绕已有材料逐步引导。答案可追溯到来源，遇到缺失内容会明确说明。
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="secondary"
            loading={busy}
            icon={<Plus className="h-3.5 w-3.5" />}
            onClick={() => void startSession()}
          >
            新建会话
          </Button>
          {session && (
            <Button
              variant="danger"
              icon={<Trash2 className="h-3.5 w-3.5" />}
              onClick={() => void handleDeleteSession()}
            >
              删除会话
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        {/* 左：暖纸对话区 */}
        <section className="atlas-sheet-panel flex min-h-[600px] flex-col overflow-hidden">
          {/* 会话头 */}
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[#ddd7cb] bg-atlas-paper2 px-5 py-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <h3 className="text-sm font-semibold text-atlas-ink">答疑会话</h3>
                {session && (
                  <span className="font-mono text-xs text-atlas-muted">{session.session_id}</span>
                )}
              </div>
              <div className="mt-0.5 text-[10px] text-[#808992]">
                {session
                  ? `学生 ${STUDENT_LABEL} · 材料范围 全部材料 · Last-Event-ID ${lastSeq ?? '—'}`
                  : '尚未创建会话 —— 首次提问时会自动创建'}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span
                className={[
                  'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
                  streaming ? 'bg-brand-50 text-brand-700' : 'bg-success-soft text-success',
                ].join(' ')}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
                {streaming ? '回答中' : '等待提问'}
              </span>
              <Button
                variant="ghost"
                size="sm"
                icon={<RefreshCw className="h-3.5 w-3.5" />}
                disabled={!sessionId || stateReq.loading}
                title="刷新状态机与诊断报告"
                aria-label="刷新状态机与诊断报告"
                onClick={() => {
                  void stateReq.reload()
                  void reportReq.reload()
                }}
              />
            </div>
          </div>

          {/* 对话体（暖纸颗粒底） */}
          <div
            className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-5"
            style={{
              backgroundImage: 'radial-gradient(rgba(16,28,46,0.07) 0.5px, transparent 0.7px)',
              backgroundSize: '7px 7px',
            }}
          >
            {error && <InlineError>{error}</InlineError>}

            {/* 契约漂移告警：不阻断本轮回答，但会让断线续推错位，必须让人看见 */}
            {protocolWarning && <InlineWarning>{protocolWarning.message}</InlineWarning>}

            {turns.length === 0 ? (
              /* 开场状态：有信息层级的引导区，不预置任何虚构对话 */
              <div className="flex min-h-[320px] flex-col items-center justify-center gap-5 px-4 py-8 text-center">
                <svg width="72" height="72" viewBox="0 0 72 72" fill="none" aria-hidden className="text-atlas-muted">
                  <path d="M14 14h32a6 6 0 0 1 6 6v18a6 6 0 0 1-6 6H30l-10 9v-9h-6a6 6 0 0 1-6-6V20a6 6 0 0 1 6-6z" stroke="currentColor" strokeWidth="1.6" transform="translate(6 4)" />
                  <path d="M22 30h16M22 37h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" transform="translate(6 4)" />
                  <path d="M46 22l4-4M46 34l4 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" transform="translate(6 4)" opacity="0.6" />
                </svg>
                <div>
                  <p className="text-base font-semibold text-atlas-ink">从一个问题开始</p>
                  <p className="mx-auto mt-2 max-w-[440px] text-xs leading-relaxed text-atlas-muted">
                    在下方输入框直接提问，或点「建议继续追问」里的示例；首次提问会自动创建会话。
                    回答范围仅限已入库的 {totalMaterials} 份材料 —— 检索不到就明确说不答，不使用材料外的知识。
                  </p>
                </div>
                <div className="w-full max-w-[520px] rounded-2xl border border-[#ddd7cb] bg-atlas-sheet p-5 text-left">
                  <p className="text-sm font-semibold text-atlas-ink">提问后你会依次看到三件事</p>
                  <ol className="mt-2 list-decimal space-y-1.5 pl-5 text-xs leading-relaxed text-slate-500">
                    <li>
                      <span className="text-slate-600">第 1 步 · 检索材料</span>
                      ：先命中知识点与原文块；一条都没命中就直接拒答，绝不用材料外的知识作答。
                    </li>
                    <li>
                      <span className="text-slate-600">第 2 步 · 组织回答</span>
                      ：苏格拉底式反问 → 一级提示 → 二级提示 → 兜底讲解，逐字流式输出。
                    </li>
                    <li>
                      <span className="text-slate-600">第 3 步 · 本轮诊断</span>
                      ：涉及知识点、卡在哪一步（含来源证据）、下一步建议练习。
                    </li>
                  </ol>
                </div>
              </div>
            ) : (
              turns.map((turn) => (
                <TurnCard key={turn.key} turn={turn} active={turn.key === streamingKey} />
              ))
            )}
          </div>

          {/* 输入区（吸附内容底部） */}
          <div className="shrink-0 border-t border-[#ded8cd] bg-[#f7f4ed] px-4 py-3">
            <div className="rounded-xl border border-[#c9c2b6] bg-white p-3">
              <textarea
                rows={2}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                    event.preventDefault()
                    void handleAsk()
                  }
                }}
                aria-label="输入问题"
                placeholder="继续追问这一步，或输入你的问题…"
                className="w-full resize-none bg-transparent text-sm leading-relaxed text-atlas-ink outline-none placeholder:text-slate-400"
              />
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                <span className="text-[10px] text-[#89919a]">
                  回答范围：全部 {totalMaterials} 份材料 · 首轮只反问、不给答案 · Ctrl/⌘ + Enter 发送
                </span>
                <div className="flex items-center gap-2">
                  {streaming && (
                    <Button variant="danger" size="sm" icon={<Square className="h-3.5 w-3.5" />} onClick={handleAbort}>
                      中断
                    </Button>
                  )}
                  <button
                    type="button"
                    disabled={question.trim() === '' || streaming}
                    onClick={() => void handleAsk()}
                    aria-label="发送"
                    className="inline-flex h-9 min-w-[44px] items-center justify-center gap-1.5 rounded-lg bg-brand-600 px-3 text-sm font-semibold text-white transition-colors duration-120 hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <SendHorizontal className="h-4 w-4" aria-hidden />
                    {streaming ? '…' : '发送'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* 右：原则板 + 追问建议 + 来源 + 报告 */}
        <aside className="space-y-3">
          <StateMachinePanel
            state={stateReq.data}
            loading={stateReq.loading}
            error={stateReq.error}
            enabled={sessionId !== null}
            onRefresh={() => void stateReq.reload()}
            currentKpName={currentKpName}
          />

          {/* 建议继续追问（示例问题：点一下填入输入框，不自动提交） */}
          <div className="rounded-2xl border border-atlas-line bg-atlas-sheet p-4">
            <h3 className="text-xs font-semibold text-atlas-ink">建议继续追问</h3>
            <div className="mt-2 space-y-1.5">
              {SAMPLE_QUESTIONS.map((item, index) => (
                <button
                  key={item.q}
                  type="button"
                  onClick={() => setQuestion(item.q)}
                  title={item.label}
                  className="flex min-h-8 w-full items-start gap-2 rounded-lg px-1 py-1 text-left text-xs leading-relaxed text-[#4b5969] transition-colors duration-120 hover:bg-atlas-paper"
                >
                  <span
                    className={[
                      'grid h-4 w-4 shrink-0 place-items-center rounded-full text-[9px] font-medium',
                      item.scope === 'out' ? 'bg-warning-soft text-warning' : 'bg-[#e2e9f7] text-brand-600',
                    ].join(' ')}
                  >
                    {index + 1}
                  </span>
                  <span>{item.q}</span>
                </button>
              ))}
            </div>
          </div>

          {/* 回答所依据的材料（最新一轮 retrieved 事件） */}
          <div className="rounded-2xl border border-atlas-line bg-atlas-sheet p-4">
            <h3 className="text-xs font-semibold text-atlas-ink">回答所依据的材料</h3>
            {latestRetrieved ? (
              <>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {latestRetrieved.kp_ids.slice(0, 6).map((id, i) => (
                    <span
                      key={id}
                      title={`知识点 id：${id}`}
                      className="inline-flex items-center rounded-md bg-atlas-ink3 px-2 py-1 text-[10px] text-[#dbe4ef]"
                    >
                      {latestRetrieved.kp_names?.[i]?.trim() || id}
                    </span>
                  ))}
                  {latestRetrieved.kp_ids.length === 0 && (
                    <span className="text-xs text-atlas-muted">本轮未命中知识点</span>
                  )}
                </div>
                <p className="mt-2 text-[10px] leading-relaxed text-atlas-muted">
                  命中 {latestRetrieved.kp_ids.length} 个知识点 / {latestRetrieved.block_ids.length} 个原文块；
                  回答只用这些材料，不用材料外的知识。
                </p>
              </>
            ) : (
              <p className="mt-2 text-xs leading-relaxed text-atlas-muted">
                提问后这里会列出本轮回答命中的知识点与原文块。
              </p>
            )}
          </div>

          <ReportPanel
            report={reportReq.data}
            loading={reportReq.loading}
            error={reportReq.error}
            enabled={sessionId !== null}
            onRefresh={() => void reportReq.reload()}
          />

          <div className="rounded-2xl bg-[#dbe7f4] p-4">
            <blockquote className="font-serif text-base italic leading-snug text-[#233a56]">
              理解的路径，也应该能被看见。
            </blockquote>
            <small className="mt-2 block text-[10px] tracking-wide text-[#687d98]">
              SOCRATIC LEARNING / XI ZHI
            </small>
          </div>
        </aside>
      </div>
    </div>
  )
}

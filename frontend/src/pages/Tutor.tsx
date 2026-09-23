import { Plus, RefreshCw, SendHorizontal, Square, Trash2, Upload } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
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
    <div className="mx-auto max-w-6xl space-y-4">
      {/* 会话条 */}
      <section className="xizhi-card flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <h2 className="text-sm font-semibold text-slate-800">答疑会话</h2>
          {session ? (
            <>
              <span className="font-mono text-xs text-slate-500">{session.session_id}</span>
              <span className="text-xs text-slate-400">
                学生 {STUDENT_LABEL} · 材料范围 全部材料
                {' · '}
                <span title="断线续推用的最后事件序号">Last-Event-ID {lastSeq ?? '—'}</span>
              </span>
            </>
          ) : (
            <span className="text-xs text-slate-400">尚未创建会话 —— 首次提问时会自动创建</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            disabled={!sessionId || stateReq.loading}
            onClick={() => {
              void stateReq.reload()
              void reportReq.reload()
            }}
          >
            刷新状态与报告
          </Button>
          <Button
            variant="secondary"
            size="sm"
            loading={busy}
            icon={<Plus className="h-3.5 w-3.5" />}
            onClick={() => void startSession()}
          >
            新建会话
          </Button>
          {session && (
            <Button
              variant="danger"
              size="sm"
              icon={<Trash2 className="h-3.5 w-3.5" />}
              onClick={() => void handleDeleteSession()}
            >
              删除会话
            </Button>
          )}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_330px]">
        {/* 左：问答流 */}
        <div className="space-y-3">
          <section className="xizhi-card p-3">
            {/* 示例问题 —— 点一下填入输入框（**不自动提交**，留改的余地）*/}
            <div className="mb-2">
              <div className="mb-1.5 text-xs font-medium text-slate-500">
                示例问题（点一下填入，可再修改）
              </div>
              <div className="flex flex-wrap gap-1.5">
                {SAMPLE_QUESTIONS.map((item) => (
                  <button
                    key={item.q}
                    type="button"
                    onClick={() => setQuestion(item.q)}
                    title={item.label}
                    className={
                      'rounded-full border px-2.5 py-1 text-xs transition-colors ' +
                      (item.scope === 'out'
                        ? 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100'
                        : 'border-slate-200 bg-slate-50 text-slate-600 hover:border-brand-300 hover:text-brand-700')
                    }
                  >
                    {item.q}
                  </button>
                ))}
              </div>
            </div>
            <textarea
              rows={3}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                  event.preventDefault()
                  void handleAsk()
                }
              }}
              placeholder="例如：三次握手为什么不是两次？（也可以点上面的示例）"
              className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm leading-relaxed text-slate-800 outline-none placeholder:text-slate-400 focus:border-brand-300 focus:ring-2 focus:ring-brand-500/20"
            />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-slate-400">
                基于 {totalMaterials} 份材料作答 · 首轮只反问、不给答案 · Ctrl/⌘ + Enter 提交
              </span>
              <div className="flex items-center gap-2">
                {streaming && (
                  <Button variant="danger" size="sm" icon={<Square className="h-3.5 w-3.5" />} onClick={handleAbort}>
                    中断
                  </Button>
                )}
                <Button
                  size="sm"
                  loading={streaming}
                  disabled={question.trim() === ''}
                  icon={<SendHorizontal className="h-3.5 w-3.5" />}
                  onClick={() => void handleAsk()}
                >
                  提问
                </Button>
              </div>
            </div>
          </section>

          {error && <InlineError>{error}</InlineError>}

          {/* 契约漂移告警：不阻断本轮回答，但会让断线续推错位，必须让人看见 */}
          {protocolWarning && <InlineWarning>{protocolWarning.message}</InlineWarning>}

          {turns.length === 0 ? (
            <section className="xizhi-card p-5">
              <p className="text-sm font-medium text-slate-700">提问后你会依次看到三件事</p>
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
            </section>
          ) : (
            <section className="space-y-4">
              {turns.map((turn) => (
                <TurnCard key={turn.key} turn={turn} active={turn.key === streamingKey} />
              ))}
            </section>
          )}
        </div>

        {/* 右：状态机 + 诊断报告 */}
        <aside className="space-y-4">
          <StateMachinePanel
            state={stateReq.data}
            loading={stateReq.loading}
            error={stateReq.error}
            enabled={sessionId !== null}
            onRefresh={() => void stateReq.reload()}
          />
          <ReportPanel
            report={reportReq.data}
            loading={reportReq.loading}
            error={reportReq.error}
            enabled={sessionId !== null}
            onRefresh={() => void reportReq.reload()}
          />
        </aside>
      </div>
    </div>
  )
}

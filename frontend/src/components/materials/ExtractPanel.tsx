import { AlertTriangle, ArrowRight, Info, Network, RotateCcw, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { JobProgressPanel } from '@/components/materials/JobProgressPanel'
import type { ActiveUpload } from '@/components/materials/JobProgressPanel'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, InlineError, LoadingState } from '@/components/ui/Feedback'
import { useJobsPolling } from '@/hooks/useJobsPolling'
import { ApiError } from '@/lib/api'
import { api } from '@/lib/endpoints'
import { STATUS_LABEL } from '@/lib/format'
import type { Job, JobStatus, Material } from '@/lib/types'

/* ------------------------------------------------------------------ *
 * 任务记录：只存"触发时后端告诉我们的东西" + 触发参数，便于失败后原样重试
 * ------------------------------------------------------------------ */

interface ExtractRecord {
  job_id: string
  /** 展示用标题：单份素材用文件名，多份用「N 份素材」 */
  label: string
  /** ★ 后端返回的预计耗时（秒）。前端只展示，不据此推算剩余时间 */
  estimated_seconds: number
  material_ids: string[]
  force: boolean
  started_at: number
  /**
   * 进入终态时缓存下来的最后一次 Job 快照。
   * 目的有两个：① 切页/刷新回来后终结状态与"下一步引导"不用再打一次接口；
   * ② 已终结的任务不再进轮询集合，避免对旧 job_id 空转（后端重启后尤其明显）。
   */
  last_job?: Job
}

const STORAGE_KEY = 'xizhi.extract.jobs.v1'

const TERMINAL_STATUSES: JobStatus[] = ['done', 'failed', 'partial']

/** 抽取要求素材完成解析，只有这两个状态可抽取 */
const EXTRACTABLE_STATUSES: Material['status'][] = ['done', 'partial']

/** 从本地存储恢复时逐字段收窄：storage 里的东西是 unknown，不能当 Job 直接用 */
function isJobLike(value: unknown): value is Job {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.job_id === 'string' &&
    typeof candidate.status === 'string' &&
    typeof candidate.progress === 'number' &&
    typeof candidate.stage_detail === 'string'
  )
}

function isTerminalStatus(status: JobStatus | null | undefined): boolean {
  return status !== null && status !== undefined && TERMINAL_STATUSES.includes(status)
}

function isExtractRecord(value: unknown): value is ExtractRecord {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.job_id === 'string' &&
    typeof candidate.label === 'string' &&
    typeof candidate.estimated_seconds === 'number' &&
    typeof candidate.force === 'boolean' &&
    typeof candidate.started_at === 'number' &&
    Array.isArray(candidate.material_ids) &&
    candidate.material_ids.every((id) => typeof id === 'string') &&
    (candidate.last_job === undefined || isJobLike(candidate.last_job))
  )
}

/**
 * 从 sessionStorage 恢复未看完的任务。
 * 后端任务本身是异步的、与前端无关；这里恢复的只是"我要看哪几个 job"，
 * 恢复后 `useJobsPolling` 会重新拉一次最新状态 —— 所以切页回来进度不会丢。
 */
function readStoredRecords(): ExtractRecord[] {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(isExtractRecord)
  } catch {
    return []
  }
}

/**
 * `Job.result` 是 `unknown`：**先收窄再判空**，且不读任何契约里没有的字段。
 * 拿不到可靠信息时返回 null（宁可不显示，也不要猜一个数字给用户）。
 */
function summarizeResult(result: unknown): string | null {
  if (result === null || result === undefined) return null
  if (Array.isArray(result)) return `后端返回了 ${result.length} 条结构化结果，详情以知识图谱页为准。`
  if (typeof result === 'object') {
    return '后端返回了结构化结果。其字段未在前端契约中约定，这里不做解析 —— 请以知识图谱 / 学习路径页为准。'
  }
  return null
}

const RESULT_FALLBACK = '知识点已抽取完成，请到知识图谱查看结果。'

export interface ExtractPanelProps {
  /** 素材清单（只读使用；上传/解析在素材页其它区块完成） */
  materials: Material[]
  /** 素材清单是否首次加载中 */
  loading?: boolean
  /** 素材清单错误 —— 后端没起时这里会是中文文案，直接展示 */
  materialsError?: string | null
  /** 重新拉素材清单（错误态重试） */
  onReloadMaterials?: () => void
  /** 抽取任务进入终态时回调（素材页可借此刷新清单） */
  onJobSettled?: (job: Job) => void
}

/**
 * 知识点抽取工作台（api-spec §4.1 触发抽取 + §1.4/§6 任务轮询）。
 *
 * 为什么必须异步：OCR 抽取单页约 140 秒，20 页可能 47 分钟。接口只返回
 * `202 { job_id, estimated_seconds }`，进度必须靠轮询 `GET /api/jobs/{job_id}` 拿。
 * 本组件的三条纪律：
 *   1. 进度文案**只**来自 `stage_detail`，原样展示（后端可能已拼好"第 7/20 页"，前端不重拼、不解析）；
 *   2. 预计耗时**只**来自 `estimated_seconds`，前端不推算剩余时间、不做进度外推；
 *   3. `result` 是 `unknown`，展示前先类型收窄 + 判空。
 */
export function ExtractPanel({
  materials,
  loading = false,
  materialsError = null,
  onReloadMaterials,
  onJobSettled,
}: ExtractPanelProps) {
  const [records, setRecords] = useState<ExtractRecord[]>(() => readStoredRecords())
  const [selected, setSelected] = useState<string[]>([])
  const [force, setForce] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const extractable = useMemo(
    () => materials.filter((m) => EXTRACTABLE_STATUSES.includes(m.status)),
    [materials],
  )
  const extractableIds = useMemo(() => extractable.map((m) => m.id), [extractable])

  // 素材被删掉后，把失效的勾选项摘掉，避免带着不存在的 id 触发抽取
  useEffect(() => {
    setSelected((prev) => {
      const next = prev.filter((id) => extractableIds.includes(id))
      return next.length === prev.length ? prev : next
    })
  }, [extractableIds])

  // 只轮询还没到终态的任务：已终结的用本地快照展示，不再对旧 job_id 空转
  const pollJobIds = useMemo(
    () =>
      records
        .filter((record) => !isTerminalStatus(record.last_job?.status))
        .map((record) => record.job_id),
    [records],
  )

  const { jobs, error: jobError, revalidate } = useJobsPolling(pollJobIds, {
    intervalMs: 2000,
    maxIntervalMs: 15000,
    backoffFactor: 1.5,
    onSettled: (job) => {
      // 终态快照落盘：切页/刷新回来仍能看到结果与下一步引导，且无需再拉一次接口
      setRecords((prev) =>
        prev.map((record) =>
          record.job_id === job.job_id ? { ...record, last_job: job } : record,
        ),
      )
      onJobSettled?.(job)
    },
  })

  /** 展示用状态：轮询结果优先，其次本地快照（恢复出来的已完成任务走这里） */
  const displayJobs = useMemo(() => {
    const merged: Record<string, Job> = {}
    for (const record of records) {
      if (record.last_job) merged[record.job_id] = record.last_job
    }
    return { ...merged, ...jobs }
  }, [records, jobs])

  // 任务清单落盘：切到别的页面再回来，仍能在本浏览器会话内接上进度
  useEffect(() => {
    try {
      if (records.length === 0) window.sessionStorage.removeItem(STORAGE_KEY)
      else window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(records))
    } catch {
      /* 隐私模式下 sessionStorage 不可用：只影响"切页回来还能看到"，不影响轮询本身 */
    }
  }, [records])

  const trigger = useCallback(
    async (ids: string[], forceFlag: boolean) => {
      if (ids.length === 0 || submitting) return
      setSubmitting(true)
      setSubmitError(null)
      if (ids.length === 1) setBusyId(ids[0])
      try {
        // 契约：202 → { job_id, estimated_seconds }
        const { job_id, estimated_seconds } = await api.extractKnowledge({
          material_ids: ids,
          force: forceFlag,
        })
        const single = ids.length === 1 ? materials.find((m) => m.id === ids[0]) : undefined
        const record: ExtractRecord = {
          job_id,
          label: single ? single.filename : `${ids.length} 份素材`,
          estimated_seconds,
          material_ids: ids,
          force: forceFlag,
          started_at: Date.now(),
        }
        // 同一个 job_id 不重复入列（后端只会返回一次，这里再兜一层）
        setRecords((prev) =>
          prev.some((item) => item.job_id === job_id) ? prev : [record, ...prev],
        )
        void revalidate()
      } catch (err) {
        const message =
          err instanceof ApiError ? err.message : '触发知识点抽取失败，请稍后重试。'
        const conflict =
          err instanceof ApiError && err.code === 'JOB_IN_PROGRESS'
            ? '（后端已有一批抽取任务在执行，等它结束后再触发即可。）'
            : ''
        setSubmitError(`${message}${conflict}`)
      } finally {
        setSubmitting(false)
        setBusyId(null)
      }
    },
    [materials, revalidate, submitting],
  )

  /** 收起：只隐藏已终结的任务，正在跑的一个都不丢 */
  const handleDismiss = () => {
    setRecords((prev) => prev.filter((record) => !isTerminalStatus(displayJobs[record.job_id]?.status)))
  }

  /** 清除本地任务记录（后端任务不受影响）—— 用于 job_id 已失效、无法再取到进度的场景 */
  const handleClearRecords = () => {
    setRecords([])
    try {
      window.sessionStorage.removeItem(STORAGE_KEY)
    } catch {
      /* 忽略：清不掉存储也不阻塞界面 */
    }
  }

  const handleRetry = (jobId: string) => {
    const record = records.find((item) => item.job_id === jobId)
    if (!record) return
    // 旧任务已终结，重跑会拿到新的 job_id —— 把旧记录摘掉，避免同一批素材在列表里出现两次
    setRecords((prev) => prev.filter((item) => item.job_id !== jobId))
    void trigger(record.material_ids, record.force)
  }

  const toggle = (id: string) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]))
  }

  const panelItems: ActiveUpload[] = records.map((record) => ({
    job_id: record.job_id,
    filename: record.label,
    estimated_seconds: record.estimated_seconds,
    hint: record.force ? '覆盖重抽' : undefined,
  }))

  const runningCount = records.filter(
    (record) => !isTerminalStatus(displayJobs[record.job_id]?.status),
  ).length

  const renderAfter = (job: Job | undefined, item: ActiveUpload) => {
    if (!job) return null
    if (job.status === 'partial') {
      return (
        <div className="rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2">
          <div className="flex items-start gap-1.5">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" aria-hidden />
            <div className="text-xs leading-relaxed text-amber-800">
              部分成功：这批素材里只有一部分抽出了知识点，其余部分后端未能完成。
              可以先到知识图谱看已抽到的部分，再对缺口素材勾选「重新抽取」补跑一次。
            </div>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs">
            <Link className="font-medium text-brand-600 hover:underline" to="/graph">
              去知识图谱看已抽到的结果
            </Link>
            <button
              className="font-medium text-brand-600 hover:underline"
              onClick={() => handleRetry(item.job_id)}
              title="沿用这批素材与本次的「重新抽取」设置再跑一次"
            >
              重跑这批素材
            </button>
          </div>
        </div>
      )
    }
    if (job.status !== 'done') return null

    const summary = summarizeResult(job.result)
    return (
      <div className="rounded-lg border border-emerald-100 bg-emerald-50/60 px-3 py-2">
        <div className="text-xs leading-relaxed text-emerald-800">
          {summary ?? RESULT_FALLBACK}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs">
          <Link className="font-medium text-brand-600 hover:underline" to="/graph">
            去知识图谱看看
          </Link>
          <Link className="font-medium text-brand-600 hover:underline" to="/path">
            按学习路径继续
          </Link>
        </div>
      </div>
    )
  }

  const body = () => {
    if (materialsError) {
      return <ErrorState message={materialsError} onRetry={onReloadMaterials} />
    }
    if (loading && materials.length === 0) {
      return <LoadingState label="正在加载素材清单…" />
    }
    if (materials.length === 0) {
      return (
        <EmptyState
          title="还没有可用素材"
          description="请先在上方的上传区添加 PDF / Word / PPT / 图片，等解析完成后再回到这里触发知识点抽取。"
        />
      )
    }
    if (extractable.length === 0) {
      return (
        <EmptyState
          title="暂时没有可抽取的素材"
          description="知识点抽取要求素材解析状态为「已完成」或「部分完成」。当前素材仍在解析中或解析失败，请等待解析完成，或先在下方素材清单中重试解析。"
        />
      )
    }

    return (
      <div className="space-y-3">
        {/* 触发条件 */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <Button
            icon={<Sparkles className="h-3.5 w-3.5" />}
            loading={submitting && busyId === null}
            disabled={submitting}
            onClick={() => void trigger(extractableIds, force)}
          >
            开始知识点抽取（全部 {extractable.length} 份）
          </Button>
          <Button
            variant="secondary"
            loading={submitting && busyId === null}
            disabled={submitting || selected.length === 0}
            onClick={() => {
              const ids = selected
              setSelected([])
              void trigger(ids, force)
            }}
          >
            抽取选中的 {selected.length} 份
          </Button>
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-600">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 rounded border-slate-300"
              checked={force}
              onChange={(event) => setForce(event.target.checked)}
            />
            重新抽取（覆盖已有结果）
          </label>
        </div>
        <div className="text-[11px] leading-relaxed text-slate-400">
          默认不勾选「重新抽取」：只补跑缺失部分，已有结果不会被覆盖。勾选后会把这批素材已抽取的知识点
          <span className="text-amber-600">整体覆盖重写</span>
          ，仅在解析结果变了或上一轮抽得不满意时使用。
        </div>

        {/* 逐份素材的抽取入口（等价于每行一个「抽取」操作） */}
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
          {extractable.map((material) => (
            <li key={material.id} className="flex items-center gap-2 px-3 py-2">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 shrink-0 rounded border-slate-300"
                checked={selected.includes(material.id)}
                onChange={() => toggle(material.id)}
                aria-label={`选择 ${material.filename}`}
              />
              <span className="min-w-0 flex-1 truncate text-xs text-slate-700" title={material.filename}>
                {material.filename}
              </span>
              <span className="shrink-0 text-[11px] text-slate-400">
                {STATUS_LABEL[material.status] ?? material.status}
                {material.page_count > 0 ? ` · ${material.page_count} 页` : ''}
              </span>
              <Button
                variant="ghost"
                size="sm"
                loading={busyId === material.id}
                disabled={submitting}
                icon={<Sparkles className="h-3.5 w-3.5" />}
                onClick={() => void trigger([material.id], force)}
                title="只抽取这一份"
              >
                抽取
              </Button>
            </li>
          ))}
        </ul>

        <div className="flex items-center justify-end gap-2 text-[11px] text-slate-400">
          <button
            className="hover:text-slate-600"
            onClick={() => setSelected(extractableIds)}
            disabled={selected.length === extractable.length}
          >
            全选
          </button>
          <span>/</span>
          <button
            className="hover:text-slate-600"
            onClick={() => setSelected([])}
            disabled={selected.length === 0}
          >
            清空
          </button>
        </div>

        {submitError && <InlineError>{submitError}</InlineError>}
      </div>
    )
  }

  return (
    <section className="space-y-3">
      <div className="xizhi-card p-4">
        <header className="mb-3 flex items-baseline gap-2">
          <Sparkles className="h-4 w-4 shrink-0 text-brand-500" aria-hidden />
          <h2 className="text-sm font-semibold text-slate-800">知识点抽取</h2>
          <span className="text-xs text-slate-400">
            异步任务：单页 OCR 约需 140 秒，整批可能持续几十分钟
          </span>
        </header>
        {body()}
      </div>

      {/* 抽取任务进度：stage_detail 原样展示，预计耗时来自后端 estimated_seconds */}
      <JobProgressPanel
        title="知识点抽取进度"
        items={panelItems}
        jobs={displayJobs}
        onDismiss={handleDismiss}
        onRetry={handleRetry}
        renderAfter={renderAfter}
        dismissibleWhileRunning
        dismissLabel={runningCount > 0 ? '隐藏已完成' : '收起'}
        waitingLabel="任务已提交，等待后端返回进度…"
      />

      {jobError && (
        <InlineError>
          {jobError}
          <button className="ml-2 font-medium text-red-600 hover:underline" onClick={revalidate}>
            重新获取进度
          </button>
          <button
            className="ml-2 font-medium text-red-600 hover:underline"
            onClick={handleClearRecords}
            title="只清掉本页的任务记录，后端任务不会被取消"
          >
            清除本地任务记录
          </button>
        </InlineError>
      )}

      {runningCount > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-xs leading-relaxed text-slate-500">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
          <span>
            抽取在后端异步执行，你可以离开本页面去做别的 —— 任务不会被取消，进度由后端保留；
            回到本页会自动重新接上（本次浏览器会话内）。为避免重复任务，同一批素材请等当前任务结束后再触发。
          </span>
          <button
            className="ml-auto flex shrink-0 items-center gap-1 font-medium text-brand-600 hover:underline"
            onClick={revalidate}
            title="立即获取一次最新进度，不影响自动轮询的节奏"
          >
            <RotateCcw className="h-3 w-3" aria-hidden />
            刷新进度
          </button>
        </div>
      )}

      {runningCount === 0 && records.length > 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
          <Network className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
          本轮抽取任务都已结束。
          <Link className="ml-auto inline-flex items-center gap-1 font-medium text-brand-600 hover:underline" to="/graph">
            查看知识图谱
            <ArrowRight className="h-3 w-3" aria-hidden />
          </Link>
        </div>
      )}
    </section>
  )
}

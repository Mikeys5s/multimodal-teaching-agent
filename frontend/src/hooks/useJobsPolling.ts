import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '@/lib/endpoints'
import type { Job, JobStatus } from '@/lib/types'

const TERMINAL_STATUSES: JobStatus[] = ['done', 'failed', 'partial']

export interface UseJobsPollingOptions {
  /** 首次/有进展时的轮询间隔（毫秒），默认 1500 */
  intervalMs?: number
  /** 长时间无进展时的间隔上限（毫秒），默认 15000 */
  maxIntervalMs?: number
  /** 无进展时的间隔放大系数，默认 1.5 */
  backoffFactor?: number
  /** 任一任务进入 done/failed/partial 时回调一次，供上层刷新列表 */
  onSettled?: (job: Job) => void
}

export interface UseJobsPollingResult {
  /** job_id → 最新任务状态 */
  jobs: Record<string, Job>
  /** 最近一次轮询的失败原因（如后端中断），不影响已有进度展示 */
  error: string | null
  /** 是否仍有任务在轮询 */
  polling: boolean
  /** 立即补一次轮询（用户点「刷新进度」）。不打断退避节奏，也不会产生并发请求 */
  revalidate: () => void
}

/** 用「状态 + 进度 + 文案」判断任务是否真的在往前走 —— 有变化说明后端在推进，可缩短间隔 */
function progressSignature(job: Job | undefined): string {
  if (!job) return ''
  // stage_detail 可为 null（api-spec §6），拼字符串时统一成空串，避免把字面量 "null" 当文案参与比较
  return `${job.status}|${job.progress}|${job.stage_detail ?? ''}`
}

/**
 * 任务轮询（api-spec §1.4：耗时操作立即返回 job_id，前端轮询 /api/jobs/{job_id}）。
 *
 * 三条硬约束（P3 抽取任务要跑几十分钟，这三点都不能让步）：
 * 1. **退避**：后端有进展（status/progress/stage_detail 变化）时按 `intervalMs` 密集轮询，
 *    长时间没进展（例如 OCR 正在啃一页）按 `backoffFactor` 逐级放大到 `maxIntervalMs` 封顶，
 *    避免半小时的任务打出上千次请求；**取状态失败走同一条退避路径** ——
 *    后端宕机属于「拿不到新进展」，绝不能因此重置回最短间隔（否则会变成资源泄漏式的密集轮询）；
 * 2. **终止**：任务进入 done/failed/partial 后立刻移出轮询集合，全部终结即彻底停表，
 *    不会留下自转的定时器；
 * 3. **不重复请求**：同一 job_id 在途请求共享同一个 Promise（`inFlightRef`），
 *    手动刷新与定时 tick 撞车时也只会发一次 HTTP；
 *    卸载 / 依赖变化时 `cancelled` 标记 + `clearTimeout` 双保险，丢弃过期响应。
 */
export function useJobsPolling(
  jobIds: string[],
  options: UseJobsPollingOptions = {},
): UseJobsPollingResult {
  const { intervalMs = 1500, maxIntervalMs = 15000, backoffFactor = 1.5, onSettled } = options

  const [jobs, setJobs] = useState<Record<string, Job>>({})
  const [error, setError] = useState<string | null>(null)
  const [polling, setPolling] = useState(false)
  /** 手动补轮询：自增即让下面的 effect 重跑一次（会先清掉旧定时器与在途响应） */
  const [revision, setRevision] = useState(0)

  const settledRef = useRef<Set<string>>(new Set())
  const lastSignatureRef = useRef<Record<string, string>>({})
  const inFlightRef = useRef<Map<string, Promise<Job>>>(new Map())
  const onSettledRef = useRef(onSettled)
  onSettledRef.current = onSettled

  // 依赖用稳定字符串，避免数组字面量每次渲染都触发 effect
  const jobKey = jobIds.join(',')

  /** 带在途去重的取任务：同一个 job_id 的并发调用复用同一个 Promise */
  const fetchJob = useCallback((jobId: string): Promise<Job> => {
    const inFlight = inFlightRef.current.get(jobId)
    if (inFlight) return inFlight

    const promise = api.getJob(jobId)
    inFlightRef.current.set(jobId, promise)
    void promise.then(
      () => inFlightRef.current.delete(jobId),
      () => inFlightRef.current.delete(jobId),
    )
    return promise
  }, [])

  const revalidate = useCallback(() => setRevision((value) => value + 1), [])

  useEffect(() => {
    const pending = jobIds.filter((id) => !settledRef.current.has(id))
    if (pending.length === 0) {
      setPolling(false)
      return
    }

    let cancelled = false
    let timer: number | undefined
    let delay = intervalMs
    setPolling(true)

    const tick = async () => {
      // 每轮重新过滤：中途终结的任务立刻移出轮询，不再对它发请求
      const active = pending.filter((id) => !settledRef.current.has(id))
      if (cancelled || active.length === 0) {
        if (!cancelled) setPolling(false)
        return
      }

      const results = await Promise.allSettled(active.map((id) => fetchJob(id)))
      if (cancelled) return

      const fresh: Record<string, Job> = {}
      let firstError: string | null = null
      /** 本 tick 是否有任务真的往前走了（只有成功取回且签名变化才算） */
      let advanced = false
      /** 本 tick 是否有任务取状态失败 */
      let failed = false

      results.forEach((result, index) => {
        const jobId = active[index]
        if (result.status === 'fulfilled') {
          const job = result.value
          fresh[jobId] = job
          const signature = progressSignature(job)
          if (signature !== lastSignatureRef.current[jobId]) {
            lastSignatureRef.current[jobId] = signature
            advanced = true
          }
          if (TERMINAL_STATUSES.includes(job.status) && !settledRef.current.has(jobId)) {
            settledRef.current.add(jobId)
            onSettledRef.current?.(job)
          }
        } else {
          // 取状态失败不算任务失败：保持原有进度继续轮询，但**不重置间隔**
          failed = true
          if (!firstError) {
            firstError = (result.reason as Error)?.message ?? '任务状态获取失败'
          }
        }
      })

      setJobs((prev) => ({ ...prev, ...fresh }))
      setError(firstError)

      if (!active.some((id) => !settledRef.current.has(id))) {
        setPolling(false)
        return
      }

      // 退避：只有「有进展且本轮没出错」才回到最短间隔；
      // 无进展或取状态失败都逐级放大到 maxIntervalMs 封顶
      delay =
        advanced && !failed
          ? intervalMs
          : Math.min(Math.round(delay * backoffFactor), maxIntervalMs)
      timer = window.setTimeout(() => void tick(), delay)
    }

    void tick()

    // 卸载 / jobIds 变化 / 手动刷新：清定时器 + 让在途响应作废，避免定时器与 setState 泄漏
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobKey, intervalMs, maxIntervalMs, backoffFactor, revision, fetchJob])

  return { jobs, error, polling, revalidate }
}

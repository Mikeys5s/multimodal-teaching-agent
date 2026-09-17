import { useEffect, useRef, useState } from 'react'

import { api } from '@/lib/endpoints'
import type { Job, JobStatus } from '@/lib/types'

const TERMINAL_STATUSES: JobStatus[] = ['done', 'failed', 'partial']

export interface UseJobsPollingResult {
  /** job_id → 最新任务状态 */
  jobs: Record<string, Job>
  /** 最近一次轮询的失败原因（如后端中断），不影响已有进度展示 */
  error: string | null
  /** 是否仍有任务在轮询 */
  polling: boolean
}

/**
 * 任务轮询（api-spec §1.4：耗时操作立即返回 job_id，前端轮询 /api/jobs/{job_id}）。
 * - 只轮询未进入终态的任务，避免空转
 * - 任一任务进入 done/failed/partial 时触发 onSettled，供上层刷新素材清单
 */
export function useJobsPolling(
  jobIds: string[],
  options: { intervalMs?: number; onSettled?: (job: Job) => void } = {},
): UseJobsPollingResult {
  const { intervalMs = 1200, onSettled } = options

  const [jobs, setJobs] = useState<Record<string, Job>>({})
  const [error, setError] = useState<string | null>(null)
  const [polling, setPolling] = useState(false)

  const settledRef = useRef<Set<string>>(new Set())
  const onSettledRef = useRef(onSettled)
  onSettledRef.current = onSettled

  // 依赖用稳定字符串，避免数组字面量每次渲染都触发 effect
  const jobKey = jobIds.join(',')

  useEffect(() => {
    const pending = jobIds.filter((id) => !settledRef.current.has(id))
    if (pending.length === 0) {
      setPolling(false)
      return
    }

    let cancelled = false
    let timer: number | undefined
    setPolling(true)

    const tick = async () => {
      const results = await Promise.allSettled(pending.map((id) => api.getJob(id)))
      if (cancelled) return

      const fresh: Record<string, Job> = {}
      let firstError: string | null = null

      results.forEach((result, index) => {
        const jobId = pending[index]
        if (result.status === 'fulfilled') {
          const job = result.value
          fresh[jobId] = job
          if (TERMINAL_STATUSES.includes(job.status) && !settledRef.current.has(jobId)) {
            settledRef.current.add(jobId)
            onSettledRef.current?.(job)
          }
        } else if (!firstError) {
          firstError = (result.reason as Error)?.message ?? '任务状态获取失败'
        }
      })

      setJobs((prev) => ({ ...prev, ...fresh }))
      setError(firstError)

      const stillRunning = pending.some((id) => !settledRef.current.has(id))
      if (!stillRunning) {
        setPolling(false)
      } else {
        timer = window.setTimeout(tick, intervalMs)
      }
    }

    void tick()

    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobKey, intervalMs])

  return { jobs, error, polling }
}

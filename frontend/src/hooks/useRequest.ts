import { useCallback, useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'

import { ApiError } from '@/lib/api'

export interface UseRequestResult<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => Promise<T | null>
  setData: Dispatch<SetStateAction<T | null>>
}

/**
 * 极简请求 hook：统一 loading / error / reload。
 * error 始终是可直接展示的中文（来自后端 error.message 或本地兜底文案）。
 */
export function useRequest<T>(
  fn: () => Promise<T>,
  deps: unknown[] = [],
  options: { immediate?: boolean } = {},
): UseRequestResult<T> {
  const { immediate = true } = options
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fnRef = useRef(fn)
  fnRef.current = fn

  const reload = useCallback(async (): Promise<T | null> => {
    setLoading(true)
    setError(null)
    try {
      const result = await fnRef.current()
      setData(result)
      return result
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : ((err as Error)?.message ?? '请求失败，请稍后重试。')
      setError(message)
      return null
    } finally {
      setLoading(false)
    }
  }, deps)

  useEffect(() => {
    if (immediate) void reload()
  }, [reload, immediate])

  return { data, loading, error, reload, setData }
}

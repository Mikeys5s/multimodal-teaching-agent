import { useEffect, useState } from 'react'

import { api } from '@/lib/endpoints'
import type { Health } from '@/lib/types'

type Phase = 'checking' | 'online' | 'offline'

/**
 * 顶栏后端健康指示（api-spec §2 GET /api/health「演示前自检用」）。
 * 让"后端在不在"一眼可见 —— 演示前自检、开发期排障都靠它。
 */
export function BackendStatus() {
  const [phase, setPhase] = useState<Phase>('checking')
  const [health, setHealth] = useState<Health | null>(null)
  const [message, setMessage] = useState<string>('')

  useEffect(() => {
    let cancelled = false

    const check = async () => {
      try {
        const result = await api.health()
        if (cancelled) return
        setHealth(result)
        setPhase('online')
        setMessage('')
      } catch (err) {
        if (cancelled) return
        setHealth(null)
        setPhase('offline')
        setMessage((err as Error)?.message ?? '后端未连接')
      }
    }

    void check()
    const timer = window.setInterval(check, 30_000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  const color = phase === 'online' ? '#10b981' : phase === 'offline' ? '#ef4444' : '#94a3b8'
  const label =
    phase === 'online'
      ? `后端已连接${health?.version ? ` · ${health.version}` : ''}`
      : phase === 'offline'
        ? '后端未连接'
        : '正在检测后端…'

  return (
    <div
      className="flex items-center gap-2 text-xs text-slate-500"
      title={message || (health ? `db: ${health.db} · llm: ${health.llm}` : undefined)}
    >
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} aria-hidden />
      {label}
    </div>
  )
}

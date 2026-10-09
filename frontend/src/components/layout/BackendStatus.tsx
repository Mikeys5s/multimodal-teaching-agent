import { useEffect, useState } from 'react'

import { api } from '@/lib/endpoints'
import type { Health } from '@/lib/types'

type Phase = 'checking' | 'online' | 'offline'

/**
 * 顶栏后端健康指示（api-spec §2 GET /api/health「演示前自检用」）。
 * 连接状态同时显示文字（不靠颜色单独传达），30 秒轮询。
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

  const color = phase === 'online' ? '#166534' : phase === 'offline' ? '#991b1b' : '#64748b'
  const label =
    phase === 'online'
      ? `后端已连接${health?.version ? ` · ${health.version}` : ''}`
      : phase === 'offline'
        ? '后端未连接'
        : '正在检测后端…'

  return (
    <div
      className="flex shrink-0 items-center gap-2 text-xs text-slate-500"
      title={message || (health ? `db: ${health.db} · llm: ${health.llm}` : undefined)}
      role="status"
    >
      <span className="relative flex h-2 w-2" aria-hidden>
        {phase === 'checking' && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-slate-400 opacity-60" />
        )}
        <span className="relative inline-flex h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
      </span>
      <span className="max-w-[10rem] truncate sm:max-w-none">{label}</span>
    </div>
  )
}

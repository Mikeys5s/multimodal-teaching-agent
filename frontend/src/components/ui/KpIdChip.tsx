import { Hash } from 'lucide-react'
import { useState } from 'react'

/**
 * `kp_id` 溯源锚（方案 C②：从"正文一行"降级为"可查小标签"）。
 *
 * 为什么不直接隐藏：`kp_id` 是「溯源覆盖率 100%」这条卖点在界面上的**唯一可见凭据**
 * —— 评委问「依据是什么」时，界面上得有个能核对的东西。
 * 所以它**不该消失，只该不抢戏**：正文只留 `#022` 这样的短编号，
 * 完整 id 收进悬停提示、点击即复制（便于对照接口与数据库）。
 */
export function KpIdChip({ kpId, className = '' }: { kpId: string; className?: string }) {
  const [copied, setCopied] = useState(false)
  const short = `#${kpId.slice(-3)}`

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(kpId)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      /* 剪贴板不可用（非 https / 无权限）时不阻塞，完整 id 仍在悬停提示里 */
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      title={`知识点 id（点击复制）：${kpId}`}
      aria-label={`复制知识点 id ${kpId}`}
      className={[
        'inline-flex min-h-6 items-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-xs text-slate-400',
        'transition-colors duration-120 hover:bg-slate-100 hover:text-slate-600',
        className,
      ].join(' ')}
    >
      <Hash className="h-3 w-3" aria-hidden />
      {copied ? '已复制' : short}
    </button>
  )
}

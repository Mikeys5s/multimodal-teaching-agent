import { Construction } from 'lucide-react'

import { Tag } from '@/components/ui/Badge'

export interface PlaceholderProps {
  title: string
  milestone: string
  note: string
  endpoints: string[]
}

/**
 * 占位页。用于尚未到排期的页面 —— 严格遵循 SPEC §8.2，
 * 不在 D2 提前实现 D6–D8 的功能，只把结构与契约列清楚。
 */
export function Placeholder({ title, milestone, note, endpoints }: PlaceholderProps) {
  return (
    <div className="mx-auto max-w-3xl">
      <div className="xizhi-card p-6">
        <div className="flex items-center gap-2 text-xs font-medium text-brand-600">
          <Construction className="h-3.5 w-3.5" aria-hidden />
          排期：{milestone}
        </div>
        <h2 className="mt-2 text-lg font-semibold text-slate-800">{title}</h2>
        <p className="mt-2 text-sm leading-relaxed text-slate-500">{note}</p>

        <div className="mt-5">
          <div className="mb-2 text-xs font-medium text-slate-500">将对接的端点（api-spec §7）</div>
          <div className="flex flex-wrap gap-1.5">
            {endpoints.map((endpoint) => (
              <Tag key={endpoint}>{endpoint}</Tag>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

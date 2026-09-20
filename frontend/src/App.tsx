import {
  BarChart3,
  LayoutDashboard,
  ListOrdered,
  MessagesSquare,
  Network,
  Upload,
} from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { BackendStatus } from '@/components/layout/BackendStatus'

/** 侧栏导航配置 —— 路由与 api-spec §8「前端路由与端点对应」保持一致 */
export interface NavItem {
  to: string
  label: string
  hint: string
  icon: typeof LayoutDashboard
  end?: boolean
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: '概览', hint: '质量总览', icon: LayoutDashboard, end: true },
  { to: '/materials', label: '素材工作台', hint: '上传与解析', icon: Upload },
  { to: '/graph', label: '知识图谱', hint: '依赖 DAG', icon: Network },
  { to: '/path', label: '学习路径', hint: '拓扑推荐', icon: ListOrdered },
  { to: '/tutor', label: '答疑辅导', hint: '苏格拉底引导', icon: MessagesSquare },
  { to: '/report', label: '质量报告', hint: '工程严谨度', icon: BarChart3 },
]

function useCurrentNav(): NavItem | undefined {
  const { pathname } = useLocation()
  return (
    NAV_ITEMS.find((item) => (item.end ? pathname === item.to : pathname.startsWith(item.to)))
  )
}

export default function App() {
  const current = useCurrentNav()

  return (
    <div className="flex h-full">
      {/* 侧栏 */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-5 py-4">
          <div className="text-lg font-semibold tracking-tight text-slate-900">析知 XiZhi</div>
          <div className="mt-0.5 text-xs text-slate-500">多模态教学智能体</div>
        </div>

        <nav className="flex-1 space-y-1 p-3">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  [
                    'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors',
                    isActive
                      ? 'bg-brand-50 font-medium text-brand-700'
                      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
                  ].join(' ')
                }
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden />
                <span className="flex-1">{item.label}</span>
              </NavLink>
            )
          })}
        </nav>

        <div className="border-t border-slate-200 px-5 py-3 text-[11px] leading-relaxed text-slate-400">
          SPEC v2.3 · 已冻结基线
          <br />
          偏离本 SPEC 的实现视为缺陷
        </div>
      </aside>

      {/* 主区 */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6">
          <div className="flex items-baseline gap-3">
            <h1 className="text-base font-semibold text-slate-900">{current?.label ?? '析知'}</h1>
            <span className="text-xs text-slate-400">{current?.hint}</span>
          </div>
          <BackendStatus />
        </header>

        <main className="min-h-0 flex-1 overflow-auto px-6 py-5">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

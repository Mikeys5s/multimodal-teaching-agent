import {
  BarChart3,
  LayoutDashboard,
  ListOrdered,
  Menu,
  MessagesSquare,
  Network,
  Upload,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
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

function BrandBlock() {
  return (
    <div className="px-5 py-4">
      <div className="flex items-center gap-2.5">
        {/* 记忆点徽标：节点 + 依赖边，呼应「知识地图」母题 */}
        <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden className="shrink-0">
          <path d="M7 19 L19 7" stroke="#2563eb" strokeWidth="1.6" strokeDasharray="0" />
          <circle cx="7" cy="19" r="3.2" fill="#eff6ff" stroke="#2563eb" strokeWidth="1.6" />
          <circle cx="19" cy="7" r="3.2" fill="#2563eb" />
          <circle cx="19" cy="19" r="2.2" fill="none" stroke="#94a3b8" strokeWidth="1.4" strokeDasharray="2.5 2.5" />
        </svg>
        <div>
          <div className="text-lg font-semibold tracking-tight text-slate-900">析知 XiZhi</div>
          <div className="mt-0.5 text-xs text-slate-500">多模态教学智能体</div>
        </div>
      </div>
    </div>
  )
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex-1 space-y-1 overflow-y-auto p-3" aria-label="主导航">
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              [
                'flex min-h-11 items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors duration-120',
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
  )
}

function SpecNote() {
  return (
    <div className="border-t border-slate-200 px-5 py-3 text-xs leading-relaxed text-slate-400">
      SPEC v2.3 · 已冻结基线
      <br />
      偏离本 SPEC 的实现视为缺陷
    </div>
  )
}

export default function App() {
  const current = useCurrentNav()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const drawerRef = useRef<HTMLDivElement>(null)
  const { pathname } = useLocation()

  // 路由变化时关闭抽屉
  useEffect(() => {
    setDrawerOpen(false)
  }, [pathname])

  // 抽屉打开期间：锁定 body 滚动、Escape 关闭、焦点进入抽屉；关闭后焦点回到菜单按钮
  useEffect(() => {
    if (!drawerOpen) return
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    drawerRef.current?.querySelector<HTMLElement>('a, button')?.focus()

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setDrawerOpen(false)
        menuButtonRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = prevOverflow
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [drawerOpen])

  const closeDrawer = () => {
    setDrawerOpen(false)
    menuButtonRef.current?.focus()
  }

  return (
    <div className="flex h-full min-w-0">
      {/* 桌面侧栏（≥lg 常驻） */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
        <div className="border-b border-slate-200">
          <BrandBlock />
        </div>
        <NavList />
        <SpecNote />
      </aside>

      {/* 移动抽屉（<lg） */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="导航菜单">
          <div
            className="absolute inset-0 bg-slate-900/40"
            onClick={closeDrawer}
            aria-hidden
          />
          <div
            ref={drawerRef}
            className="absolute inset-y-0 left-0 flex w-72 max-w-[320px] flex-col bg-white shadow-overlay transition-transform duration-220"
          >
            <div className="flex items-center justify-between border-b border-slate-200 pr-2">
              <div className="flex-1">
                <BrandBlock />
              </div>
              <button
                type="button"
                onClick={closeDrawer}
                aria-label="关闭导航菜单"
                className="mr-2 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900"
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
            </div>
            <NavList onNavigate={closeDrawer} />
            <SpecNote />
          </div>
        </div>
      )}

      {/* 主区 */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <button
              ref={menuButtonRef}
              type="button"
              onClick={() => setDrawerOpen(true)}
              aria-label="打开导航菜单"
              aria-expanded={drawerOpen}
              className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 hover:text-slate-900 lg:hidden"
            >
              <Menu className="h-5 w-5" aria-hidden />
            </button>
            <div className="flex min-w-0 items-baseline gap-3">
              <h1 className="truncate text-base font-semibold text-slate-900">{current?.label ?? '析知'}</h1>
              <span className="hidden truncate text-xs text-slate-400 sm:inline">{current?.hint}</span>
            </div>
          </div>
          <BackendStatus />
        </header>

        <main className="min-h-0 min-w-0 flex-1 overflow-auto px-4 py-5 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

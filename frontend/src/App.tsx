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

/** Learning Atlas 品牌块：lime 地图徽标 + 名称 + 制图档案编号 */
function BrandBlock() {
  return (
    <div className="flex items-center gap-3 border-b border-white/10 px-2 pb-6 pt-1">
      <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"
        aria-hidden className="shrink-0 text-lime">
        <circle cx="6" cy="6" r="2.5" fill="currentColor" stroke="none" />
        <circle cx="18" cy="6" r="2.5" />
        <circle cx="12" cy="18" r="2.5" />
        <path d="M8.5 6h7M7.5 8l3 7M16.5 8l-3 7" />
      </svg>
      <div className="min-w-0">
        <div className="truncate text-xl font-bold leading-none tracking-tight text-[#f8f5ec]">
          析知 <span className="font-medium text-[#9ba8b8]">XiZhi</span>
        </div>
        <div className="mt-1.5 text-[10px] uppercase tracking-[0.13em] text-[#a9b4c1]">
          LEARNING ATLAS / 01
        </div>
      </div>
    </div>
  )
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex-1 space-y-1.5 overflow-y-auto py-3" aria-label="主导航">
      <div className="px-2 pb-2 pt-4 text-[10px] font-bold uppercase tracking-[0.19em] text-[#7f8da0]">
        Workspace
      </div>
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
                'flex min-h-11 items-center gap-3 rounded-xl border border-transparent px-3 text-[13px] transition-all duration-220',
                isActive
                  ? 'border-[#7e99ff]/30 bg-gradient-to-r from-brand-600/30 to-brand-600/5 font-medium text-white shadow-[inset_3px_0_0_0_#7292ff]'
                  : 'text-[#c6ced8] hover:translate-x-0.5 hover:bg-white/5 hover:text-white',
              ].join(' ')
            }
          >
            <Icon className="h-[17px] w-[17px] shrink-0" aria-hidden />
            <span className="flex-1 truncate">{item.label}</span>
          </NavLink>
        )
      })}
    </nav>
  )
}

/** SPEC 冻结提示 —— 基线纪律必须保留可见（必要信息不低于 12px） */
function SpecNote() {
  return (
    <div className="border-t border-white/10 px-2.5 pb-1 pt-3 text-xs leading-relaxed text-[#94a1b2]">
      <strong className="font-semibold text-lime">SPEC v2.3</strong>
      <br />
      知识有来处，学习有方向。
      <br />
      已冻结基线 · 偏离属于缺陷
    </div>
  )
}

/** 深色制图侧栏（桌面常驻 + 移动抽屉共用） */
function AtlasRail({ onNavigate, showClose, onClose }: { onNavigate?: () => void; showClose?: boolean; onClose?: () => void }) {
  return (
    <div className="relative flex h-full flex-col overflow-hidden bg-atlas-ink px-4 py-6 text-[#f8f5ec]">
      {/* 制图氛围层（纯装饰） */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'linear-gradient(160deg, rgba(49,92,255,0.12), transparent 38%), radial-gradient(circle at 15% 90%, rgba(98,200,180,0.10), transparent 29%)',
        }}
      />
      <div className="relative z-10 flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <BrandBlock />
        </div>
        {showClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭导航菜单"
            className="-mr-1 -mt-1 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-[#c6ced8] hover:bg-white/10 hover:text-white"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        )}
      </div>
      <div className="relative z-10 flex min-h-0 flex-1 flex-col">
        <NavList onNavigate={onNavigate} />
      </div>
      <div className="relative z-10">
        <SpecNote />
      </div>
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
      {/* 桌面侧栏（≥lg 常驻，240px） */}
      <aside className="hidden w-60 shrink-0 lg:block">
        <AtlasRail />
      </aside>

      {/* 移动抽屉（<lg，≤320px 左抽屉 + 遮罩） */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="导航菜单">
          <div
            className="absolute inset-0 bg-slate-900/40"
            onClick={closeDrawer}
            aria-hidden
          />
          <div
            ref={drawerRef}
            className="absolute inset-y-0 left-0 w-72 max-w-[320px] shadow-overlay"
          >
            <AtlasRail onNavigate={closeDrawer} showClose onClose={closeDrawer} />
          </div>
        </div>
      )}

      {/* 主区 */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-[62px] shrink-0 items-center justify-between gap-3 border-b border-[#101c2e]/10 bg-atlas-sheet/70 px-4 backdrop-blur-md sm:px-8">
          <div className="flex min-w-0 items-center gap-2.5">
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
            {/* 面包屑：知识工作台 / 当前页（小屏收起面包屑、保留页名） */}
            <nav aria-label="当前位置" className="flex min-w-0 items-center gap-2 text-xs text-[#7d8490]">
              <span className="hidden sm:inline">知识工作台</span>
              <span aria-hidden className="hidden text-[#c1b8a9] sm:inline">/</span>
              <h1 className="truncate text-sm font-semibold text-atlas-ink">{current?.label ?? '析知'}</h1>
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-4">
            <BackendStatus />
            <span
              aria-hidden
              className="hidden h-[27px] w-[27px] items-center justify-center rounded-full bg-brand-600 text-2xs font-bold text-white sm:inline-flex"
              title="析知 XiZhi"
            >
              知
            </span>
          </div>
        </header>

        {/* key=pathname：切页时整组内容以 220ms 淡入上移（reduced-motion 时瞬时切换） */}
        <main key={pathname} className="xizhi-page-enter min-h-0 min-w-0 flex-1 overflow-auto px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

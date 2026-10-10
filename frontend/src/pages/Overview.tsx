import { ArrowRight, ArrowUpRight, Layers, MessagesSquare, Route, ShieldCheck, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '@/lib/endpoints'
import { dupGroupSize, kpDisplayTitle } from '@/lib/kpTitle'

/**
 * 概览页 —— Learning Atlas 主视觉（2026-10-10 v2，2026-10-10 返修）。
 * 构图：编辑式大标题 + 深蓝制图 hero（路径描绘动画）+ 四步流程带 + A-D 直达入口 + 原则板。
 * 文案约束：
 *  - QUICK_TOURS 的三个纪律不破坏：① 点了直达（深链来自运行时数据）② 文案自解释 ③ 数量 3–4 个；
 *  - **不允许固定数字与固定实体 ID**（2026-10-10 返修 P0）：入口里的知识点总数、同组副本数、
 *    「出现 N 处」和深链目标全部由 `/api/knowledge-points` 与 `/api/learning-path` 的实时响应算出；
 *    接口失败时回落为不含数字、不带实体参数的文案与路由，绝不写死默认值。
 */

/** 四步流程（对应三段管线的编辑式表达；纯展示，导航在下方 A-D 入口） */
const FLOW_STEPS = [
  { no: '01', title: '收进材料', desc: '保留原始文件与来源' },
  { no: '02', title: '抽取结构', desc: '识别知识点与关系' },
  { no: '03', title: '看见路径', desc: '沿着前置逐步学习' },
  { no: '04', title: '追问理解', desc: '先思考，再得到引导' },
]

/** 入口 C 的运行时数据：重复组中最大的一个合并知识点（深链目标 + 「出现 N 处」的 N） */
interface DupShowcase {
  id: string
  name: string
  size: number
}

/** 入口 A 的运行时数据：一条真实的学习路径（深链目标 + 实际步数） */
interface PathShowcase {
  id: string
  name: string
  steps: number
}

interface OverviewData {
  /** 知识点总数（/api/knowledge-points 的 total） */
  total: number
  /** 同组副本数：重复组成员数 − 重复组数（成员 = is_duplicate 或 duplicate_group_size > 1） */
  dupCopies: number
  dup: DupShowcase | null
  path: PathShowcase | null
}

const KP_PAGE_SIZE = 100

/**
 * 拉全量知识点并算出入口 A / C 需要的数据。
 * 模块级缓存：StrictMode 双跑 effect、切页再回来都不会重复请求。
 * 失败时 resolve(null) —— 调用方回落到无数字文案，不把错误堆到首页。
 */
let overviewDataPromise: Promise<OverviewData | null> | null = null
function loadOverviewData(): Promise<OverviewData | null> {
  overviewDataPromise ??= (async (): Promise<OverviewData | null> => {
    try {
      const first = await api.listKnowledgePoints({ page: 1, page_size: KP_PAGE_SIZE })
      const pageCount = Math.max(1, Math.ceil(first.total / first.page_size))
      const rest = await Promise.all(
        Array.from({ length: pageCount - 1 }, (_, i) =>
          api.listKnowledgePoints({ page: i + 2, page_size: KP_PAGE_SIZE }),
        ),
      )
      const items = [first, ...rest].flatMap((page) => page.items)

      let dupMembers = 0
      const dupGroups = new Set<string>()
      let dup: DupShowcase | null = null
      let pathCandidate: { id: string; name: string; prereq: number } | null = null
      for (const kp of items) {
        const size = dupGroupSize(kp)
        if (kp.is_duplicate || size !== null) {
          dupMembers += 1
          dupGroups.add(kp.duplicate_of ?? kp.id)
          if (size !== null && (dup === null || size > dup.size)) {
            dup = { id: kp.id, name: kpDisplayTitle(kp), size }
          }
        }
        const prereq = kp.prerequisite_count ?? 0
        if (prereq > (pathCandidate?.prereq ?? 0)) {
          pathCandidate = { id: kp.id, name: kpDisplayTitle(kp), prereq }
        }
      }

      let path: PathShowcase | null = null
      if (pathCandidate) {
        try {
          const steps = await api.getLearningPath(pathCandidate.id)
          if (steps.length > 0) {
            path = {
              id: pathCandidate.id,
              name: kpDisplayTitle(steps[steps.length - 1]) || pathCandidate.name,
              steps: steps.length,
            }
          }
        } catch {
          // 路径拉取失败：入口 A 回落为无参数路由
        }
      }

      return { total: first.total, dupCopies: dupMembers - dupGroups.size, dup, path }
    } catch {
      return null
    }
  })()
  return overviewDataPromise
}

/** 入口描述里的知识点名：过长时截断，防止把卡片撑破（完整名落到目标页展示） */
function shortName(name: string, max = 14): string {
  return name.length > max ? `${name.slice(0, max)}…` : name
}

/** 「从这看起」A–D 直达入口：B / D 为静态文案，A / C 的深链与数字来自运行时数据 */
function useQuickTours() {
  const [data, setData] = useState<OverviewData | null>(null)
  useEffect(() => {
    let cancelled = false
    void loadOverviewData().then((result) => {
      if (!cancelled) setData(result)
    })
    return () => {
      cancelled = true
    }
  }, [])

  return [
    {
      num: 'A',
      icon: Route,
      title: '看依赖图与学习路径',
      desc: data?.path
        ? `打开「${shortName(data.path.name)}」的 ${data.path.steps} 步先修链，每步都写明先后关系。`
        : '打开一个知识点的先修链：先修在前、目标在后，每步都写明先后关系。',
      to: data?.path ? `/path?kp_id=${data.path.id}` : '/path',
    },
    {
      num: 'B',
      icon: MessagesSquare,
      title: '看多轮答疑怎么「降级直讲」',
      desc: '首轮只反问不给答案；连续两次答不上，才降级为直接讲解。',
      to: '/tutor',
    },
    {
      num: 'C',
      icon: Layers,
      title: '看我们怎么处理重复数据',
      desc:
        data?.dup != null
          ? `${data.total} 个知识点里 ${data.dupCopies} 个是同组副本：只标注、不删数据 —— 打开能看到「出现 ${data.dup.size} 处，已合并显示」。`
          : '重复的知识点只标注、不删数据 —— 节点详情会写明它在材料中出现了几处、已合并显示。',
      to: data?.dup ? `/graph?kp_id=${data.dup.id}` : '/graph',
    },
    {
      num: 'D',
      icon: ShieldCheck,
      title: '看校验体系',
      desc: '质量报告页汇总全链路复验与部署自检：环数、溯源覆盖、字段完备都在这一页。',
      to: '/report',
    },
  ]
}

/** Atlas 主视觉 SVG：路径沿虚线流动，节点带光晕（纯装饰，不代表真实数据） */
function AtlasVisual() {
  return (
    <div className="relative z-10 grid min-h-[220px] place-items-center overflow-hidden sm:min-h-[300px]">
      <span className="absolute right-10 top-10 font-serif text-xs italic tracking-wide text-[#9eabbc]" aria-hidden>
        SOURCE / 04
      </span>
      <span className="absolute bottom-8 right-14 font-serif text-xs italic tracking-wide text-lime" aria-hidden>
        NEXT: UNDERSTAND
      </span>
      <svg viewBox="0 0 600 330" role="img" aria-label="知识节点与学习路径示意图"
        className="h-[220px] w-full max-w-[600px] overflow-visible sm:h-[300px]">
        <defs>
          <linearGradient id="atlas-route" x1="0" x2="1">
            <stop stopColor="#315cff" />
            <stop offset="0.55" stopColor="#62c8b4" />
            <stop offset="1" stopColor="#d9ed83" />
          </linearGradient>
          <filter id="atlas-glow">
            <feGaussianBlur stdDeviation="6" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <path d="M54 229 C118 205 116 120 189 133 S272 237 326 196 S388 79 449 106 S506 195 562 112"
          fill="none" stroke="url(#atlas-route)" strokeWidth="2.6" className="atlas-draw" />
        <path d="M54 229 C118 205 116 120 189 133 S272 237 326 196 S388 79 449 106 S506 195 562 112"
          fill="none" stroke="#c4d0df" strokeWidth="0.8" strokeDasharray="2 8" opacity="0.5" />
        <path d="M189 133 C212 67 260 56 296 82 M326 196 C355 251 408 259 455 232 M449 106 C466 59 499 49 527 62"
          fill="none" stroke="#93a3b6" strokeWidth="1" strokeDasharray="3 6" opacity="0.55" />
        <g fill="#101c2e" stroke="#d6e1ee" strokeWidth="1.4">
          <circle cx="54" cy="229" r="11" />
          <circle cx="189" cy="133" r="13" />
          <circle cx="326" cy="196" r="12" />
          <circle cx="449" cy="106" r="14" />
          <circle cx="562" cy="112" r="10" />
        </g>
        <g className="atlas-breathe" filter="url(#atlas-glow)">
          <circle cx="449" cy="106" r="6" fill="#d9ed83" />
        </g>
        <circle cx="562" cy="112" r="4" fill="#62c8b4" />
        <g fill="#bdc9d6" fontSize="9" fontFamily="Arial,sans-serif">
          <text x="27" y="258">SOURCE</text>
          <text x="164" y="163">CONCEPT</text>
          <text x="297" y="223">RELATION</text>
          <text x="418" y="78" fill="#d9ed83">INSIGHT</text>
          <text x="536" y="145">NEXT</text>
        </g>
        <g fill="#73849a" fontSize="7" fontFamily="Arial,sans-serif">
          <text x="78" y="213">01</text>
          <text x="212" y="122">02</text>
          <text x="348" y="184">03</text>
          <text x="475" y="100">04</text>
          <text x="576" y="98">05</text>
        </g>
      </svg>
      <span className="absolute bottom-3 right-5 text-[9px] tracking-[0.08em] text-[#9ba9b9]" aria-hidden>
        RELATIONSHIP, NOT A FLAT LIST
      </span>
    </div>
  )
}

export default function Overview() {
  const quickTours = useQuickTours()
  return (
    <div className="mx-auto max-w-6xl">
      {/* 编辑式 eyebrow */}
      <div className="atlas-eyebrow mb-4">
        <span className="idx">01</span> A MAP FOR LEARNING
        <span className="kick">把知识，读成一张地图</span>
      </div>

      {/* 深蓝 Atlas 主视觉 */}
      <section className="atlas-navy-panel">
        <div aria-hidden className="atlas-map-grid absolute inset-0 [mask-image:linear-gradient(90deg,black,transparent_90%)]" />
        <div
          aria-hidden
          className="pointer-events-none absolute -top-56 right-0 h-[500px] w-[500px] rounded-full border border-lime/15 shadow-[0_0_0_40px_rgba(217,237,131,0.025),0_0_0_90px_rgba(217,237,131,0.018)]"
        />
        <div className="relative grid lg:grid-cols-[minmax(360px,0.92fr)_minmax(400px,1.08fr)]">
          <div className="relative z-10 flex flex-col items-start px-7 py-9 sm:px-10 sm:py-10">
            <div className="atlas-eyebrow !text-[#b8c3d1]">
              <span className="idx !text-lime">XiZhi / Atlas</span> MULTIMODAL TEACHING INTELLIGENCE
            </div>
            <h2 className="mt-6 max-w-[520px] text-[2.4rem] font-bold leading-[1.09] tracking-[-0.04em] sm:text-[3rem]">
              让每份材料
              <br />
              长出一条
              <em className="whitespace-nowrap font-serif font-medium italic tracking-[-0.03em] text-lime">学习路径。</em>
            </h2>
            <p className="mt-4 max-w-[430px] text-[13px] leading-relaxed text-[#b8c1cd]">
              从资料解析、知识结构到追问引导。每个结论保留来源，每一步学习都有前后关系。
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-4">
              <Link
                to="/materials"
                className="inline-flex h-11 min-w-0 items-center gap-2 rounded-lg bg-lime px-4 text-sm font-semibold text-atlas-ink shadow-[0_8px_20px_rgba(217,237,131,0.12)] transition-all duration-160 hover:bg-[#e4f6a2] hover:-translate-y-0.5"
              >
                <Upload className="h-4 w-4" aria-hidden />
                开始上传材料
              </Link>
              <Link
                to="/graph"
                className="inline-flex items-center gap-1 text-sm text-[#d5dbe3] transition-colors duration-120 hover:text-lime"
              >
                进入知识地图
                <ArrowUpRight className="h-4 w-4" aria-hidden />
              </Link>
            </div>
          </div>
          <AtlasVisual />
        </div>
      </section>

      {/* 四步流程带 */}
      <section aria-label="流程" className="mt-4 grid grid-cols-2 border-y border-[#c9c3b7] bg-atlas-sheet/55 md:grid-cols-4">
        {FLOW_STEPS.map((step, i) => (
          <div
            key={step.no}
            className={[
              'flex items-center gap-3 px-4 py-4',
              i !== FLOW_STEPS.length - 1 ? 'md:border-r md:border-[#d7d0c3]' : '',
              i % 2 === 0 ? 'border-r border-[#d7d0c3] md:border-r' : '',
              i < 2 ? 'border-b border-[#d7d0c3] md:border-b-0' : '',
            ].join(' ')}
          >
            <span className="font-serif text-xl italic text-coral">{step.no}</span>
            <span className="min-w-0">
              <span className="block text-xs font-semibold text-atlas-ink">{step.title}</span>
              <span className="mt-0.5 block text-xs text-atlas-muted">{step.desc}</span>
            </span>
          </div>
        ))}
      </section>

      {/* A–D 直达入口 + 原则板 */}
      <section className="mt-6 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-2xl border border-atlas-line bg-atlas-sheet p-5 sm:p-6">
          <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h3 className="text-lg font-bold tracking-tight text-atlas-ink">从这里继续</h3>
            <span className="text-xs text-atlas-muted">
              四个入口对应演示的四个环节 —— 每个点了都直接落到那一步
            </span>
          </div>
          <div className="grid sm:grid-cols-2">
            {quickTours.map((tour) => {
              const Icon = tour.icon
              return (
                <Link
                  key={tour.num}
                  to={tour.to}
                  className="group grid grid-cols-[27px_minmax(0,1fr)_15px] items-center gap-2 border-t border-[#e8e3d8] py-3.5 text-atlas-ink"
                >
                  <span className="font-serif text-base italic text-coral">{tour.num}</span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5 text-[13px] font-semibold transition-colors duration-120 group-hover:text-brand-600">
                      <Icon className="h-3.5 w-3.5 text-brand-600" aria-hidden />
                      {tour.title}
                    </span>
                    <span className="mt-1 block text-xs leading-relaxed text-atlas-muted">{tour.desc}</span>
                  </span>
                  <ArrowRight
                    className="h-3.5 w-3.5 text-brand-600 transition-transform duration-120 group-hover:translate-x-0.5"
                    aria-hidden
                  />
                </Link>
              )
            })}
          </div>
        </div>

        <div className="relative overflow-hidden rounded-2xl bg-brand-600 p-6 text-white">
          <div
            aria-hidden
            className="pointer-events-none absolute -bottom-24 -right-9 h-52 w-52 rounded-full border border-white/25 shadow-[0_0_0_28px_rgba(255,255,255,0.07),0_0_0_58px_rgba(255,255,255,0.04)]"
          />
          <div className="font-serif text-4xl italic leading-[0.8] text-lime" aria-hidden>“</div>
          <p className="relative z-10 mt-4 max-w-[290px] text-base font-semibold leading-relaxed">
            知识不该是散落的答案，而是能追溯、能连接、能继续前进的结构。
          </p>
          <small className="relative z-10 mt-5 block text-[10px] tracking-[0.12em] text-[#d9e0ff]">
            THE XI ZHI PRINCIPLE / 01
          </small>
        </div>
      </section>

      {/* 产品原则（既有内容保留，压缩为脚注行，不丢失信息） */}
      <p className="mt-5 text-center text-xs leading-relaxed text-atlas-muted">
        产品原则 —— 宁缺毋错：检索不到就明说「材料里没有」 · 显式不确定性：存疑处主动标出 ·
        先结论后细节 · 可见的溯源：任何来自材料的断言都能一点回到原文
      </p>
    </div>
  )
}

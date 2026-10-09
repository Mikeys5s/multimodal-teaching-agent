import { FileText, Network, MessagesSquare, ArrowRight, Upload, Route, Layers, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'

const STAGES = [
  {
    icon: FileText,
    step: '01',
    title: 'Stage 1 · 素材解析',
    desc: 'PDF / Word / PPT / 图片统一转为带页码锚点的 Markdown，输出素材清单与存疑处。',
    to: '/materials',
    cta: '去上传素材',
  },
  {
    icon: Network,
    step: '02',
    title: 'Stage 2 · 知识点结构化',
    desc: '章—节—知识点三级结构，五要素齐全，构建知识点依赖 DAG 与学习路径。',
    to: '/graph',
    cta: '查看知识图谱',
  },
  {
    icon: MessagesSquare,
    step: '03',
    title: 'Stage 3 · 交互式答疑',
    desc: '苏格拉底式引导：先反问、再提示、答不上两次才直接讲解；每轮给出卡点与下一步。',
    to: '/tutor',
    cta: '进入答疑辅导',
  },
]

/**
 * 「从这看起」—— 四个**可点击直达**的入口。
 *
 * 为什么要有它：本作品有 629 个知识点、28 个端点。评委自己打开时**不知道该点哪个**，
 * 容易随便点两下就走。这里的每一入口对应演讲里的**一镜**，且**点了就落到那一镜**，
 * 不依赖讲解也能看懂（2026-10-08 分工会议定的）。
 *
 * ⚠️ 三条约束（写在需求里的，别在后续改动中破坏）：
 *   1. **点了能直达** —— 不是跳首页再让人自己找，所以带 `?kp_id=` 深链；
 *   2. **文案自解释** —— 每条的说明都能独立说清「这是干嘛的」；
 *   3. **数量 3–4 个** —— 多了又变成「不知道该点哪个」。
 */
const QUICK_TOURS = [
  {
    icon: Route,
    title: '看依赖图与学习路径',
    desc: '打开「拥塞控制」这一点的 4 步先修链：先修在左、后修在右，每一步都写明排序依据。',
    to: '/path?kp_id=kp_cf6fcaa0_000_000_028',
    cta: '打开学习路径',
  },
  {
    icon: MessagesSquare,
    title: '看多轮答疑怎么「降级直讲」',
    desc: '首轮只反问不给答案；连续两次答不上，才降级为直接讲解。页面上有可直接点的示例问题。',
    to: '/tutor',
    cta: '进入答疑辅导',
  },
  {
    icon: Layers,
    title: '看我们怎么处理重复数据',
    desc: '629 个知识点里 462 个是同组副本。我们只做标注、不删数据 —— 打开就能看到「出现 35 处，已合并显示」。',
    to: '/graph?kp_id=kp_42b16cd4_000_000_012',
    cta: '打开该知识点',
  },
  {
    icon: ShieldCheck,
    title: '看校验体系',
    desc: '质量报告页汇总全链路复验与部署自检的结果：DAG 环数、溯源覆盖率、字段完备率都在这一页。',
    to: '/report',
    cta: '打开质量报告',
  },
]

/** 装饰性「知识路线」插图：纯装饰（aria-hidden），不代表真实数据 */
function MapMotif({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 200 120" fill="none" aria-hidden className={className}>
      <path d="M20 96 C 60 96, 70 60, 105 60 S 150 26, 182 26" stroke="#bfdbfe" strokeWidth="1.6" />
      <path d="M20 96 C 55 96, 62 78, 88 78" stroke="#dbeafe" strokeWidth="1.4" strokeDasharray="3 4" />
      <circle cx="20" cy="96" r="5" fill="#eff6ff" stroke="#2563eb" strokeWidth="1.8" />
      <circle cx="105" cy="60" r="5" fill="#eff6ff" stroke="#2563eb" strokeWidth="1.8" />
      <circle cx="182" cy="26" r="6" fill="#2563eb" />
      <circle cx="88" cy="78" r="3.5" fill="none" stroke="#94a3b8" strokeWidth="1.4" strokeDasharray="2.5 2.5" />
      <text x="113" y="56" fontSize="9" fill="#64748b">先修</text>
      <text x="160" y="16" fontSize="9" fill="#2563eb">目标</text>
    </svg>
  )
}

export default function Overview() {
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      {/* Hero：一句话说清产品是什么 + 唯一主 CTA */}
      <section className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="grid gap-6 p-6 sm:p-8 md:grid-cols-[1fr_auto] md:items-center">
          <div>
            <h2 className="max-w-2xl text-2xl font-semibold leading-8 tracking-tight text-slate-900">
              让教学材料变成可查询、可溯源、能引导自学的结构化知识体
            </h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
              上传《计算机网络》的真实教学材料，系统在几分钟内完成解析、知识点结构化与依赖图构建，
              并在答疑时引导学生自己把问题想明白 —— 而不是直接给答案。
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <Link
                to="/materials"
                className="inline-flex h-11 items-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-semibold text-white transition-colors duration-120 hover:bg-brand-700 sm:h-10"
              >
                <Upload className="h-4 w-4" aria-hidden />
                开始上传素材
              </Link>
              <span className="text-xs text-slate-400">先跑通 Stage 1，再逐步点亮 Stage 2 / 3</span>
            </div>
          </div>
          <MapMotif className="hidden h-28 w-48 shrink-0 md:block" />
        </div>
        <div className="h-1 w-full bg-gradient-to-r from-brand-600 via-brand-200 to-transparent" aria-hidden />
      </section>

      {/* 「从这看起」—— 排在 Stage 卡片之前，让第一次打开的人不用猜从哪点 */}
      <section>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 className="text-lg font-semibold leading-7 text-slate-900">从这看起</h3>
          <span className="text-xs text-slate-400">
            四个入口，对应演示里的四个环节 —— 每个点了都直接落到那一步，不需要先自己找
          </span>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {QUICK_TOURS.map((tour) => {
            const Icon = tour.icon
            return (
              <Link
                key={tour.title}
                to={tour.to}
                className="group flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 transition-colors duration-120 hover:border-brand-300 hover:bg-brand-50/40"
              >
                <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                  <Icon className="h-4 w-4" aria-hidden />
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1 text-sm font-semibold text-slate-800">
                    {tour.title}
                    <ArrowRight
                      className="h-3 w-3 text-brand-500 transition-transform duration-120 group-hover:translate-x-0.5"
                      aria-hidden
                    />
                  </span>
                  <span className="mt-1 block text-[13px] leading-5 text-slate-500">{tour.desc}</span>
                  <span className="mt-1.5 block text-xs font-medium text-brand-600">{tour.cta} →</span>
                </span>
              </Link>
            )
          })}
        </div>
      </section>

      {/* 三个 Stage：排成一条「路线」，序号即步骤 */}
      <section>
        <h3 className="text-lg font-semibold leading-7 text-slate-900">三步走通</h3>
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
          {STAGES.map((stage) => {
            const Icon = stage.icon
            return (
              <div key={stage.title} className="xizhi-card relative flex flex-col p-5">
                <div className="flex items-center justify-between">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                    <Icon className="h-5 w-5" aria-hidden />
                  </div>
                  <span className="font-mono text-xs font-medium tracking-widest text-slate-300">{stage.step}</span>
                </div>
                <h4 className="mt-3 text-base font-semibold leading-6 text-slate-800">{stage.title}</h4>
                <p className="mt-1.5 flex-1 text-[13px] leading-5 text-slate-500">{stage.desc}</p>
                <Link
                  to={stage.to}
                  className="mt-3 inline-flex items-center gap-1 text-[13px] font-medium text-brand-600 hover:text-brand-700"
                >
                  {stage.cta}
                  <ArrowRight className="h-3 w-3" aria-hidden />
                </Link>
              </div>
            )
          })}
        </div>
      </section>

      <section className="xizhi-card p-5">
        <h3 className="text-base font-semibold leading-6 text-slate-800">产品原则</h3>
        <ul className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1.5 text-[13px] leading-5 text-slate-500 sm:grid-cols-2">
          <li>· 宁缺毋错：检索不到就明说「材料里没有」，绝不编造</li>
          <li>· 显式不确定性：解析存疑处主动标出，不做完美假象</li>
          <li>· 先结论后细节：所有输出先给结论再给依据</li>
          <li>· 可见的溯源：任何来自材料的断言都能一点回到原文</li>
        </ul>
      </section>
    </div>
  )
}

import { FileText, Network, MessagesSquare, ArrowRight, Upload } from 'lucide-react'
import { Link } from 'react-router-dom'

const STAGES = [
  {
    icon: FileText,
    title: 'Stage 1 · 素材解析',
    desc: 'PDF / Word / PPT / 图片统一转为带页码锚点的 Markdown，输出素材清单与存疑处。',
    to: '/materials',
    cta: '去上传素材',
  },
  {
    icon: Network,
    title: 'Stage 2 · 知识点结构化',
    desc: '章—节—知识点三级结构，五要素齐全，构建知识点依赖 DAG 与学习路径。',
    to: '/graph',
    cta: '查看知识图谱',
  },
  {
    icon: MessagesSquare,
    title: 'Stage 3 · 交互式答疑',
    desc: '苏格拉底式引导：先反问、再提示、答不上两次才直接讲解；每轮给出卡点与下一步。',
    to: '/tutor',
    cta: '进入答疑辅导',
  },
]

export default function Overview() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <section className="xizhi-card p-6">
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">
          让教学材料变成可查询、可溯源、能引导自学的结构化知识体
        </h2>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-500">
          上传《计算机网络》的真实教学材料，系统在几分钟内完成解析、知识点结构化与依赖图构建，
          并在答疑时引导学生自己把问题想明白 —— 而不是直接给答案。
        </p>
        <div className="mt-4 flex items-center gap-3">
          <Link
            to="/materials"
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-medium text-white transition-colors hover:bg-brand-700"
          >
            <Upload className="h-4 w-4" aria-hidden />
            开始上传素材
          </Link>
          <span className="text-xs text-slate-400">先跑通 Stage 1，再逐步点亮 Stage 2 / 3</span>
        </div>
      </section>

      <section className="grid grid-cols-3 gap-4">
        {STAGES.map((stage) => {
          const Icon = stage.icon
          return (
            <div key={stage.title} className="xizhi-card flex flex-col p-5">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                <Icon className="h-5 w-5" aria-hidden />
              </div>
              <h3 className="mt-3 text-sm font-semibold text-slate-800">{stage.title}</h3>
              <p className="mt-1.5 flex-1 text-xs leading-relaxed text-slate-500">{stage.desc}</p>
              <Link
                to={stage.to}
                className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700"
              >
                {stage.cta}
                <ArrowRight className="h-3 w-3" aria-hidden />
              </Link>
            </div>
          )
        })}
      </section>

      <section className="xizhi-card p-5">
        <h3 className="text-sm font-semibold text-slate-800">产品原则</h3>
        <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs text-slate-500">
          <li>· 宁缺毋错：检索不到就明说「材料里没有」，绝不编造</li>
          <li>· 显式不确定性：解析存疑处主动标出，不做完美假象</li>
          <li>· 先结论后细节：所有输出先给结论再给依据</li>
          <li>· 可见的溯源：任何来自材料的断言都能一点回到原文</li>
        </ul>
      </section>
    </div>
  )
}

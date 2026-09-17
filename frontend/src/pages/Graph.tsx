import { Placeholder } from '@/components/layout/Placeholder'

export default function Graph() {
  return (
    <Placeholder
      title="知识图谱"
      milestone="D7（9/22）· 创新点集中攻坚日"
      note="把知识点的前置依赖渲染为有向无环图：节点按难度取色，边区分 hard / soft。页首将展示环数、因成环被剪除的边数、结构-语义冲突边数 —— 把「教学依赖图必须无环」这个工程不变量变成评委可见的信任信号。"
      endpoints={[
        'GET /api/knowledge-graph',
        'GET /api/knowledge-points',
        'GET /api/knowledge-points/{id}',
        'POST /api/extract/knowledge',
      ]}
    />
  )
}

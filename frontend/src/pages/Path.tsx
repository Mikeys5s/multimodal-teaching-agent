import { Placeholder } from '@/components/layout/Placeholder'

export default function PathPage() {
  return (
    <Placeholder
      title="学习路径"
      milestone="D7（9/22）"
      note="指定目标知识点后，沿前置依赖反向遍历并拓扑排序，输出有序学习路径。每一步都会展示来自前置边的 reason（P10 产出）—— 让「为什么这个要排在前面」可解释，而不是黑盒排序的结果。"
      endpoints={['GET /api/learning-path', 'GET /api/knowledge-points/{id}/gap-analysis']}
    />
  )
}

import { createBrowserRouter } from 'react-router-dom'

import App from '@/App'
import Graph from '@/pages/Graph'
import Materials from '@/pages/Materials'
import Overview from '@/pages/Overview'
import PathPage from '@/pages/Path'
import Report from '@/pages/Report'
import Tutor from '@/pages/Tutor'

/**
 * 路由表 —— 与 docs/api-spec.md §8 完全一致。
 * D2 只完整实现 /materials；其余页面按 SPEC §8.2 排期在 D6–D8 落地，当前为骨架占位。
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Overview /> },
      { path: 'materials', element: <Materials /> },
      { path: 'graph', element: <Graph /> },
      { path: 'path', element: <PathPage /> },
      { path: 'tutor', element: <Tutor /> },
      { path: 'report', element: <Report /> },
      { path: '*', element: <Overview /> },
    ],
  },
])

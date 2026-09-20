import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'

import { router } from '@/router'

import '@/index.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error('#root 节点不存在，index.html 可能被破坏')
}

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)

/** @type {import('tailwindcss').Config} */
// 设计 token 集中在此：难度色阶、状态色、品牌色
// 依据：SPEC §5.2 F2.7（节点颜色映射难度）、api-spec §3.2（status 枚举）
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },
        // 难度 1–5（易 → 难）；前端知识图谱节点按 difficulty 取色
        difficulty: {
          1: '#10b981',
          2: '#84cc16',
          3: '#f59e0b',
          4: '#f97316',
          5: '#ef4444',
        },
        // 素材/任务状态；与 api-spec 的 status 枚举一一对应
        status: {
          pending: '#94a3b8',
          parsing: '#3b82f6',
          done: '#10b981',
          partial: '#f59e0b',
          failed: '#ef4444',
        },
      },
      fontFamily: {
        sans: [
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'PingFang SC',
          'Hiragino Sans GB',
          'Microsoft YaHei',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      borderRadius: {
        xl: '0.75rem',
        '2xl': '1rem',
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)',
      },
    },
  },
  plugins: [],
}

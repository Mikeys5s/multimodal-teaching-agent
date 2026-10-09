import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const VARIANT_CLASS: Record<Variant, string> = {
  primary:
    'bg-brand-600 text-white hover:bg-brand-700 active:bg-brand-800 disabled:bg-brand-300 disabled:hover:bg-brand-300',
  secondary:
    'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-900 active:bg-slate-100 disabled:text-slate-400 disabled:hover:bg-white',
  ghost:
    'text-slate-600 hover:bg-slate-100 hover:text-slate-900 active:bg-slate-200 disabled:text-slate-400 disabled:hover:bg-transparent',
  danger:
    'border border-danger-line bg-white text-danger hover:bg-danger-soft active:bg-danger-line/50 disabled:text-danger/40 disabled:hover:bg-white',
}

// 触控目标：手机端主要按钮至少 44px 高（硬约束），桌面端 40/32px
const SIZE_CLASS: Record<Size, string> = {
  sm: 'h-9 px-3 text-xs sm:h-8',
  md: 'h-11 px-4 text-sm sm:h-10',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  className = '',
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={[
        'inline-flex items-center justify-center gap-2 rounded-lg font-medium',
        'transition-colors duration-120',
        'disabled:cursor-not-allowed',
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        className,
      ].join(' ')}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  )
}

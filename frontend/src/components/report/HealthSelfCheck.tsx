import { AlertTriangle, CheckCircle2, Database, RefreshCw, ServerCog, ShieldCheck } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { ErrorState, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'

/** 自检一行：label + 值 + 通过/异常标记 */
function CheckRow({
  label,
  value,
  ok,
  hint,
}: {
  label: string
  value: string
  ok: boolean | null
  hint?: string
}) {
  const color = ok === null ? '#64748b' : ok ? '#10b981' : '#ef4444'
  return (
    <div className="flex items-start justify-between gap-3 border-b border-slate-100 py-2 last:border-b-0">
      <div className="min-w-0">
        <div className="text-xs font-medium text-slate-600">{label}</div>
        {hint && <div className="mt-0.5 text-[11px] text-slate-400">{hint}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <span className="font-mono text-xs" style={{ color }}>
          {value}
        </span>
        {ok !== null &&
          (ok ? (
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" aria-hidden />
          ) : (
            <AlertTriangle className="h-3.5 w-3.5 text-red-500" aria-hidden />
          ))}
      </div>
    </div>
  )
}

/**
 * 演示前自检区（api-spec §2：`GET /api/health` + `GET /api/health/pragma`）。
 * 关键点：`pragmas.foreign_keys` **必须为 "1"** —— 这是「外键约束到底生效了没」的
 * 可验证答案，而不是靠读代码猜。
 */
export function HealthSelfCheck() {
  const healthReq = useRequest(() => api.health(), [])
  const pragmaReq = useRequest(() => api.healthPragma(), [])

  const health = healthReq.data
  const pragma = pragmaReq.data
  const pragmas = pragma ? Object.entries(pragma.pragmas ?? {}) : []
  const foreignKeys = pragmas.find(([key]) => key === 'foreign_keys')?.[1]
  const foreignKeysOk = foreignKeys === '1'

  const reloadAll = () => {
    void healthReq.reload()
    void pragmaReq.reload()
  }

  const loading = (healthReq.loading && !health) || (pragmaReq.loading && !pragma)
  const error = healthReq.error ?? pragmaReq.error

  return (
    <section className="xizhi-card">
      <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div className="flex items-baseline gap-3">
          <h2 className="text-sm font-semibold text-slate-800">演示前自检</h2>
          <span className="text-xs text-slate-400">后端健康检查 + SQLite 实际 pragma 读回</span>
        </div>
        <Button
          variant="secondary"
          size="sm"
          loading={healthReq.loading || pragmaReq.loading}
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={reloadAll}
        >
          重新自检
        </Button>
      </header>

      {loading ? (
        <LoadingState label="正在自检后端…" />
      ) : error && !health && !pragma ? (
        <div className="p-4">
          <ErrorState message={error} onRetry={reloadAll} />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 p-4">
          <div className="rounded-xl border border-slate-200 p-3.5">
            <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-slate-600">
              <ServerCog className="h-3.5 w-3.5" aria-hidden />
              GET /api/health
            </div>
            {health ? (
              <div>
                <CheckRow label="status" value={health.status} ok={health.status === 'ok' || health.status === 'healthy'} />
                <CheckRow label="db" value={health.db} ok={health.db === 'ok' || health.db === 'connected'} />
                <CheckRow label="llm" value={health.llm} ok={health.llm !== 'unavailable' && health.llm !== 'down'} />
                <CheckRow label="version" value={health.version} ok={null} />
              </div>
            ) : (
              <p className="py-2 text-xs text-red-600">{healthReq.error ?? '健康检查暂无数据。'}</p>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 p-3.5">
            <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-slate-600">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
              GET /api/health/pragma{foreignKeys !== undefined && (foreignKeysOk ? ' · 外键生效' : ' · 外键异常')}
            </div>
            {pragma ? (
              <>
                <div
                  className={[
                    'mb-2 rounded-lg border px-2.5 py-2 text-[11px] font-medium',
                    foreignKeysOk
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                      : 'border-red-200 bg-red-50 text-red-700',
                  ].join(' ')}
                >
                  {foreignKeysOk
                    ? 'foreign_keys = "1"，外键约束已生效（DELETE 级联才会真的生效）。'
                    : `外键约束未生效：foreign_keys 实际为 ${
                        foreignKeys === undefined ? '未返回' : `"${foreignKeys}"`
                      }，必须为 "1"。`}
                </div>

                <div className="max-h-44 overflow-y-auto pr-1">
                  {pragmas.length === 0 ? (
                    <p className="py-2 text-xs text-slate-400">后端未返回任何 pragma。</p>
                  ) : (
                    pragmas.map(([key, value]) => (
                      <CheckRow
                        key={key}
                        label={key}
                        value={value}
                        ok={key === 'foreign_keys' ? value === '1' : null}
                      />
                    ))
                  )}
                </div>

                <div className="mt-2 flex items-center gap-1.5 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
                  <Database className="h-3.5 w-3.5 text-slate-400" aria-hidden />
                  db_file：<span className="font-mono text-slate-700">{pragma.db_file}</span>
                </div>
              </>
            ) : (
              <p className="py-2 text-xs text-red-600">{pragmaReq.error ?? 'pragma 读回失败。'}</p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

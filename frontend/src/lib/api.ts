import { REQUEST_ID_HEADER, type ApiEnvelope, type ApiErrorCode, type NonJsonContentType } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

export type QueryValue = string | number | boolean | undefined | null
/** 可重复查询参数（v1.3 §4.4：gap-analysis 的 `student_evidence`）—— 展开成同名多值 */
export type QueryArrayValue = readonly string[]
export type QueryMapValue = QueryValue | QueryArrayValue

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  query?: Record<string, QueryMapValue>
  body?: unknown
  formData?: FormData
  signal?: AbortSignal
  /** 覆盖 `Accept` 头；非 JSON 接口需要显式声明（如 text/markdown） */
  accept?: string
}

/**
 * 统一错误对象。
 * message 直接来自后端（后端保证是可直接展示的中文，api-spec §1.1），
 * 前端任何地方都应直接把 message 展示给用户，不要自行拼装英文。
 */
export class ApiError extends Error {
  readonly code: ApiErrorCode
  readonly detail?: unknown
  readonly requestId?: string
  readonly httpStatus?: number

  constructor(
    code: ApiErrorCode,
    message: string,
    opts: { detail?: unknown; requestId?: string; httpStatus?: number } = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.detail = opts.detail
    this.requestId = opts.requestId
    this.httpStatus = opts.httpStatus
  }
}

function buildQuery(query?: Record<string, QueryMapValue>): string {
  if (!query) return ''
  const sp = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    // 数组 → 同名多值（`?student_evidence=a&student_evidence=b`）
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item === undefined || item === null || item === '') continue
        sp.append(key, String(item))
      }
      continue
    }
    sp.set(key, String(value))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

function fullUrl(path: string, query?: Record<string, QueryMapValue>): string {
  return `${API_BASE}${path}${buildQuery(query)}`
}

async function doFetch(url: string, options: RequestOptions): Promise<Response> {
  const { method = 'GET', body, formData, signal, accept } = options
  const headers: Record<string, string> = { Accept: accept ?? 'application/json' }
  let payload: BodyInit | undefined

  if (formData) {
    // 不要手动设置 Content-Type，浏览器会自动带上 multipart boundary
    payload = formData
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  try {
    return await fetch(url, { method, headers, body: payload, signal })
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') throw err
    throw new ApiError('NETWORK_ERROR', '无法连接后端服务，请确认后端已启动后重试。')
  }
}

/** 请求并解开 {ok,data,request_id} 包封（api-spec §1.1） */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const res = await doFetch(fullUrl(path, options.query), options)
  const text = await res.text()

  let envelope: ApiEnvelope<T> | null = null
  if (text) {
    try {
      envelope = JSON.parse(text) as ApiEnvelope<T>
    } catch {
      envelope = null
    }
  }

  if (!envelope) {
    throw new ApiError('BAD_RESPONSE', `服务返回了无法解析的内容（HTTP ${res.status}）。`, {
      httpStatus: res.status,
    })
  }

  if (envelope.ok === false) {
    throw new ApiError(envelope.error.code, envelope.error.message, {
      detail: envelope.error.detail,
      requestId: envelope.request_id,
      httpStatus: res.status,
    })
  }

  return envelope.data
}

/**
 * 请求**非 JSON 响应**（`text/markdown` / `text/csv`，api-spec §1.1 v1.3 例外条款）。
 *
 * 涉及：`GET /api/materials/{id}/markdown`、`GET /api/export/knowledge-points?format=csv`。
 * 这两类接口**塞不进 `{ok,data,request_id}` 包封**，所以约定：
 *   - 成功 → 原始内容，请求标识走 `X-Request-ID` **响应头**；
 *   - 失败 → **仍返回 JSON 包封**（`Content-Type` 切回 `application/json`）。
 *
 * 因此判定顺序是「**先看 `Content-Type`，再决定解析分支**」——这样前端只需要一套
 * 错误处理逻辑，也不用依赖 HTTP 状态码去猜 body 是什么。
 */
export async function requestText(
  path: string,
  options: RequestOptions = {},
  accept: NonJsonContentType = 'text/markdown',
): Promise<string> {
  const res = await doFetch(fullUrl(path, options.query), { ...options, accept })
  const requestId = res.headers.get(REQUEST_ID_HEADER) ?? undefined
  const text = await res.text()
  const contentType = (res.headers.get('Content-Type') ?? '').toLowerCase()

  // ① 成功且不是 JSON → 就是原始内容
  if (res.ok && !contentType.includes('application/json')) return text

  // ② 其余情况（失败，或成功却返回了 JSON）都按包封解析
  try {
    const env = JSON.parse(text) as ApiEnvelope<unknown>
    if (env.ok === false) {
      throw new ApiError(env.error.code, env.error.message, {
        detail: env.error.detail,
        requestId: env.request_id || requestId,
        httpStatus: res.status,
      })
    }
    if (env.ok === true) {
      // 契约漂移：这两类接口成功时不包封。明确报错，不要静默把包封当内容返回
      throw new ApiError('BAD_RESPONSE', '服务返回了 JSON 包封，但该接口约定返回原始内容。', {
        requestId,
        httpStatus: res.status,
      })
    }
  } catch (err) {
    if (err instanceof ApiError) throw err
    /* 不是 JSON，落到下面给通用文案 */
  }

  throw new ApiError('INTERNAL', `请求失败（HTTP ${res.status}）。`, {
    requestId,
    httpStatus: res.status,
  })
}

export { API_BASE }

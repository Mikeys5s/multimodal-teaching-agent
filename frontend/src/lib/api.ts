import type { ApiEnvelope, ApiErrorCode } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

export type QueryValue = string | number | boolean | undefined | null

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  query?: Record<string, QueryValue>
  body?: unknown
  formData?: FormData
  signal?: AbortSignal
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

function buildQuery(query?: Record<string, QueryValue>): string {
  if (!query) return ''
  const sp = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    sp.set(key, String(value))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

function fullUrl(path: string, query?: Record<string, QueryValue>): string {
  return `${API_BASE}${path}${buildQuery(query)}`
}

async function doFetch(url: string, options: RequestOptions): Promise<Response> {
  const { method = 'GET', body, formData, signal } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
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

/** 请求纯文本响应（如 GET /api/materials/{id}/markdown 返回 text/markdown） */
export async function requestText(path: string, options: RequestOptions = {}): Promise<string> {
  const res = await doFetch(fullUrl(path, options.query), options)
  const text = await res.text()

  if (res.ok) return text

  // 失败时后端仍返回 JSON 包封，尝试解出可读中文
  let message = `请求失败（HTTP ${res.status}）。`
  let code: ApiErrorCode = 'INTERNAL'
  try {
    const env = JSON.parse(text) as ApiEnvelope<unknown>
    if (env.ok === false) {
      message = env.error.message
      code = env.error.code
    }
  } catch {
    /* 保留默认文案 */
  }
  throw new ApiError(code, message, { httpStatus: res.status })
}

export { API_BASE }

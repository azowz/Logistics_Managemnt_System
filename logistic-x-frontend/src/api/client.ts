import type { paths } from './generated';

export const BASE_URL = (process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000/v1').replace(/\/+$/, '');
// Demo data is opt-in, prominently labelled, and never enabled in production.
export const USE_MOCK = process.env.EXPO_PUBLIC_USE_MOCK === 'true' &&
  process.env.EXPO_PUBLIC_APP_ENV !== 'production';
export const MOCK_LATENCY = 450;
export function delay<T>(value: T, ms = MOCK_LATENCY): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public requestId?: string,
    public code?: string, public details?: unknown) {
    super(message);
    this.name = 'ApiError';
  }
}

let authToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;
export function setAuthToken(token: string | null) { authToken = token; }
export function onUnauthorized(handler: (() => void) | null) { unauthorizedHandler = handler; }

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0 || error.status >= 500 && error.status !== 501)
      return 'تعذّر الاتصال بالخادم. تحقق من الشبكة ثم أعد المحاولة.';
    if (error.status === 401) return 'انتهت الجلسة أو بيانات الدخول غير صحيحة. سجّل الدخول مجدداً.';
    if (error.status === 403) return 'ليس لديك صلاحية لتنفيذ هذا الإجراء.';
    if (error.status === 501) return 'هذه الخدمة غير مفعّلة في بيئة الخادم الحالية.';
    return error.message;
  }
  return 'تعذّر إتمام الطلب. حاول مرة أخرى.';
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort);
  if (options.signal?.aborted) controller.abort();
  const timer = setTimeout(abort, 12000);
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  if (authToken) headers.set('Authorization', `Bearer ${authToken}`);
  if (!headers.has('X-Request-ID')) headers.set('X-Request-ID', `frontend-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  try {
    const res = await fetch(`${BASE_URL}${path}`, { ...options, headers, signal: controller.signal });
    const requestId = res.headers.get('X-Request-ID') ?? undefined;
    const text = await res.text();
    let body: any;
    try { body = text ? JSON.parse(text) : undefined; } catch { body = undefined; }
    if (!res.ok) {
      if (res.status === 401 && authToken) unauthorizedHandler?.();
      const message = body?.error?.message ??
        (typeof body?.detail === 'string' ? body.detail : res.statusText || `HTTP ${res.status}`);
      throw new ApiError(res.status, message, requestId ?? body?.error?.request_id,
        body?.error?.code, body?.error?.details ?? body?.detail);
    }
    if (res.status === 204 || !text) return undefined as T;
    if (body === undefined) throw new ApiError(res.status, 'استجابة غير صالحة من الخادم.', requestId);
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, 'تعذّر الاتصال بالخادم. تحقق من الشبكة ثم أعد المحاولة.');
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
  }
}

type JsonBody<T> = T extends { content: { 'application/json': infer B } } ? B : never;
type ResponseBody<T> = T extends { responses: infer R }
  ? 200 extends keyof R ? JsonBody<R[200]> : 201 extends keyof R ? JsonBody<R[201]> : void
  : never;
type RequestBody<T> = T extends { requestBody: infer B } ? JsonBody<B> : never;
type HttpMethod = 'get' | 'post' | 'patch' | 'delete';
type MethodFor<P extends keyof paths> = {
  [M in HttpMethod]: paths[P][M] extends undefined ? never : M
}[HttpMethod];

/** Method, request body and response all come from the checked-in OpenAPI. */
export function apiRequest<P extends keyof paths, M extends keyof paths[P] & MethodFor<P>>(
  path: P, method: M,
  options?: { params?: Record<string, string>; body?: RequestBody<paths[P][M]> },
): Promise<ResponseBody<paths[P][M]>> {
  const resolved = path.replace(/\{([^}]+)\}/g, (_, key: string) => encodeURIComponent(options?.params?.[key] ?? ''));
  return request(resolved.replace(/^\/v1/, ''), {
    method: method.toUpperCase(),
    ...(options?.body === undefined ? {} : { body: JSON.stringify(options.body) }),
  });
}

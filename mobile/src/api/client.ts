/**
 * Thin HTTP client wrapper.
 *
 * The app currently runs against the mock layer (see ./driverApi), but every
 * mock function returns the same shape this client would, so switching to the
 * live FastAPI backend is a matter of flipping `USE_MOCK` to false and pointing
 * BASE_URL at the server.
 */
export const BASE_URL =
  process.env.EXPO_PUBLIC_API_URL ?? 'https://api.mesaar.sa/v1';

export const USE_MOCK = process.env.EXPO_PUBLIC_USE_MOCK !== 'false';

/** Simulated network latency for the mock layer (ms). */
export const MOCK_LATENCY = 450;

export function delay<T>(value: T, ms: number = MOCK_LATENCY): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Auth token kept in memory; swap for SecureStore in production. */
let authToken: string | null = null;
export function setAuthToken(token: string | null) {
  authToken = token;
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...(options.headers ?? {}),
    },
  });

  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = body.detail ?? message;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message);
  }

  return (await res.json()) as T;
}

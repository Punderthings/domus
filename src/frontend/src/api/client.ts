// Small fetch wrapper for /api/v1: JSON in and out, cookie session, CSRF header.

export const API_BASE = '/api/v1';
export const CSRF_COOKIE = 'domus_csrf';
export const CSRF_HEADER = 'X-CSRF-Token';

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/** An HTTP error from the API, with FastAPI's `detail` when present. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : `Request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/** Read one cookie value from a `document.cookie` style string. */
export function readCookie(name: string, cookies: string = document.cookie): string | null {
  for (const part of cookies.split(';')) {
    const [key, ...rest] = part.trim().split('=');
    if (key === name) return decodeURIComponent(rest.join('='));
  }
  return null;
}

export type QueryParams = Record<string, string | number | boolean | null | undefined>;

/** Build an API URL, dropping empty parameters. */
export function apiUrl(path: string, params?: QueryParams): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  }
  const query = search.toString();
  return `${API_BASE}${path}${query ? `?${query}` : ''}`;
}

export interface RequestOptions {
  method?: string;
  params?: QueryParams;
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase();
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (UNSAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE);
    if (token) headers[CSRF_HEADER] = token;
  }

  const response = await fetch(apiUrl(path, options.params), {
    method,
    headers,
    credentials: 'same-origin',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  if (response.status === 204) return undefined as T;
  const isJson = response.headers.get('Content-Type')?.includes('application/json') ?? false;
  const payload: unknown = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    const detail =
      isJson && payload && typeof payload === 'object' && 'detail' in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    throw new ApiError(response.status, detail);
  }
  return payload as T;
}

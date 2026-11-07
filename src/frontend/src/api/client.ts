// Typed client for /api/v1, generated from openapi.json (openapi-fetch), with the
// cookie session, the CSRF header, and errors thrown as ApiError.

import createClient, { type Middleware } from 'openapi-fetch';
import type { paths } from './schema';

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

const csrf: Middleware = {
  onRequest({ request }) {
    if (UNSAFE_METHODS.has(request.method)) {
      const token = readCookie(CSRF_COOKIE);
      if (token) request.headers.set(CSRF_HEADER, token);
    }
    return request;
  },
};

export const api = createClient<paths>({
  // Same origin as the page: the backend serves both the app and the API.
  baseUrl: globalThis.location?.origin ?? '',
  credentials: 'same-origin',
  headers: { Accept: 'application/json' },
  // Look fetch up on each call, so tests can replace it.
  fetch: (request) => globalThis.fetch(request),
});
api.use(csrf);

function errorDetail(error: unknown): unknown {
  return error && typeof error === 'object' && 'detail' in error
    ? (error as { detail: unknown }).detail
    : error;
}

/** Return the data of an openapi-fetch result, or throw ApiError for an HTTP error. */
export async function unwrap<T>(
  result: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await result;
  if (!response.ok) throw new ApiError(response.status, errorDetail(error));
  return data as T;
}

/**
 * Upload one file as the raw request body (the API takes no multipart forms).
 * `query` becomes the query string, for example `{ kind: 'floor_plan' }`.
 */
export async function uploadFile<T>(
  path: string,
  file: Blob,
  query: Record<string, string | undefined> = {},
): Promise<T> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value) params.set(key, value);
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': file.type || 'application/octet-stream',
  };
  const token = readCookie(CSRF_COOKIE);
  if (token) headers[CSRF_HEADER] = token;
  const base = globalThis.location?.origin ?? '';
  const response = await globalThis.fetch(`${base}${path}?${params.toString()}`, {
    method: 'POST',
    credentials: 'same-origin',
    headers,
    body: file,
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorDetail(body));
  return body as T;
}

// A tiny in-memory fake of the Domus API for component tests. No network is used.
import { vi } from 'vitest';

export interface RecordedCall {
  method: string;
  path: string;
  search: URLSearchParams;
  headers: Record<string, string>;
  body: unknown;
}

type Handler = (call: RecordedCall) => { status?: number; body?: unknown } | undefined;

export function json(status: number, body?: unknown): Response {
  if (status === 204) return new Response(null, { status });
  return new Response(JSON.stringify(body ?? null), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** Route "METHOD /path" to a handler. Unknown routes return 404. */
export function fakeApi(routes: Record<string, Handler>) {
  const calls: RecordedCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://domus.test');
    const call: RecordedCall = {
      method: (init?.method ?? 'GET').toUpperCase(),
      path: url.pathname.replace(/^\/api\/v1/, ''),
      search: url.searchParams,
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    };
    calls.push(call);
    const handler = routes[`${call.method} ${call.path}`];
    const result = handler?.(call);
    if (!result) return json(404, { detail: 'Not Found' });
    return json(result.status ?? 200, result.body);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { calls, fetchMock };
}

export const page = <T>(items: T[]) => ({ items, next_cursor: null });

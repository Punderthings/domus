import { describe, expect, it } from 'vitest';
import { fakeApi } from '../test/server';
import { ApiError, api, readCookie, unwrap } from './client';

describe('readCookie', () => {
  it('finds a cookie among several and decodes it', () => {
    expect(readCookie('domus_csrf', 'a=1; domus_csrf=abc%3D%3D; b=2')).toBe('abc==');
  });
  it('returns null when missing', () => {
    expect(readCookie('domus_csrf', 'a=1')).toBeNull();
    expect(readCookie('domus_csrf', '')).toBeNull();
  });
});

describe('api client', () => {
  it('sends the CSRF header on unsafe methods only', async () => {
    document.cookie = 'domus_csrf=token123';
    const { calls } = fakeApi({
      'GET /auth/setup': () => ({ body: { needs_setup: false } }),
      'POST /auth/login': () => ({ body: {} }),
    });
    await unwrap(api.GET('/api/v1/auth/setup'));
    await unwrap(api.POST('/api/v1/auth/login', { body: { email: 'a@b.c', password: 'pw' } }));
    expect(calls[0]?.headers['x-csrf-token']).toBeUndefined();
    expect(calls[1]?.headers['x-csrf-token']).toBe('token123');
    expect(calls[1]?.headers['content-type']).toBe('application/json');
    expect(calls[1]?.body).toEqual({ email: 'a@b.c', password: 'pw' });
    document.cookie = 'domus_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  });

  it('serializes query parameters and leaves out undefined ones', async () => {
    const { calls } = fakeApi({
      'GET /assets': () => ({ body: { items: [], next_cursor: null } }),
    });
    await unwrap(
      api.GET('/api/v1/assets', {
        params: { query: { property_id: 'p', q: 'a&b', area_id: undefined } },
      }),
    );
    expect(calls[0]?.search.get('property_id')).toBe('p');
    expect(calls[0]?.search.get('q')).toBe('a&b');
    expect(calls[0]?.search.has('area_id')).toBe(false);
  });

  it('returns undefined for 204 responses', async () => {
    fakeApi({ 'POST /auth/logout': () => ({ status: 204 }) });
    await expect(unwrap(api.POST('/api/v1/auth/logout'))).resolves.toBeUndefined();
  });

  it('throws ApiError with the FastAPI detail', async () => {
    fakeApi({
      'GET /assets/missing': () => ({ status: 404, body: { detail: 'Asset not found' } }),
    });
    const error = await unwrap(
      api.GET('/api/v1/assets/{asset_id}', { params: { path: { asset_id: 'missing' } } }),
    ).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).message).toBe('Asset not found');
  });

  it('keeps structured validation details', async () => {
    const detail = [{ loc: ['body', 'email'], msg: 'invalid' }];
    fakeApi({ 'POST /auth/login': () => ({ status: 422, body: { detail } }) });
    const error = (await unwrap(
      api.POST('/api/v1/auth/login', { body: { email: '', password: '' } }),
    ).catch((e: unknown) => e)) as ApiError;
    expect(error.detail).toEqual(detail);
    expect(error.message).toBe('Request failed with status 422');
  });
});

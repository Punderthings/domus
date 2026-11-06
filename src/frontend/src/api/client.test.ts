import { describe, expect, it } from 'vitest';
import { fakeApi } from '../test/server';
import { ApiError, apiRequest, apiUrl, readCookie } from './client';

describe('readCookie', () => {
  it('finds a cookie among several and decodes it', () => {
    expect(readCookie('domus_csrf', 'a=1; domus_csrf=abc%3D%3D; b=2')).toBe('abc==');
  });
  it('returns null when missing', () => {
    expect(readCookie('domus_csrf', 'a=1')).toBeNull();
    expect(readCookie('domus_csrf', '')).toBeNull();
  });
});

describe('apiUrl', () => {
  it('prefixes the API base and drops empty parameters', () => {
    expect(
      apiUrl('/assets', { property_id: 'p', q: '', area_id: undefined, limit: 50, active: true }),
    ).toBe('/api/v1/assets?property_id=p&limit=50&active=true');
  });
  it('encodes parameter values', () => {
    expect(apiUrl('/assets', { q: 'a&b c' })).toBe('/api/v1/assets?q=a%26b+c');
  });
});

describe('apiRequest', () => {
  it('sends the CSRF header on unsafe methods only', async () => {
    document.cookie = 'domus_csrf=token123';
    const { calls } = fakeApi({
      'GET /x': () => ({ body: {} }),
      'POST /x': () => ({ status: 204 }),
    });
    await apiRequest('/x');
    await apiRequest('/x', { method: 'POST', body: { a: 1 } });
    expect(calls[0]?.headers['X-CSRF-Token']).toBeUndefined();
    expect(calls[1]?.headers['X-CSRF-Token']).toBe('token123');
    expect(calls[1]?.headers['Content-Type']).toBe('application/json');
    expect(calls[1]?.body).toEqual({ a: 1 });
    document.cookie = 'domus_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
  });

  it('returns undefined for 204 responses', async () => {
    fakeApi({ 'POST /auth/logout': () => ({ status: 204 }) });
    await expect(apiRequest('/auth/logout', { method: 'POST' })).resolves.toBeUndefined();
  });

  it('throws ApiError with the FastAPI detail', async () => {
    fakeApi({
      'GET /assets/missing': () => ({ status: 404, body: { detail: 'Asset not found' } }),
    });
    const error = await apiRequest('/assets/missing').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    expect((error as ApiError).message).toBe('Asset not found');
  });

  it('keeps structured validation details', async () => {
    const detail = [{ loc: ['body', 'email'], msg: 'invalid' }];
    fakeApi({ 'POST /auth/login': () => ({ status: 422, body: { detail } }) });
    const error = (await apiRequest('/auth/login', { method: 'POST', body: {} }).catch(
      (e: unknown) => e,
    )) as ApiError;
    expect(error.detail).toEqual(detail);
    expect(error.message).toBe('Request failed with status 422');
  });
});

import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { CurrentUser, Property } from './api/types';
import { PROPERTY_STORAGE_KEY } from './auth/activeProperty';
import { areas, buildings, floors, property, user } from './test/fixtures';
import { renderApp } from './test/render';
import { fakeApi, page, type RecordedCall } from './test/server';

const MY_HOME_ID = '01a1b31d-0000-7000-8000-000000000001';
const SAMPLE_ID = property.id;

const myHome: Property = { ...property, id: MY_HOME_ID, name: 'Maple Street', address: null };

function member(role: 'admin' | 'resident', ids: string[]): CurrentUser {
  return {
    ...user(role),
    memberships: ids.map((id, i) => ({ id: `m${i}`, property_id: id, role, expires_at: null })),
  };
}

/** A user whose only property is a new, empty one, as setup leaves it. */
function emptyInstall(role: 'admin' | 'resident' = 'admin', loaded = false) {
  let me = member(role, [MY_HOME_ID]);
  const api = fakeApi({
    'GET /auth/setup': () => ({ body: { needs_setup: false } }),
    'GET /auth/me': () => ({ body: me }),
    'GET /properties': () => ({
      body: page(me.memberships.length > 1 ? [myHome, property] : [myHome]),
    }),
    [`GET /properties/${MY_HOME_ID}`]: () => ({ body: myHome }),
    [`GET /properties/${SAMPLE_ID}`]: () => ({ body: property }),
    'GET /buildings': (c: RecordedCall) => ({
      body: page(c.search.get('property_id') === SAMPLE_ID ? buildings : []),
    }),
    'GET /floors': () => ({ body: page(floors) }),
    'GET /areas': (c: RecordedCall) => ({
      body: page(c.search.get('property_id') === SAMPLE_ID ? areas : []),
    }),
    'GET /maintenance/tasks': () => ({ body: page([]) }),
    'GET /sample-data': () =>
      role === 'admin'
        ? { body: { available: true, loaded, property_id: SAMPLE_ID } }
        : { status: 403, body: { detail: 'Requires the admin role' } },
    'POST /sample-data': () => {
      me = member(role, [MY_HOME_ID, SAMPLE_ID]);
      return { status: 201, body: { available: true, loaded: true, property_id: SAMPLE_ID } };
    },
  });
  return api;
}

describe('sample data', () => {
  it('lets an Admin of an empty property load the sample home and switches to it', async () => {
    const { calls } = emptyInstall();
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Maple Street' })).toBeInTheDocument();
    await userEvent.click(await screen.findByRole('button', { name: 'Load sample data' }));

    expect(
      await screen.findByRole('heading', { name: 'Sample Home', level: 2 }),
    ).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: /Kitchen/ })).toBeInTheDocument();
    expect(calls.filter((c) => c.method === 'POST' && c.path === '/sample-data')).toHaveLength(1);
    expect(window.localStorage.getItem(PROPERTY_STORAGE_KEY)).toBe(SAMPLE_ID);
    expect(screen.queryByRole('button', { name: 'Load sample data' })).not.toBeInTheDocument();
  });

  it('does not offer it once the sample home is loaded', async () => {
    emptyInstall('admin', true);
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Maple Street' })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Try Domus with sample data')).toBeNull());
  });

  it('does not offer it to non-Admins or ask the API', async () => {
    const { calls } = emptyInstall('resident');
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Maple Street' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Load sample data' })).toBeNull();
    expect(calls.some((c) => c.path === '/sample-data')).toBe(false);
  });

  it('does not offer it on a property that already has rooms', async () => {
    const { calls } = fakeApi({
      'GET /auth/setup': () => ({ body: { needs_setup: false } }),
      'GET /auth/me': () => ({ body: user('admin') }),
      'GET /properties': () => ({ body: page([property]) }),
      [`GET /properties/${SAMPLE_ID}`]: () => ({ body: property }),
      'GET /buildings': () => ({ body: page(buildings) }),
      'GET /floors': () => ({ body: page(floors) }),
      'GET /areas': () => ({ body: page(areas) }),
      'GET /maintenance/tasks': () => ({ body: page([]) }),
    });
    renderApp('/');
    expect(await screen.findByRole('link', { name: /Kitchen/ })).toBeInTheDocument();
    expect(calls.some((c) => c.path === '/sample-data')).toBe(false);
  });

  it('lists properties in the account menu only for members of several', async () => {
    window.localStorage.setItem(PROPERTY_STORAGE_KEY, SAMPLE_ID);
    fakeApi({
      'GET /auth/setup': () => ({ body: { needs_setup: false } }),
      'GET /auth/me': () => ({ body: member('admin', [MY_HOME_ID, SAMPLE_ID]) }),
      'GET /properties': () => ({ body: page([myHome, property]) }),
      [`GET /properties/${MY_HOME_ID}`]: () => ({ body: myHome }),
      [`GET /properties/${SAMPLE_ID}`]: () => ({ body: property }),
      'GET /buildings': (c: RecordedCall) => ({
        body: page(c.search.get('property_id') === SAMPLE_ID ? buildings : []),
      }),
      'GET /floors': () => ({ body: page(floors) }),
      'GET /areas': (c: RecordedCall) => ({
        body: page(c.search.get('property_id') === SAMPLE_ID ? areas : []),
      }),
      'GET /maintenance/tasks': () => ({ body: page([]) }),
      'GET /sample-data': () => ({
        body: { available: true, loaded: true, property_id: SAMPLE_ID },
      }),
    });
    renderApp('/');
    expect(
      await screen.findByRole('heading', { name: 'Sample Home', level: 2 }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Account' }));
    // Mantine's menu transition can hide the dropdown again in jsdom, so look
    // the items up including hidden ones and click with fireEvent.
    const current = await screen.findByRole('menuitem', { name: 'Sample Home', hidden: true });
    const other = screen.getByRole('menuitem', { name: 'Maple Street', hidden: true });
    expect(current).toHaveAttribute('aria-current', 'true');
    expect(other).not.toHaveAttribute('aria-current');
    fireEvent.click(other);
    expect(
      await screen.findByRole('heading', { name: 'Maple Street', level: 2 }),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem(PROPERTY_STORAGE_KEY)).toBe(MY_HOME_ID);
  });
});

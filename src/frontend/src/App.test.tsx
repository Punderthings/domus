import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { AssetDetail } from './api/types';
import {
  FRIDGE_ID,
  KITCHEN_ID,
  areas,
  buildings,
  floors,
  fridge,
  guestView,
  property,
  task,
  user,
} from './test/fixtures';
import { renderApp } from './test/render';
import { fakeApi, page, type RecordedCall } from './test/server';

/** A signed-in API serving the sample home. */
function signedIn(role: Parameters<typeof user>[0] = 'admin', device: AssetDetail = fridge) {
  return fakeApi({
    'GET /auth/setup': () => ({ body: { needs_setup: false } }),
    'GET /auth/me': () => ({ body: user(role) }),
    'GET /properties/01a1a901-5800-7001-8000-000000000001': () => ({ body: property }),
    'GET /buildings': () => ({ body: page(buildings) }),
    'GET /floors': () => ({ body: page(floors) }),
    'GET /areas': () => ({ body: page(areas) }),
    'GET /assets': (call: RecordedCall) => ({
      body: page(call.search.get('q') === 'nothing' ? [] : [device]),
    }),
    [`GET /assets/${FRIDGE_ID}`]: () => ({ body: device }),
    'GET /maintenance/tasks': () => ({
      body: page([
        task({ id: 'smoke', title: 'Test smoke detector', next_due: '2026-11-01', asset_id: null }),
      ]),
    }),
    'POST /auth/logout': () => ({ status: 204 }),
  });
}

describe('signing in', () => {
  it('sends a fresh install to the setup wizard', async () => {
    fakeApi({
      'GET /auth/setup': () => ({ body: { needs_setup: true } }),
      'GET /auth/me': () => ({ status: 401, body: { detail: 'Not authenticated' } }),
    });
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Welcome to Domus' })).toBeInTheDocument();
  });

  it('validates the setup form before sending it', async () => {
    const { calls } = fakeApi({
      'GET /auth/setup': () => ({ body: { needs_setup: true } }),
      'GET /auth/me': () => ({ status: 401, body: { detail: 'Not authenticated' } }),
    });
    renderApp('/setup');
    await userEvent.type(await screen.findByLabelText(/Property name/), 'Our house');
    await userEvent.type(screen.getByLabelText(/Your name/), 'Pat');
    await userEvent.type(screen.getByLabelText(/Email/), 'pat@example.com');
    await userEvent.type(screen.getByLabelText(/^Password/), 'short');
    await userEvent.type(screen.getByLabelText(/Confirm password/), 'other');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByText('Use at least 12 characters')).toBeInTheDocument();
    expect(screen.getByText('Passwords do not match')).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('redirects a signed-out user to the login page', async () => {
    fakeApi({
      'GET /auth/setup': () => ({ body: { needs_setup: false } }),
      'GET /auth/me': () => ({ status: 401, body: { detail: 'Not authenticated' } }),
    });
    const { history } = renderApp('/devices');
    expect(await screen.findByRole('heading', { name: 'Sign in to Domus' })).toBeInTheDocument();
    expect(history.location.pathname).toBe('/login');
  });

  it('shows a clear message for a wrong password', async () => {
    fakeApi({
      'GET /auth/setup': () => ({ body: { needs_setup: false } }),
      'GET /auth/me': () => ({ status: 401, body: { detail: 'Not authenticated' } }),
      'POST /auth/login': () => ({ status: 401, body: { detail: 'Invalid credentials' } }),
    });
    renderApp('/login');
    await userEvent.type(await screen.findByLabelText(/Email/), 'pat@example.com');
    await userEvent.type(screen.getByLabelText(/Password/), 'wrong password');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'That email and password did not match.',
    );
  });

  it('signs in and lands on the overview', async () => {
    let signedInYet = false;
    const { calls } = fakeApi({
      'GET /auth/setup': () => ({ body: { needs_setup: false } }),
      'GET /auth/me': () =>
        signedInYet ? { body: user() } : { status: 401, body: { detail: 'Not authenticated' } },
      'POST /auth/login': () => {
        signedInYet = true;
        return { status: 204 };
      },
      'GET /properties/01a1a901-5800-7001-8000-000000000001': () => ({ body: property }),
      'GET /buildings': () => ({ body: page(buildings) }),
      'GET /floors': () => ({ body: page(floors) }),
      'GET /areas': () => ({ body: page(areas) }),
      'GET /maintenance/tasks': () => ({ body: page([]) }),
    });
    const { history } = renderApp('/login');
    await userEvent.type(await screen.findByLabelText(/Email/), 'pat@example.com');
    await userEvent.type(screen.getByLabelText(/Password/), 'correct horse battery');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(
      await screen.findByRole('heading', { name: 'Sample Home', level: 2 }),
    ).toBeInTheDocument();
    expect(history.location.pathname).toBe('/');
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      email: 'pat@example.com',
      password: 'correct horse battery',
    });
  });

  it('signs out from the account menu', async () => {
    const { calls } = signedIn();
    const { history } = renderApp('/');
    await userEvent.click(await screen.findByRole('button', { name: 'Account' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Sign out' }));
    await waitFor(() => expect(history.location.pathname).toBe('/login'));
    expect(calls.some((c) => c.method === 'POST' && c.path === '/auth/logout')).toBe(true);
  });
});

describe('overview', () => {
  it('groups areas by building and floor, with outdoor areas separate', async () => {
    signedIn();
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'House' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Main Floor' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Basement' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Outdoor' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Kitchen/ })).toHaveAttribute(
      'href',
      `/areas/${KITCHEN_ID}`,
    );
    expect(screen.getByRole('link', { name: /Utility Room/ })).toHaveTextContent('Critical');
  });

  it('lists maintenance that is overdue or due soon', async () => {
    const { calls } = signedIn();
    renderApp('/');
    expect(await screen.findByText('Test smoke detector')).toBeInTheDocument();
    expect(screen.getByText(/Overdue since/)).toBeInTheDocument();
    const query = calls.find((c) => c.path === '/maintenance/tasks')?.search;
    expect(query?.get('due_before')).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(query?.get('active')).toBe('true');
  });
});

describe('devices', () => {
  it('shows the devices in an area', async () => {
    const { calls } = signedIn();
    renderApp(`/areas/${KITCHEN_ID}`);
    expect(await screen.findByRole('heading', { name: 'Kitchen', level: 2 })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Refrigerator' })).toBeInTheDocument();
    expect(calls.find((c) => c.path === '/assets')?.search.get('area_id')).toBe(KITCHEN_ID);
  });

  it('searches devices and keeps the search in the URL', async () => {
    const { calls } = signedIn();
    const { history } = renderApp('/devices');
    await screen.findByRole('link', { name: 'Refrigerator' });
    await userEvent.type(screen.getByLabelText('Search'), 'nothing');
    expect(await screen.findByText('No devices here yet.')).toBeInTheDocument();
    expect(history.location.search).toContain('q=nothing');
    expect(calls.some((c) => c.path === '/assets' && c.search.get('q') === 'nothing')).toBe(true);
  });

  it('shows full device details to an admin', async () => {
    signedIn('admin');
    renderApp(`/devices/${FRIDGE_ID}`);
    expect(
      await screen.findByRole('heading', { name: 'Refrigerator', level: 2 }),
    ).toBeInTheDocument();
    expect(screen.getByText('ExampleCo Appliances')).toBeInTheDocument();
    expect(screen.getByText('$1,899.00')).toBeInTheDocument();
    expect(screen.getByText('FR24-0001')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open manual' })).toHaveAttribute(
      'href',
      'https://example.com/manuals/fr-2400.pdf',
    );
    const maintenance = screen.getByRole('heading', { name: 'Maintenance' }).closest('div');
    expect(
      await within(maintenance as HTMLElement).findByText('Test smoke detector'),
    ).toBeInTheDocument();
  });

  it('shows a guest only what the API returns, with no cost or serial', async () => {
    signedIn('guest', guestView(fridge));
    renderApp(`/devices/${FRIDGE_ID}`);
    expect(
      await screen.findByRole('heading', { name: 'Refrigerator', level: 2 }),
    ).toBeInTheDocument();
    expect(screen.queryByText('Purchase price')).not.toBeInTheDocument();
    expect(screen.queryByText('Warranty until')).not.toBeInTheDocument();
    expect(screen.queryByText('Identifiers')).not.toBeInTheDocument();
  });

  it('does not render unsafe manual links', async () => {
    const bad = {
      ...fridge,
      product: {
        ...(fridge.product ?? {
          id: 'p',
          created_at: '',
          updated_at: '',
          manufacturer: null,
          model: null,
        }),
        manual_url: 'javascript:alert(1)',
      },
    };
    signedIn('admin', bad);
    renderApp(`/devices/${FRIDGE_ID}`);
    await screen.findByRole('heading', { name: 'Refrigerator', level: 2 });
    expect(screen.queryByRole('link', { name: 'Open manual' })).not.toBeInTheDocument();
  });

  it('explains a missing device', async () => {
    signedIn();
    renderApp('/devices/does-not-exist');
    expect(await screen.findByRole('alert')).toHaveTextContent('This was not found');
  });
});

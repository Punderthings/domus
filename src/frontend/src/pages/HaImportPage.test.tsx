import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { HaDevicePlan, HaImportResult, HaPreview } from '../api/types';
import { areas, buildings, floors, property, user } from '../test/fixtures';
import { renderApp } from '../test/render';
import { fakeApi, page, type RecordedCall } from '../test/server';

const TOKEN = 'secret-token';

function device(overrides: Partial<HaDevicePlan>): HaDevicePlan {
  return {
    ha_device_id: 'dev',
    name: 'Device',
    manufacturer: null,
    model: null,
    ha_area_id: 'kitchen',
    area_name: 'Kitchen',
    status: 'new',
    match_reason: null,
    asset_id: null,
    asset_name: null,
    action: 'create',
    can_apply: true,
    changes: [],
    new_identifiers: [],
    note: null,
    ...overrides,
  };
}

const preview: HaPreview = {
  floors: [],
  areas: [
    {
      ha_area_id: 'garden',
      name: 'Garden',
      ha_floor_id: null,
      status: 'new',
      match_reason: null,
      area_id: null,
    },
  ],
  devices: [
    device({ ha_device_id: 'lamp', name: 'Reading Lamp', manufacturer: 'Signify' }),
    device({
      ha_device_id: 'fridge',
      name: 'Fridge',
      status: 'matched',
      match_reason: 'serial',
      asset_id: 'a1',
      asset_name: 'Refrigerator',
      action: 'link',
    }),
    device({ ha_device_id: 'sun', name: 'Sun', status: 'ignored', action: 'skip' }),
  ],
  counts: { new: 1, matched: 1, ignored: 1 },
};

const result: HaImportResult = {
  floors_created: 0,
  areas_created: 1,
  relations_created: 0,
  devices: [],
  counts: { created: 1, updated: 1, skipped: 1 },
};

function api(role: Parameters<typeof user>[0] = 'maintainer') {
  return fakeApi({
    'GET /auth/setup': () => ({ body: { needs_setup: false } }),
    'GET /auth/me': () => ({ body: user(role) }),
    'GET /properties/01a1a901-5800-7001-8000-000000000001': () => ({ body: property }),
    'GET /buildings': () => ({ body: page(buildings) }),
    'GET /floors': () => ({ body: page(floors) }),
    'GET /areas': () => ({ body: page(areas) }),
    'GET /assets': () => ({ body: page([]) }),
    'GET /maintenance/tasks': () => ({ body: page([]) }),
    'POST /homeassistant/preview': (call: RecordedCall) =>
      (call.body as { token: string }).token === TOKEN
        ? { body: preview }
        : { status: 422, body: { detail: 'Home Assistant rejected the access token' } },
    'POST /homeassistant/apply': () => ({ body: result }),
  });
}

async function connect(token = TOKEN) {
  const address = await screen.findByLabelText(/Home Assistant address/);
  await userEvent.clear(address);
  await userEvent.type(address, 'http://ha.local:8123');
  await userEvent.type(screen.getByLabelText(/Long-lived access token/), token);
  await userEvent.click(screen.getByRole('button', { name: 'Preview import' }));
}

describe('Home Assistant import', () => {
  it('previews, lets the user change an action, and applies', async () => {
    const { calls } = api();
    renderApp('/import/home-assistant');
    await connect();

    const table = await screen.findByRole('table', { name: 'Devices to import' });
    expect(within(table).getByText('Reading Lamp')).toBeInTheDocument();
    expect(within(table).getByText(/same serial number: Refrigerator/)).toBeInTheDocument();
    expect(screen.getByText('New areas: Garden')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import 2 Devices' })).toBeInTheDocument();

    const select = screen.getByRole('combobox', { name: 'Action for Reading Lamp' });
    await userEvent.click(select);
    const listbox = document.getElementById(select.getAttribute('aria-controls') ?? '');
    if (!listbox) throw new Error('the action list did not open');
    await userEvent.click(within(listbox).getByRole('option', { name: 'Skip', hidden: true }));
    await userEvent.click(screen.getByRole('button', { name: 'Import 1 Device' }));

    expect(await screen.findByText('Import finished')).toBeInTheDocument();
    expect(screen.getByText('1 added, 1 updated, 0 unchanged, 1 skipped')).toBeInTheDocument();
    const sent = calls.find((c) => c.path === '/homeassistant/apply');
    expect(sent?.body).toMatchObject({
      base_url: 'http://ha.local:8123',
      token: TOKEN,
      devices: [
        { ha_device_id: 'lamp', action: 'skip' },
        { ha_device_id: 'fridge', action: 'link', asset_id: 'a1' },
        { ha_device_id: 'sun', action: 'skip' },
      ],
    });
  });

  it('shows the server message when the token is rejected', async () => {
    api();
    renderApp('/import/home-assistant');
    await connect('wrong');
    expect(await screen.findByRole('alert')).toHaveTextContent('rejected the access token');
    expect(screen.getByLabelText(/Long-lived access token/)).toBeInTheDocument();
  });

  it('never saves the token in the browser', async () => {
    api();
    renderApp('/import/home-assistant');
    await connect();
    await screen.findByRole('table', { name: 'Devices to import' });
    const stored = [...Array(window.localStorage.length).keys()]
      .map((i) => window.localStorage.getItem(window.localStorage.key(i) ?? '') ?? '')
      .join(' ');
    expect(stored).not.toContain(TOKEN);
    expect(document.cookie).not.toContain(TOKEN);
  });

  it('is only offered to maintainers and admins', async () => {
    api('resident');
    renderApp('/import/home-assistant');
    expect(await screen.findByText('Maintainers only')).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Main' });
    await waitFor(() => expect(within(nav).getByText('Devices')).toBeInTheDocument());
    expect(within(nav).queryByText('Import from HA')).not.toBeInTheDocument();
  });

  it('shows the link in the menu for maintainers', async () => {
    api('maintainer');
    renderApp('/');
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    expect(await within(nav).findByText('Import from HA')).toBeInTheDocument();
  });
});

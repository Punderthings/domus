// Device add/edit and "mark done", against the in-memory fake API.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { AssetDetail, Role } from './api/types';
import {
  FRIDGE_ID,
  KITCHEN_ID,
  PROPERTY_ID,
  areas,
  buildings,
  floors,
  fridge,
  property,
  task,
  user,
} from './test/fixtures';
import { renderApp } from './test/render';
import { fakeApi, page, type RecordedCall } from './test/server';

const NEW_ID = '01a1a901-5800-7099-8000-000000000099';

type Routes = Parameters<typeof fakeApi>[0];

function api(role: Role = 'admin', device: AssetDetail = fridge, overrides: Routes = {}) {
  return fakeApi({
    'GET /auth/setup': () => ({ body: { needs_setup: false } }),
    'GET /auth/me': () => ({ body: user(role) }),
    [`GET /properties/${PROPERTY_ID}`]: () => ({ body: property }),
    'GET /buildings': () => ({ body: page(buildings) }),
    'GET /floors': () => ({ body: page(floors) }),
    'GET /areas': () => ({ body: page(areas) }),
    'GET /assets': () => ({ body: page([device]) }),
    [`GET /assets/${FRIDGE_ID}`]: () => ({ body: device }),
    [`GET /assets/${NEW_ID}`]: () => ({ body: { ...fridge, id: NEW_ID, name: 'Furnace' } }),
    'GET /locations': () => ({ body: page(device.location ? [device.location] : []) }),
    'POST /locations': (call: RecordedCall) => ({
      status: 201,
      body: { ...fridge.location, id: 'l2', ...(call.body as object) },
    }),
    'POST /products': (call: RecordedCall) => ({
      status: 201,
      body: { id: 'p2', ...(call.body as object) },
    }),
    'POST /assets': () => ({ status: 201, body: { ...fridge, id: NEW_ID, name: 'Furnace' } }),
    [`PATCH /assets/${FRIDGE_ID}`]: (call: RecordedCall) => ({
      body: { ...device, ...(call.body as object) },
    }),
    'GET /maintenance/tasks': () => ({ body: page([task({ next_due: '2026-11-01' })]) }),
    'POST /maintenance/tasks/task1/complete': (call: RecordedCall) => ({
      body: {
        event: { id: 'e1', ...(call.body as object) },
        task: task({ next_due: '2027-05-01' }),
      },
    }),
    ...overrides,
  });
}

async function pick(label: RegExp | string, option: string) {
  await userEvent.click(screen.getByRole('combobox', { name: label }));
  await userEvent.click(await screen.findByRole('option', { name: option, hidden: true }));
}

describe('adding a device', () => {
  it('offers "Add device" to maintainers but not residents', async () => {
    api('maintainer');
    const first = renderApp('/devices');
    expect(await screen.findByRole('link', { name: 'Add device' })).toHaveAttribute(
      'href',
      '/devices/new',
    );
    first.unmount();
    api('resident');
    renderApp('/devices');
    await screen.findByRole('link', { name: 'Refrigerator' });
    expect(screen.queryByRole('link', { name: 'Add device' })).not.toBeInTheDocument();
  });

  it('creates the location, the product, and the device, then opens it', async () => {
    const { calls } = api('admin');
    const { history } = renderApp('/devices/new');
    await userEvent.type(await screen.findByRole('textbox', { name: /^Name/ }), 'Furnace');
    await pick('Category', 'HVAC');
    await pick('Area', 'Kitchen');
    await pick('Location', 'New location…');
    await userEvent.type(screen.getByLabelText(/New location name/), 'Under the stairs');
    await userEvent.type(screen.getByLabelText('Manufacturer'), 'HeatCo');
    await userEvent.type(screen.getByLabelText('Serial number'), 'HC-1');
    await userEvent.type(screen.getByLabelText('Purchase price'), '2400.50');
    await userEvent.click(screen.getByRole('button', { name: 'Add device' }));

    await waitFor(() => expect(history.location.pathname).toBe(`/devices/${NEW_ID}`));
    const posted = (path: string) => calls.find((c) => c.method === 'POST' && c.path === path);
    expect(posted('/locations')?.body).toEqual({
      area_id: KITCHEN_ID,
      name: 'Under the stairs',
      kind: 'wall',
    });
    expect(posted('/products')?.body).toEqual({
      manufacturer: 'HeatCo',
      model: null,
      manual_url: null,
      category: 'hvac',
    });
    expect(posted('/assets')?.body).toMatchObject({
      property_id: PROPERTY_ID,
      name: 'Furnace',
      category: 'hvac',
      product_id: 'p2',
      location_id: 'l2',
      purchase_price: '2400.50',
      is_critical: false,
      identifiers: [{ kind: 'serial', value: 'HC-1', source: 'manual' }],
    });
  });

  it('checks the form before sending anything', async () => {
    const { calls } = api('admin');
    renderApp('/devices/new');
    await userEvent.type(await screen.findByLabelText('Manual link'), 'javascript:alert(1)');
    await userEvent.click(screen.getByRole('button', { name: 'Add device' }));
    expect(await screen.findByText('Enter a name')).toBeInTheDocument();
    expect(screen.getByText(/starts with http/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('tells a resident they cannot add devices', async () => {
    api('resident');
    renderApp('/devices/new');
    expect(await screen.findByText(/Only Maintainers and Admins/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add device' })).not.toBeInTheDocument();
  });
});

describe('editing a device', () => {
  it('sends only the changed fields and returns to the device', async () => {
    const { calls } = api('maintainer');
    const { history } = renderApp(`/devices/${FRIDGE_ID}`);
    await userEvent.click(await screen.findByRole('link', { name: 'Edit' }));
    const name = await screen.findByRole('textbox', { name: /^Name/ });
    expect(name).toHaveValue('Refrigerator');
    await userEvent.clear(name);
    await userEvent.type(name, 'Kitchen fridge');
    await userEvent.clear(screen.getByLabelText('Warranty until'));
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    await waitFor(() => expect(history.location.pathname).toBe(`/devices/${FRIDGE_ID}`));
    const patch = calls.find((c) => c.method === 'PATCH');
    expect(patch?.body).toEqual({ name: 'Kitchen fridge', warranty_expires: null });
    expect(calls.some((c) => c.path === '/products')).toBe(false);
  });

  it('shows the critical flag only to admins', async () => {
    api('maintainer');
    const first = renderApp(`/devices/${FRIDGE_ID}/edit`);
    await screen.findByRole('button', { name: 'Save changes' });
    expect(screen.queryByLabelText(/Critical/)).not.toBeInTheDocument();
    first.unmount();
    const { calls } = api('admin');
    renderApp(`/devices/${FRIDGE_ID}/edit`);
    await userEvent.click(await screen.findByLabelText(/Critical/));
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ is_critical: true }),
    );
  });

  it('hides Edit from residents and from devices the user cannot manage', async () => {
    api('resident');
    const first = renderApp(`/devices/${FRIDGE_ID}`);
    await screen.findByRole('heading', { name: 'Refrigerator', level: 2 });
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument();
    first.unmount();
    api('maintainer', { ...fridge, access: 'control' });
    renderApp(`/devices/${FRIDGE_ID}`);
    await screen.findByRole('heading', { name: 'Refrigerator', level: 2 });
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument();
  });

  it('shows the error the API returns', async () => {
    api('maintainer', fridge, {
      [`PATCH /assets/${FRIDGE_ID}`]: () => ({
        status: 400,
        body: { detail: 'location_id not found in this property' },
      }),
    });
    renderApp(`/devices/${FRIDGE_ID}/edit`);
    await userEvent.type(await screen.findByLabelText('Vendor'), 'ACME');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('location_id not found');
  });
});

describe('marking maintenance done', () => {
  it('logs the work with a cost in the property currency', async () => {
    const { calls } = api('resident');
    renderApp(`/devices/${FRIDGE_ID}`);
    await userEvent.click(
      await screen.findByRole('button', { name: 'Mark done: Replace refrigerator water filter' }),
    );
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Cost (USD)'), '49.99');
    await userEvent.type(within(dialog).getByLabelText('Notes'), 'Used the OEM filter');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));

    expect(await screen.findByText(/Next due/)).toBeInTheDocument();
    const call = calls.find((c) => c.path === '/maintenance/tasks/task1/complete');
    expect(call?.body).toMatchObject({
      outcome: 'done',
      cost: '49.99',
      currency: 'USD',
      notes: 'Used the OEM filter',
    });
    expect((call?.body as { performed_on: string }).performed_on).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('sends no cost or currency when the cost is empty, and refuses a bad cost', async () => {
    const { calls } = api('admin');
    renderApp('/');
    await userEvent.click(
      await screen.findByRole('button', { name: /^Mark done: Replace refrigerator/ }),
    );
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(within(dialog).getByLabelText('Cost (USD)'), '12,50');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await within(dialog).findByText('Use a number such as 49.99')).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith('/complete'))).toBe(false);

    await userEvent.clear(within(dialog).getByLabelText('Cost (USD)'));
    await pickIn(dialog, 'Outcome', 'Skipped');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/complete'))?.body).toMatchObject({
        outcome: 'skipped',
        cost: null,
        currency: null,
        notes: null,
      }),
    );
  });

  it('is not offered to guests', async () => {
    api('guest');
    renderApp(`/devices/${FRIDGE_ID}`);
    await screen.findByText('Replace refrigerator water filter');
    expect(screen.queryByRole('button', { name: /Mark done/ })).not.toBeInTheDocument();
  });
});

async function pickIn(container: HTMLElement, label: string, option: string) {
  await userEvent.click(within(container).getByRole('combobox', { name: label }));
  await userEvent.click(await screen.findByRole('option', { name: option, hidden: true }));
}

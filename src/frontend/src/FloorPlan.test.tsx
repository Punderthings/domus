// Floor plan and wall photo pages, against the in-memory fake API.
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { Canvas, Placement, Role } from './api/types';
import {
  FRIDGE_ID,
  KITCHEN_ID,
  MAIN_FLOOR,
  PLAN_ID,
  areas,
  floorPlan,
  floors,
  fridge,
  fridgePin,
  property,
  user,
} from './test/fixtures';
import { renderApp } from './test/render';
import { fakeApi, page, type RecordedCall } from './test/server';

function serve(role: Role, plans: Canvas[], pins: Placement[] = []) {
  return fakeApi({
    'GET /auth/setup': () => ({ body: { needs_setup: false } }),
    'GET /auth/me': () => ({ body: user(role) }),
    [`GET /properties/${property.id}`]: () => ({ body: property }),
    [`GET /floors/${MAIN_FLOOR}`]: () => ({
      body: { ...floors[0], access: role === 'guest' ? 'view' : 'manage' },
    }),
    'GET /areas': () => ({ body: page(areas) }),
    'GET /assets': () => ({ body: page([fridge]) }),
    'GET /canvases': (call: RecordedCall) => ({
      body: page(plans.filter((c) => c.kind === call.search.get('kind'))),
    }),
    [`GET /canvases/${PLAN_ID}/placements`]: () => ({ body: page(pins) }),
    'POST /documents': () => ({ status: 201, body: { id: 'd2' } }),
    'POST /canvases': () => ({ status: 201, body: floorPlan() }),
    'POST /placements': () => ({ status: 201, body: fridgePin() }),
    'DELETE /placements/pin1': () => ({ status: 204 }),
  });
}

const pngFile = () =>
  new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], 'main.png', {
    type: 'image/png',
  });

describe('floor plan page', () => {
  it('lets a Maintainer upload the first floor plan', async () => {
    const { calls } = serve('maintainer', []);
    const { container } = renderApp(`/floors/${MAIN_FLOOR}`);
    expect(await screen.findByText(/No floor plan yet/)).toBeInTheDocument();
    await screen.findByRole('button', { name: 'Upload floor plan' });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, pngFile());
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path === '/canvases')).toBe(true),
    );
    const doc = calls.find((c) => c.path === '/documents');
    expect(doc?.headers['content-type']).toBe('image/png');
    expect(doc?.search.get('kind')).toBe('floor_plan');
    expect(doc?.search.get('sensitivity')).toBe('guest');
    expect(doc?.search.get('filename')).toBe('main.png');
    const canvas = calls.find((c) => c.method === 'POST' && c.path === '/canvases');
    expect(canvas?.body).toMatchObject({
      document_id: 'd2',
      scope_type: 'floor',
      scope_id: MAIN_FLOOR,
      kind: 'floor_plan',
    });
  });

  it('tells a Guest who can add one, with no upload button', async () => {
    serve('guest', []);
    renderApp(`/floors/${MAIN_FLOOR}`);
    expect(await screen.findByText(/A Maintainer or Admin can add one/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Upload floor plan' })).not.toBeInTheDocument();
  });

  it('lists pins as links and hides editing from viewers', async () => {
    serve('guest', [floorPlan({ access: 'view' })], [fridgePin({ access: 'view' })]);
    renderApp(`/floors/${MAIN_FLOOR}`);
    const link = await screen.findByRole('link', { name: 'Refrigerator' });
    expect(link).toHaveAttribute('href', `/devices/${FRIDGE_ID}`);
    expect(
      await screen.findByRole('img', { name: 'Floor plan of Main Floor' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit pins' })).not.toBeInTheDocument();
  });

  it('places a device in the middle of the plan', async () => {
    const { calls } = serve('admin', [floorPlan()]);
    renderApp(`/floors/${MAIN_FLOOR}`);
    await userEvent.click(await screen.findByRole('button', { name: 'Edit pins' }));
    await userEvent.click(screen.getByRole('combobox', { name: 'Device to place' }));
    await userEvent.click(
      await screen.findByRole('option', { name: 'Refrigerator', hidden: true }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Place in the middle' }));
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.path === '/placements');
      expect(post?.body).toEqual({ canvas_id: PLAN_ID, asset_id: FRIDGE_ID, x: 0.5, y: 0.5 });
    });
  });

  it('removes a pin in edit mode', async () => {
    const { calls } = serve('admin', [floorPlan()], [fridgePin()]);
    renderApp(`/floors/${MAIN_FLOOR}`);
    await userEvent.click(await screen.findByRole('button', { name: 'Edit pins' }));
    await userEvent.click(screen.getByRole('button', { name: 'Remove pin for Refrigerator' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path === '/placements/pin1')).toBe(true),
    );
  });
});

describe('area page', () => {
  it('links to the floor plan and offers a wall photo to Maintainers', async () => {
    serve('maintainer', []);
    renderApp(`/areas/${KITCHEN_ID}`);
    expect(await screen.findByRole('heading', { name: 'Wall photos' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'See the floor plan' })).toHaveAttribute(
      'href',
      `/floors/${MAIN_FLOOR}`,
    );
    expect(screen.getByRole('button', { name: 'Add wall photo' })).toBeInTheDocument();
  });
});

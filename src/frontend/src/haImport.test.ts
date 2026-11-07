import { describe, expect, it } from 'vitest';
import type { HaDevicePlan } from './api/types';
import { actionsFor } from './haImport';

function plan(overrides: Partial<HaDevicePlan>): HaDevicePlan {
  return {
    ha_device_id: 'd1',
    name: 'Lamp',
    manufacturer: null,
    model: null,
    ha_area_id: null,
    area_name: null,
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

describe('actionsFor', () => {
  it('offers create or skip for new and ignored devices', () => {
    expect(actionsFor(plan({ status: 'new' }))).toEqual(['create', 'skip']);
    expect(actionsFor(plan({ status: 'ignored', action: 'skip' }))).toEqual(['create', 'skip']);
  });

  it('lets a match be linked, added separately, or skipped', () => {
    expect(actionsFor(plan({ status: 'matched', action: 'link' }))).toEqual([
      'link',
      'create',
      'skip',
    ]);
  });

  it('never offers to duplicate a linked device', () => {
    expect(actionsFor(plan({ status: 'linked', action: 'skip' }))).toEqual(['link', 'skip']);
    expect(actionsFor(plan({ status: 'changed', action: 'link' }))).toEqual(['link', 'skip']);
  });

  it('only skips what the user may not change', () => {
    expect(actionsFor(plan({ status: 'matched', can_apply: false }))).toEqual(['skip']);
  });
});

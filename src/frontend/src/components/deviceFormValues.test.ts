import { describe, expect, it } from 'vitest';
import { fridge, fridgeForGuest } from '../test/fixtures';
import {
  COST_PATTERN,
  NEW_LOCATION,
  changedFields,
  initialValues,
  validate,
} from './deviceFormValues';

describe('initialValues', () => {
  it('starts a new device as active, uncategorized, and nowhere', () => {
    const values = initialValues();
    expect(values).toMatchObject({ name: '', category: 'other', status: 'active', area_id: '' });
  });

  it('copies an existing device, its product, and its area', () => {
    const values = initialValues(fridge);
    expect(values).toMatchObject({
      name: 'Refrigerator',
      area_id: fridge.location?.area_id,
      location_id: 'l1',
      manufacturer: 'ExampleCo Appliances',
      model: 'FR-2400',
      purchase_price: '1899.00',
      install_date: '2021-03-14',
    });
  });

  it('leaves the fields a guest cannot see empty', () => {
    expect(initialValues(fridgeForGuest).purchase_price).toBe('');
  });
});

describe('changedFields', () => {
  it('sends only what changed, and a cleared field as null', () => {
    const initial = initialValues(fridge);
    const values = { ...initial, name: '  Kitchen fridge ', install_date: '', vendor: 'ACME' };
    expect(changedFields(values, initial)).toEqual({
      name: 'Kitchen fridge',
      install_date: null,
      vendor: 'ACME',
    });
  });

  it('ignores whitespace-only edits', () => {
    const initial = initialValues(fridge);
    expect(changedFields({ ...initial, notes: `${initial.notes}  ` }, initial)).toEqual({});
  });
});

describe('validate', () => {
  const ok = { ...initialValues(), name: 'Furnace' };

  it('accepts a minimal device', () => {
    expect(Object.values(validate(ok)).filter(Boolean)).toEqual([]);
  });

  it('needs a name', () => {
    expect(validate({ ...ok, name: '   ' }).name).toBe('Enter a name');
  });

  it('refuses non-http manual links', () => {
    expect(validate({ ...ok, manual_url: 'javascript:alert(1)' }).manual_url).toMatch(/http/);
    expect(validate({ ...ok, manual_url: 'https://example.com/m.pdf' }).manual_url).toBeNull();
  });

  it('checks prices and dates', () => {
    expect(validate({ ...ok, purchase_price: '12.345' }).purchase_price).not.toBeNull();
    expect(validate({ ...ok, warranty_expires: '14/03/2026' }).warranty_expires).not.toBeNull();
  });

  it('needs a name for a new location', () => {
    expect(validate({ ...ok, area_id: 'a', location_id: NEW_LOCATION }).new_location_name).toBe(
      'Name the new location',
    );
  });
});

describe('COST_PATTERN', () => {
  it.each(['0', '49', '49.9', '49.99', '1234567890.00'])('accepts %s', (v) => {
    expect(COST_PATTERN.test(v)).toBe(true);
  });
  it.each(['', '-1', '1.234', '1e3', '12,50', '12345678901'])('refuses %s', (v) => {
    expect(COST_PATTERN.test(v)).toBe(false);
  });
});

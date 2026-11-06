// A slice of examples/sample-home/, shaped as the API returns it.
import type {
  Area,
  AssetDetail,
  Building,
  CurrentUser,
  Floor,
  MaintenanceTask,
  Property,
} from '../api/types';

const stamp = { created_at: '2026-11-05T00:00:00Z', updated_at: '2026-11-05T00:00:00Z' };
export const PROPERTY_ID = '01a1a901-5800-7001-8000-000000000001';
const BUILDING_ID = '01a1a901-5800-7002-8000-000000000002';
const MAIN_FLOOR = '01a1a901-5800-7003-8000-000000000003';
const BASEMENT = '01a1a901-5800-7004-8000-000000000004';
export const KITCHEN_ID = '01a1a901-5800-7005-8000-000000000005';
export const FRIDGE_ID = '01a1a901-5800-7012-8000-000000000012';

export function user(role: CurrentUser['memberships'][number]['role'] = 'admin'): CurrentUser {
  return {
    id: 'u1',
    email: 'pat@example.com',
    display_name: 'Pat',
    memberships: [{ id: 'm1', property_id: PROPERTY_ID, role, expires_at: null }],
  };
}

export const property: Property = {
  id: PROPERTY_ID,
  ...stamp,
  name: 'Sample Home',
  address: '123 Example Lane, Springfield',
  timezone: 'America/New_York',
  default_currency: 'USD',
};

export const buildings: Building[] = [
  {
    id: BUILDING_ID,
    ...stamp,
    property_id: PROPERTY_ID,
    name: 'House',
    kind: 'house',
    is_primary: true,
  },
];

export const floors: Floor[] = [
  { id: MAIN_FLOOR, ...stamp, building_id: BUILDING_ID, name: 'Main Floor', level: 0 },
  { id: BASEMENT, ...stamp, building_id: BUILDING_ID, name: 'Basement', level: -1 },
];

const area = (id: string, name: string, floor_id: string, is_critical = false): Area => ({
  id,
  ...stamp,
  property_id: PROPERTY_ID,
  building_id: BUILDING_ID,
  floor_id,
  name,
  kind: 'room',
  is_critical,
});

export const areas: Area[] = [
  area(KITCHEN_ID, 'Kitchen', MAIN_FLOOR),
  area('01a1a901-5800-7006-8000-000000000006', 'Living Room', MAIN_FLOOR),
  area('01a1a901-5800-7008-8000-000000000008', 'Utility Room', BASEMENT, true),
  {
    ...area('01a1a901-5800-70ff-8000-0000000000ff', 'Back Yard', MAIN_FLOOR),
    building_id: null,
    floor_id: null,
    kind: 'yard',
  },
];

export const fridge: AssetDetail = {
  id: FRIDGE_ID,
  ...stamp,
  access: 'manage',
  property_id: PROPERTY_ID,
  product_id: 'p1',
  location_id: 'l1',
  parent_asset_id: null,
  name: 'Refrigerator',
  category: 'appliance',
  status: 'active',
  install_date: '2021-03-14',
  is_critical: false,
  notes: 'Water filter part FR-WF1, behind the lower grille.',
  purchase_price: 1899,
  warranty_expires: '2026-03-14',
  tags: [{ id: 't1', name: 'smart', color: '#228be6' }],
  product: {
    id: 'p1',
    ...stamp,
    manufacturer: 'ExampleCo Appliances',
    model: 'FR-2400',
    manual_url: 'https://example.com/manuals/fr-2400.pdf',
  },
  location: {
    id: 'l1',
    ...stamp,
    area_id: KITCHEN_ID,
    name: 'Fridge alcove',
    kind: 'wall',
    position_note: 'Between the pantry and the back door',
  },
  identifiers: [{ id: 'i1', kind: 'serial_number', value: 'FR24-0001', source: 'label' }],
};

/** What a guest gets: sensitive fields omitted, not null. */
export function guestView(asset: AssetDetail): AssetDetail {
  const copy: AssetDetail = { ...asset, access: 'view' };
  delete copy.purchase_price;
  delete copy.identifiers;
  delete copy.warranty_expires;
  return copy;
}

export function task(overrides: Partial<MaintenanceTask>): MaintenanceTask {
  return {
    id: 'task1',
    ...stamp,
    property_id: PROPERTY_ID,
    asset_id: FRIDGE_ID,
    location_id: null,
    title: 'Replace refrigerator water filter',
    schedule_kind: 'after_completion',
    interval_value: 6,
    interval_unit: 'month',
    rrule: null,
    next_due: '2027-03-01',
    lead_days: 7,
    active: true,
    ...overrides,
  };
}

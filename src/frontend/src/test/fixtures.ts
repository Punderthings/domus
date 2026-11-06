// A slice of examples/sample-home/, shaped as the API returns it (see openapi.json).
import type {
  Area,
  AssetDetail,
  Building,
  CurrentUser,
  Floor,
  MaintenanceTask,
  Property,
  Role,
} from '../api/types';

const stamp = { created_at: '2026-11-05T00:00:00Z', updated_at: '2026-11-05T00:00:00Z' };
export const PROPERTY_ID = '01a1a901-5800-7001-8000-000000000001';
const BUILDING_ID = '01a1a901-5800-7002-8000-000000000002';
const MAIN_FLOOR = '01a1a901-5800-7003-8000-000000000003';
const BASEMENT = '01a1a901-5800-7004-8000-000000000004';
export const KITCHEN_ID = '01a1a901-5800-7005-8000-000000000005';
export const FRIDGE_ID = '01a1a901-5800-7012-8000-000000000012';

export function user(role: Role = 'admin'): CurrentUser {
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
  access: 'manage',
};

export const buildings: Building[] = [
  {
    id: BUILDING_ID,
    ...stamp,
    property_id: PROPERTY_ID,
    name: 'House',
    kind: 'house',
    is_primary: true,
    year_built: 1998,
    notes: null,
    access: 'manage',
  },
];

const floor = (id: string, name: string, level: number): Floor => ({
  id,
  ...stamp,
  building_id: BUILDING_ID,
  name,
  level,
  ha_floor_id: null,
  access: 'manage',
});

export const floors: Floor[] = [
  floor(MAIN_FLOOR, 'Main Floor', 0),
  floor(BASEMENT, 'Basement', -1),
];

const area = (id: string, name: string, floor_id: string | null, is_critical = false): Area => ({
  id,
  ...stamp,
  property_id: PROPERTY_ID,
  building_id: floor_id ? BUILDING_ID : null,
  floor_id,
  name,
  kind: floor_id ? 'room' : 'yard',
  ha_area_id: null,
  is_critical,
  access: 'manage',
});

export const areas: Area[] = [
  area(KITCHEN_ID, 'Kitchen', MAIN_FLOOR),
  area('01a1a901-5800-7006-8000-000000000006', 'Living Room', MAIN_FLOOR),
  area('01a1a901-5800-7008-8000-000000000008', 'Utility Room', BASEMENT, true),
  area('01a1a901-5800-70ff-8000-0000000000ff', 'Back Yard', null),
];

const product = {
  id: 'p1',
  ...stamp,
  manufacturer: 'ExampleCo Appliances',
  model: 'FR-2400',
  model_id: null,
  category: 'appliance',
  manual_url: 'https://example.com/manuals/fr-2400.pdf',
  support_url: null,
};

const shared = {
  id: FRIDGE_ID,
  ...stamp,
  property_id: PROPERTY_ID,
  product_id: 'p1',
  location_id: 'l1',
  area_id: KITCHEN_ID,
  parent_asset_id: null,
  name: 'Refrigerator',
  category: 'appliance',
  status: 'active',
  is_critical: false,
  notes: 'Water filter part FR-WF1, behind the lower grille.',
  tags: [{ id: 't1', name: 'smart', color: '#228be6' }],
  product,
  location: {
    id: 'l1',
    ...stamp,
    area_id: KITCHEN_ID,
    parent_location_id: null,
    name: 'Fridge alcove',
    kind: 'wall',
    orientation: 'N',
    position_note: 'Between the pantry and the back door',
    access: 'manage' as const,
  },
};

export const fridge: AssetDetail = {
  ...shared,
  access: 'manage',
  install_date: '2021-03-14',
  purchase_date: null,
  purchase_price: '1899.00',
  vendor: null,
  warranty_expires: '2026-03-14',
  sw_version: null,
  hw_version: null,
  identifiers: [{ id: 'i1', kind: 'serial_number', value: 'FR24-0001', source: 'label' }],
};

/** What a guest gets: the narrower schema, with sensitive fields left out. */
export const fridgeForGuest: AssetDetail = { ...shared, access: 'view' };

/** The fridge with a different manual link. */
export function withManual(manual_url: string): AssetDetail {
  return { ...fridge, product: { ...product, manual_url } };
}

export function task(overrides: Partial<MaintenanceTask>): MaintenanceTask {
  return {
    id: 'task1',
    ...stamp,
    property_id: PROPERTY_ID,
    asset_id: FRIDGE_ID,
    location_id: null,
    title: 'Replace refrigerator water filter',
    procedure: null,
    schedule_kind: 'after_completion',
    interval_value: 6,
    interval_unit: 'month',
    rrule: null,
    anchor_date: null,
    next_due: '2027-03-01',
    lead_days: 7,
    active: true,
    access: 'manage',
    ...overrides,
  };
}

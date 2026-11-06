// Types for the Domus REST API (/api/v1). Field names follow the data model in
// docs/_prompts/plan/data-storage-backup.md and examples/sample-home/.
// Hand-written until the backend publishes openapi.json; then these are
// replaced by types generated from it.

export type Role = 'admin' | 'maintainer' | 'resident' | 'guest';

/** The current user's effective access to one object (hidden objects are omitted). */
export type Access = 'view' | 'control' | 'manage';

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

interface Row {
  id: string;
  created_at: string;
  updated_at: string;
  access?: Access;
}

export interface Membership {
  id: string;
  property_id: string;
  role: Role;
  expires_at: string | null;
}

export interface CurrentUser {
  id: string;
  email: string;
  display_name: string;
  memberships: Membership[];
}

export interface SetupStatus {
  needs_setup: boolean;
}

export interface Property extends Row {
  name: string;
  address?: string | null;
  timezone: string;
  default_currency?: string | null;
}

export interface Building extends Row {
  property_id: string;
  name: string;
  kind: string;
  is_primary: boolean;
  year_built?: number | null;
  notes?: string | null;
}

export interface Floor extends Row {
  building_id: string;
  name: string;
  level: number;
}

/** Home Assistant "area": a room, hallway, or outdoor space. */
export interface Area extends Row {
  property_id: string;
  building_id: string | null;
  floor_id: string | null;
  name: string;
  kind: string;
  is_critical: boolean;
}

export interface Location extends Row {
  area_id: string;
  name: string;
  kind: string;
  orientation?: string | null;
  position_note?: string | null;
}

export interface Product extends Row {
  manufacturer: string | null;
  model: string | null;
  model_id?: string | null;
  category?: string | null;
  manual_url?: string | null;
}

export interface Tag {
  id: string;
  name: string;
  color: string | null;
}

export interface AssetIdentifier {
  id: string;
  kind: string;
  value: string;
  source?: string | null;
}

export interface Asset extends Row {
  property_id: string;
  product_id: string | null;
  location_id: string | null;
  parent_asset_id: string | null;
  name: string;
  category: string;
  status: string;
  install_date?: string | null;
  is_critical: boolean;
  notes?: string | null;
  /** Decimal string such as "49.99". Omitted for guests. */
  purchase_price?: string | null;
  warranty_expires?: string | null;
  tags?: Tag[];
}

export interface AssetDetail extends Asset {
  product: Product | null;
  location: Location | null;
  /** Omitted for guests. */
  identifiers?: AssetIdentifier[];
}

export interface MaintenanceTask extends Row {
  property_id: string;
  asset_id: string | null;
  location_id: string | null;
  title: string;
  schedule_kind: 'after_completion' | 'fixed_calendar';
  interval_value: number | null;
  interval_unit: 'day' | 'week' | 'month' | 'year' | null;
  rrule: string | null;
  next_due: string | null;
  lead_days: number | null;
  active: boolean;
  procedure?: string | null;
}

// Values, rules, and helpers for DeviceForm, kept out of the component file so they
// can be unit tested and so React fast refresh keeps working.

import type { AssetInput, AssetUpdateInput, LocationInput } from '../api/mutations';
import type { AssetDetail } from '../api/types';
import { humanize } from '../format';

/** Money as the API takes it: digits with up to two decimals, no more than 12 digits. */
export const COST_PATTERN = /^\d{1,10}(\.\d{1,2})?$/;

type Category = NonNullable<AssetInput['category']>;
type Status = NonNullable<AssetInput['status']>;
type LocationKind = NonNullable<LocationInput['kind']>;

// The API's enums (src/domus/models/enums.py).
export const CATEGORIES = [
  'appliance',
  'hvac',
  'plumbing',
  'electrical',
  'lighting',
  'network',
  'sensor',
  'security',
  'structural',
  'other',
] as const satisfies readonly Category[];
export const STATUSES = [
  'active',
  'spare',
  'retired',
  'disposed',
] as const satisfies readonly Status[];
export const LOCATION_KINDS = [
  'wall',
  'window',
  'door',
  'ceiling',
  'floor',
  'cabinet',
  'closet',
  'exterior_wall',
] as const satisfies readonly LocationKind[];

export const NEW_LOCATION = '__new__';
const DATE = /^\d{4}-\d{2}-\d{2}$/;

export const options = (values: readonly string[]) =>
  values.map((value) => ({ value, label: value === 'hvac' ? 'HVAC' : humanize(value) }));

export interface DeviceValues {
  name: string;
  category: Category;
  status: Status;
  area_id: string;
  location_id: string;
  new_location_name: string;
  new_location_kind: LocationKind;
  manufacturer: string;
  model: string;
  manual_url: string;
  serial: string;
  install_date: string;
  purchase_date: string;
  purchase_price: string;
  vendor: string;
  warranty_expires: string;
  is_critical: boolean;
  notes: string;
}

/** Simple fields that map one to one onto the asset; '' means "not set". */
const ASSET_FIELDS = [
  'name',
  'category',
  'status',
  'install_date',
  'purchase_date',
  'purchase_price',
  'vendor',
  'warranty_expires',
  'notes',
] as const;

export function initialValues(device?: AssetDetail): DeviceValues {
  const str = (value: string | null | undefined) => value ?? '';
  const full = device && 'install_date' in device ? device : undefined;
  return {
    name: str(device?.name),
    category: (device?.category ?? 'other') as Category,
    status: (device?.status ?? 'active') as Status,
    area_id: str(device?.location?.area_id ?? device?.area_id),
    location_id: str(device?.location_id),
    new_location_name: '',
    new_location_kind: 'wall',
    manufacturer: str(device?.product?.manufacturer),
    model: str(device?.product?.model),
    manual_url: str(device?.product?.manual_url),
    serial: '',
    install_date: str(full?.install_date),
    purchase_date: str(full?.purchase_date),
    purchase_price: str(full?.purchase_price),
    vendor: str(full?.vendor),
    warranty_expires: str(full?.warranty_expires),
    is_critical: device?.is_critical ?? false,
    notes: str(device?.notes),
  };
}

const dateRule = (v: string) => (v && !DATE.test(v) ? 'Use a date such as 2026-03-14' : null);

export function validate(values: DeviceValues) {
  return {
    name: values.name.trim()
      ? values.name.length > 200
        ? 'Use 200 characters or fewer'
        : null
      : 'Enter a name',
    manual_url:
      values.manual_url.trim() && !/^https?:\/\/\S+$/.test(values.manual_url.trim())
        ? 'Use a link that starts with http:// or https://'
        : null,
    purchase_price:
      values.purchase_price.trim() && !COST_PATTERN.test(values.purchase_price.trim())
        ? 'Use a number such as 49.99'
        : null,
    install_date: dateRule(values.install_date),
    purchase_date: dateRule(values.purchase_date),
    warranty_expires: dateRule(values.warranty_expires),
    new_location_name:
      values.location_id === NEW_LOCATION && !values.new_location_name.trim()
        ? 'Name the new location'
        : null,
  };
}

export const orNull = (value: string) => value.trim() || null;

/** The changed asset fields, with '' sent as null so a cleared field is cleared. */
export function changedFields(values: DeviceValues, initial: DeviceValues): AssetUpdateInput {
  const body: Record<string, string | null> = {};
  for (const field of ASSET_FIELDS) {
    if (values[field].trim() !== initial[field].trim()) {
      body[field] = field === 'name' ? values.name.trim() : orNull(values[field]);
    }
  }
  return body as AssetUpdateInput;
}

export const productChanged = (values: DeviceValues, initial: DeviceValues) =>
  (['manufacturer', 'model', 'manual_url'] as const).some(
    (field) => values[field].trim() !== initial[field].trim(),
  );

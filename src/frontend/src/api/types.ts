// Friendly names for the API types generated from openapi.json (see schema.d.ts,
// made by `npm run api:types`). Field names follow the data model in
// docs/_prompts/plan/data-storage-backup.md.

import type { components } from './schema';

type Schemas = components['schemas'];

export type Role = 'admin' | 'maintainer' | 'resident' | 'guest';

/** The current user's effective access to one object (hidden objects are omitted). */
export type Access = Schemas['AreaOut']['access'];

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
}

export type CurrentUser = Schemas['MeOut'];
export type Membership = Schemas['MembershipOut'];
export type SetupStatus = Schemas['SetupStatus'];
export type LoginInput = Schemas['LoginIn'];
export type SetupInput = Schemas['SetupIn'];
export type Property = Schemas['PropertyOut'];
export type Building = Schemas['BuildingOut'];
export type Floor = Schemas['FloorOut'];
/** Home Assistant "area": a room, hallway, or outdoor space. */
export type Area = Schemas['AreaOut'];
export type Location = Schemas['LocationOut'];
export type Product = Schemas['ProductOut'];
export type Tag = Schemas['TagRef'];
export type AssetIdentifier = Schemas['IdentifierOut'];
/** Guests get the narrower schema: no purchase, warranty, version, or install fields. */
export type Asset = Schemas['AssetOut'] | Schemas['AssetGuestOut'];
/** Guests get no identifiers and none of the fields left out of `Asset`. */
export type AssetDetail = Schemas['AssetDetailOut'] | Schemas['AssetGuestDetailOut'];
export type MaintenanceTask = Schemas['TaskOut'];
export type Document = Schemas['DocumentOut'];
/** An image devices can be pinned onto: a floor plan, wall photo, or panel photo. */
export type Canvas = Schemas['CanvasOut'];
export type CanvasKind = Schemas['CanvasIn']['kind'];
/** One device pin on a canvas, at 0-1 coordinates of the image. */
export type Placement = Schemas['PlacementOut'];
/** Search hits: devices and areas, best match first, hidden items left out. */
export type SearchResults = Schemas['SearchOut'];

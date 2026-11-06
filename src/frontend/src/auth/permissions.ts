import type { Access, Membership, Role } from '../api/types';

const ROLE_RANK: Record<Role, number> = { guest: 0, resident: 1, maintainer: 2, admin: 3 };
const ACCESS_RANK: Record<Access, number> = { view: 0, control: 1, manage: 2 };

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Admin',
  maintainer: 'Maintainer',
  resident: 'Resident',
  guest: 'Guest',
};

/** Narrow the API's role string; anything unknown gets the least access. */
export function toRole(value: string): Role {
  return value in ROLE_RANK ? (value as Role) : 'guest';
}

/** True if `role` ranks at or above `minimum` (Admin > Maintainer > Resident > Guest). */
export function hasRole(role: Role | undefined, minimum: Role): boolean {
  return role !== undefined && ROLE_RANK[role] >= ROLE_RANK[minimum];
}

/**
 * True if the server-reported access level allows `needed`. The UI only hides
 * controls; the API enforces every rule. A missing level is treated as view.
 */
export function allows(access: Access | undefined, needed: Access): boolean {
  return ACCESS_RANK[access ?? 'view'] >= ACCESS_RANK[needed];
}

/** Pick the active membership: the remembered property if still valid, else the first. */
export function pickMembership(
  memberships: Membership[],
  preferredPropertyId: string | null,
  now: Date = new Date(),
): Membership | undefined {
  const active = memberships.filter((m) => !m.expires_at || new Date(m.expires_at) > now);
  return active.find((m) => m.property_id === preferredPropertyId) ?? active[0];
}

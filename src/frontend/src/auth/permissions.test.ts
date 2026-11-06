import { describe, expect, it } from 'vitest';
import type { Membership } from '../api/types';
import { allows, hasRole, pickMembership } from './permissions';

describe('hasRole', () => {
  it('ranks Admin > Maintainer > Resident > Guest', () => {
    expect(hasRole('admin', 'maintainer')).toBe(true);
    expect(hasRole('maintainer', 'maintainer')).toBe(true);
    expect(hasRole('resident', 'maintainer')).toBe(false);
    expect(hasRole('guest', 'resident')).toBe(false);
    expect(hasRole(undefined, 'guest')).toBe(false);
  });
});

describe('allows', () => {
  it('follows the view < control < manage ladder', () => {
    expect(allows('manage', 'control')).toBe(true);
    expect(allows('control', 'control')).toBe(true);
    expect(allows('view', 'control')).toBe(false);
  });
  it('treats a missing level as view only', () => {
    expect(allows(undefined, 'view')).toBe(true);
    expect(allows(undefined, 'control')).toBe(false);
  });
});

describe('pickMembership', () => {
  const now = new Date('2026-11-06T12:00:00Z');
  const m = (id: string, property_id: string, expires_at: string | null = null): Membership => ({
    id,
    property_id,
    role: 'resident',
    expires_at,
  });

  it('prefers the remembered property', () => {
    expect(pickMembership([m('a', 'p1'), m('b', 'p2')], 'p2', now)?.id).toBe('b');
  });
  it('falls back to the first membership', () => {
    expect(pickMembership([m('a', 'p1'), m('b', 'p2')], 'gone', now)?.id).toBe('a');
    expect(pickMembership([m('a', 'p1')], null, now)?.id).toBe('a');
  });
  it('skips expired memberships, such as a finished house sit', () => {
    const list = [m('old', 'p1', '2026-11-01T00:00:00Z'), m('b', 'p2', '2026-12-01T00:00:00Z')];
    expect(pickMembership(list, 'p1', now)?.id).toBe('b');
    expect(pickMembership([m('old', 'p1', '2026-11-01T00:00:00Z')], null, now)).toBeUndefined();
  });
  it('returns undefined with no memberships', () => {
    expect(pickMembership([], null, now)).toBeUndefined();
  });
});

describe('toRole', () => {
  it('keeps known roles and gives unknown ones the least access', async () => {
    const { toRole } = await import('./permissions');
    expect(toRole('maintainer')).toBe('maintainer');
    expect(toRole('superuser')).toBe('guest');
    expect(toRole('')).toBe('guest');
  });
});

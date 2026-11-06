import { useCurrentUser } from '../api/queries';
import type { Membership } from '../api/types';
import { pickMembership } from './permissions';

export const PROPERTY_STORAGE_KEY = 'domus.propertyId';

function rememberedPropertyId(): string | null {
  try {
    return window.localStorage.getItem(PROPERTY_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** The property the user is working in, and their membership (role) there. */
export function useActiveMembership(): Membership | undefined {
  const { data: user } = useCurrentUser();
  return user ? pickMembership(user.memberships, rememberedPropertyId()) : undefined;
}

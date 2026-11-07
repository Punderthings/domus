import { useSyncExternalStore } from 'react';
import { useCurrentUser } from '../api/queries';
import type { Membership } from '../api/types';
import { activePropertyId, subscribeActiveProperty } from './activeProperty';
import { pickMembership } from './permissions';

export { PROPERTY_STORAGE_KEY, setActivePropertyId } from './activeProperty';

/** The property the user is working in, and their membership (role) there. */
export function useActiveMembership(): Membership | undefined {
  const { data: user } = useCurrentUser();
  const preferred = useSyncExternalStore(subscribeActiveProperty, activePropertyId);
  return user ? pickMembership(user.memberships, preferred) : undefined;
}

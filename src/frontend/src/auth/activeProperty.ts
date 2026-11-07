// The property the user is working in, kept in localStorage and shared by every
// component in this tab. useActiveMembership() turns it into a membership.

export const PROPERTY_STORAGE_KEY = 'domus.propertyId';

const listeners = new Set<() => void>();
// Used when storage is unavailable (private mode), so a switch lasts until reload.
let fallbackPropertyId: string | null = null;

export function subscribeActiveProperty(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function activePropertyId(): string | null {
  try {
    return window.localStorage.getItem(PROPERTY_STORAGE_KEY) ?? fallbackPropertyId;
  } catch {
    return fallbackPropertyId;
  }
}

/** Switch the property the user is working in, and remember it for next time. */
export function setActivePropertyId(propertyId: string): void {
  try {
    window.localStorage.setItem(PROPERTY_STORAGE_KEY, propertyId);
  } catch {
    fallbackPropertyId = propertyId; // storage unavailable: remember it for this tab only
  }
  listeners.forEach((listener) => listener());
}

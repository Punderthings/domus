// Display words and rules for the Home Assistant import preview.

import type { HaDeviceChoice, HaDevicePlan } from './api/types';
import { terms } from './terms';

export type Action = HaDeviceChoice['action'];

export const STATUS_LABELS: Record<HaDevicePlan['status'], { label: string; color: string }> = {
  new: { label: 'New', color: 'green' },
  matched: { label: 'Match found', color: 'blue' },
  linked: { label: 'Up to date', color: 'gray' },
  changed: { label: 'Updated in HA', color: 'yellow' },
  ignored: { label: 'Ignored', color: 'gray' },
};

export const REASON_LABELS: Record<NonNullable<HaDevicePlan['match_reason']>, string> = {
  ha_device_id: 'already linked',
  connection: 'same network address',
  serial: 'same serial number',
  name: 'similar name in the same Area',
};

export const ACTION_LABELS: Record<Action, string> = {
  create: `Add as a new ${terms.device.toLowerCase()}`,
  link: 'Link to the match',
  skip: 'Skip',
};

/** The actions that make sense for a device in the preview. */
export function actionsFor(device: HaDevicePlan): Action[] {
  if (!device.can_apply) return ['skip'];
  if (device.status === 'new' || device.status === 'ignored') return ['create', 'skip'];
  if (device.status === 'matched') return ['link', 'create', 'skip'];
  return ['link', 'skip'];
}

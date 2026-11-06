// Display helpers. Dates from the API are ISO strings; plain dates (YYYY-MM-DD)
// are calendar days in the property's time zone, so they're shown without a
// time zone shift.

const PLAIN_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

export function parseDay(value: string): Date {
  const match = PLAIN_DATE.exec(value);
  if (match) return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return new Date(value);
}

export function formatDate(value: string | null | undefined, locale?: string): string {
  if (!value) return '—';
  const date = parseDay(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(date);
}

/** Today's date as YYYY-MM-DD in local time, plus an optional number of days. */
export function isoDay(offsetDays = 0, now: Date = new Date()): string {
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offsetDays);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

export type DueState = 'overdue' | 'due' | 'upcoming' | 'none';

/** Overdue before today; due within the task's lead days; upcoming otherwise. */
export function dueState(
  nextDue: string | null,
  leadDays: number | null,
  now: Date = new Date(),
): DueState {
  if (!nextDue) return 'none';
  const today = isoDay(0, now);
  if (nextDue < today) return 'overdue';
  if (nextDue <= isoDay(leadDays ?? 0, now)) return 'due';
  return 'upcoming';
}

/** Money arrives from the API as a decimal string such as "49.99". */
export function formatMoney(
  amount: string | number | null | undefined,
  currency = 'USD',
  locale?: string,
): string {
  if (amount === null || amount === undefined || amount === '') return '—';
  const value = typeof amount === 'number' ? amount : Number(amount);
  if (!Number.isFinite(value)) return String(amount);
  return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value);
}

/** "appliance" -> "Appliance", "pool_house" -> "Pool house". */
export function humanize(value: string | null | undefined): string {
  if (!value) return '—';
  const text = value.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Only http(s) links are rendered as links, so stored data can't inject javascript: URLs. */
export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
  } catch {
    return null;
  }
}

/** The property's time zone starts as the browser's; an Admin can change it later. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

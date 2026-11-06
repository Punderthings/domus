import { describe, expect, it } from 'vitest';
import {
  dueState,
  formatDate,
  formatMoney,
  humanize,
  isoDay,
  parseDay,
  safeHttpUrl,
} from './format';

const now = new Date(2026, 10, 6, 15, 30); // 6 Nov 2026, local time

describe('dates', () => {
  it('parses plain dates as local calendar days', () => {
    const day = parseDay('2027-03-01');
    expect([day.getFullYear(), day.getMonth(), day.getDate()]).toEqual([2027, 2, 1]);
  });
  it('formats dates and handles empty or bad values', () => {
    expect(formatDate('2027-03-01', 'en-US')).toBe('Mar 1, 2027');
    expect(formatDate(null)).toBe('—');
    expect(formatDate('not a date')).toBe('not a date');
  });
  it('computes ISO days across month and year ends', () => {
    expect(isoDay(0, now)).toBe('2026-11-06');
    expect(isoDay(25, now)).toBe('2026-12-01');
    expect(isoDay(56, now)).toBe('2027-01-01');
  });
});

describe('dueState', () => {
  it('classifies tasks by next due date and lead days', () => {
    expect(dueState('2026-11-01', 7, now)).toBe('overdue');
    expect(dueState('2026-11-06', 0, now)).toBe('due');
    expect(dueState('2026-11-10', 7, now)).toBe('due');
    expect(dueState('2026-11-20', 7, now)).toBe('upcoming');
    expect(dueState('2026-11-07', null, now)).toBe('upcoming');
    expect(dueState(null, 7, now)).toBe('none');
  });
});

describe('formatMoney and humanize', () => {
  it('formats currency', () => {
    expect(formatMoney(1899, 'USD', 'en-US')).toBe('$1,899.00');
    expect(formatMoney('49.99', 'USD', 'en-US')).toBe('$49.99');
    expect(formatMoney(undefined)).toBe('—');
    expect(formatMoney('n/a')).toBe('n/a');
  });
  it('turns enum values into labels', () => {
    expect(humanize('pool_house')).toBe('Pool house');
    expect(humanize('')).toBe('—');
  });
});

describe('safeHttpUrl', () => {
  it('allows http and https links', () => {
    expect(safeHttpUrl('https://example.com/m.pdf')).toBe('https://example.com/m.pdf');
    expect(safeHttpUrl('http://192.168.1.10/manual')).toBe('http://192.168.1.10/manual');
  });
  it('rejects script and other schemes, and junk', () => {
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull();
    expect(safeHttpUrl('JAVASCRIPT:alert(1)')).toBeNull();
    expect(safeHttpUrl('data:text/html,hi')).toBeNull();
    expect(safeHttpUrl('not a url')).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
  });
});

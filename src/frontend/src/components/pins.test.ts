import { describe, expect, it } from 'vitest';
import { clamp01, fitToWidth, roundPosition, toNormalized, toPixels } from './pins';

describe('pin geometry', () => {
  it('clamps to the image', () => {
    expect(clamp01(-0.2)).toBe(0);
    expect(clamp01(1.5)).toBe(1);
    expect(clamp01(0.3)).toBe(0.3);
    expect(clamp01(Number.NaN)).toBe(0);
  });

  it('fits an image to a width without scaling up', () => {
    expect(fitToWidth({ width: 2000, height: 1000 }, 800)).toEqual({ width: 800, height: 400 });
    expect(fitToWidth({ width: 400, height: 300 }, 800)).toEqual({ width: 400, height: 300 });
    expect(fitToWidth({ width: 0, height: 300 }, 800)).toEqual({ width: 0, height: 0 });
  });

  it('round-trips between pixels and 0-1 positions', () => {
    const drawn = { width: 800, height: 400 };
    expect(toNormalized({ x: 200, y: 100 }, drawn)).toEqual({ x: 0.25, y: 0.25 });
    expect(toPixels({ x: 0.25, y: 0.25 }, drawn)).toEqual({ x: 200, y: 100 });
    expect(toNormalized({ x: -5, y: 900 }, drawn)).toEqual({ x: 0, y: 1 });
    expect(toNormalized({ x: 5, y: 5 }, { width: 0, height: 0 })).toEqual({ x: 0, y: 0 });
  });

  it('keeps the same spot when the image is replaced at another size', () => {
    const stored = toNormalized({ x: 300, y: 150 }, { width: 600, height: 300 });
    expect(toPixels(stored, { width: 1200, height: 600 })).toEqual({ x: 600, y: 300 });
  });

  it('rounds to four decimals', () => {
    expect(roundPosition({ x: 0.123456, y: 0.99999 })).toEqual({ x: 0.1235, y: 1 });
  });
});

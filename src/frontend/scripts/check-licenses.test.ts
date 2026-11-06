import { describe, expect, it } from 'vitest';
// @ts-expect-error plain JavaScript module without type declarations
import { ALLOWED, checkLockfile, isAllowed } from './check-licenses.mjs';

describe('isAllowed', () => {
  it('accepts Category A ids and rejects others', () => {
    expect(isAllowed('MIT', ALLOWED)).toBe(true);
    expect(isAllowed('MPL-2.0', ALLOWED)).toBe(false);
    expect(isAllowed('CC-BY-4.0', ALLOWED)).toBe(false);
    expect(isAllowed('GPL-3.0-only', ALLOWED)).toBe(false);
    expect(isAllowed(undefined, ALLOWED)).toBe(false);
  });
  it('handles OR and AND expressions', () => {
    expect(isAllowed('(MIT OR CC0-1.0)', ALLOWED)).toBe(true);
    expect(isAllowed('(MPL-2.0 OR Apache-2.0)', ALLOWED)).toBe(true);
    expect(isAllowed('Apache-2.0 AND MIT', ALLOWED)).toBe(true);
    expect(isAllowed('MIT AND LGPL-3.0', ALLOWED)).toBe(false);
  });
});

describe('checkLockfile', () => {
  it('reports bad and missing licenses, including dev tools, and skips the root', () => {
    const problems = checkLockfile({
      packages: {
        '': { license: 'Apache-2.0' },
        'node_modules/good': { version: '1.0.0', license: 'MIT' },
        'node_modules/other-mpl': { version: '1.0.0', license: 'MPL-2.0', dev: true },
        'node_modules/a/node_modules/nolicense': { version: '2.0.0' },
      },
    });
    expect(problems).toEqual([
      'other-mpl@1.0.0: MPL-2.0 (dev)',
      'nolicense@2.0.0: no license field (runtime)',
    ]);
  });

  it('allows lightningcss only as a build-only dev dependency under MPL-2.0', () => {
    const lock = (info: object) => ({
      packages: { 'node_modules/lightningcss': { version: '1.33.0', ...info } },
    });
    expect(checkLockfile(lock({ license: 'MPL-2.0', dev: true }))).toEqual([]);
    expect(
      checkLockfile({
        packages: {
          'node_modules/lightningcss-linux-x64-gnu': {
            version: '1.33.0',
            license: 'MPL-2.0',
            dev: true,
          },
        },
      }),
    ).toEqual([]);
    expect(checkLockfile(lock({ license: 'MPL-2.0' }))).toEqual([
      'lightningcss@1.33.0: MPL-2.0 (runtime)',
    ]);
    expect(checkLockfile(lock({ license: 'GPL-3.0', dev: true }))).toEqual([
      'lightningcss@1.33.0: GPL-3.0 (dev)',
    ]);
    expect(
      checkLockfile({
        packages: {
          'node_modules/lightningcss-evil': { version: '1', license: 'MPL-2.0', dev: true },
        },
      }),
    ).toEqual(['lightningcss-evil@1: MPL-2.0 (dev)']);
  });
});

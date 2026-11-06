// Fail if any npm package in package-lock.json uses a license outside our allowlist.
//
// AGENTS.md requires dependencies to use licenses on the ASF Category A list:
// https://www.apache.org/legal/resolved.html#category-a
// This mirrors scripts/check_licenses.py for the Python side. It reads only the
// lockfile, so it never touches the network and needs no extra dependency.
// This covers build, lint, and test tools too, not only what ships in the app.
// Adding to the list below needs a maintainer's review.
//
// Usage: node scripts/check-licenses.mjs [path/to/package-lock.json]

import { readFileSync } from 'node:fs';

/** SPDX ids from the ASF Category A list. */
export const ALLOWED = new Set([
  '0BSD',
  'Apache-2.0',
  'BlueOak-1.0.0',
  'BSD-2-Clause',
  'BSD-3-Clause',
  'ISC',
  'MIT',
  'MIT-0',
  'Python-2.0',
  'Unlicense',
  'Zlib',
]);

/**
 * Build-only tools allowed under a non-Category-A license, by package name, with
 * the one license accepted for each. They must be dev dependencies that never
 * end up in the built app. Decision 20 (Shane, 2026-11-06): Vite 8 needs
 * lightningcss (MPL-2.0) and its per-platform binaries.
 */
export const BUILD_ONLY_EXCEPTIONS = [
  { name: /^lightningcss(-(android|darwin|freebsd|linux|win32)-[a-z0-9-]+)?$/, license: 'MPL-2.0' },
];

function isBuildOnlyException(name, info) {
  return (
    info.dev === true &&
    BUILD_ONLY_EXCEPTIONS.some((rule) => rule.name.test(name) && rule.license === info.license)
  );
}

/** Return true if an SPDX expression is satisfied by the allowed set. */
export function isAllowed(expression, allowed) {
  const text = String(expression ?? '').trim();
  if (!text) return false;
  const stripped = text.replace(/^\((.*)\)$/, '$1').trim();
  if (/\s+OR\s+/.test(stripped)) {
    return stripped.split(/\s+OR\s+/).some((part) => isAllowed(part, allowed));
  }
  if (/\s+AND\s+/.test(stripped)) {
    return stripped.split(/\s+AND\s+/).every((part) => isAllowed(part, allowed));
  }
  return allowed.has(stripped);
}

/** Return a list of problem strings for a parsed package-lock.json. */
export function checkLockfile(lock) {
  const problems = [];
  for (const [path, info] of Object.entries(lock.packages ?? {})) {
    if (path === '') continue; // the project itself
    const name = path.replace(/^.*node_modules\//, '');
    if (!isAllowed(info.license, ALLOWED) && !isBuildOnlyException(name, info)) {
      const scope = info.dev ? 'dev' : 'runtime';
      problems.push(`${name}@${info.version}: ${info.license ?? 'no license field'} (${scope})`);
    }
  }
  return problems;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const file = process.argv[2] ?? new URL('../package-lock.json', import.meta.url);
  const problems = checkLockfile(JSON.parse(readFileSync(file, 'utf8')));
  if (problems.length) {
    console.error('Licenses outside the allowlist:\n  ' + problems.join('\n  '));
    process.exit(1);
  }
  console.log('All npm package licenses are on the allowlist.');
}

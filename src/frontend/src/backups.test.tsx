// The Admin backup screen, against the in-memory fake API.
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { Role } from './api/types';
import { formatBytes } from './format';
import { PROPERTY_ID, areas, buildings, floors, property, user } from './test/fixtures';
import { renderApp } from './test/render';
import { fakeApi, page } from './test/server';

const OLD = {
  name: 'domus-20261101T000000Z.hiotbak',
  size_bytes: 2_500_000,
  modified_at: '2026-11-01T00:00:00Z',
};
const NEW = {
  name: 'domus-20261107T000000Z.hiotbak',
  size_bytes: 3_000,
  modified_at: '2026-11-07T00:00:00Z',
  missing_files: 0,
};

function api(role: Role, backupsStatus = 200) {
  let made = false;
  return fakeApi({
    'GET /auth/setup': () => ({ body: { needs_setup: false } }),
    'GET /auth/me': () => ({ body: user(role) }),
    [`GET /properties/${PROPERTY_ID}`]: () => ({ body: property }),
    'GET /buildings': () => ({ body: page(buildings) }),
    'GET /floors': () => ({ body: page(floors) }),
    'GET /areas': () => ({ body: page(areas) }),
    'GET /maintenance/tasks': () => ({ body: page([]) }),
    'GET /backups': () =>
      backupsStatus === 200
        ? { body: page(made ? [NEW, OLD] : [OLD]) }
        : { status: backupsStatus, body: { detail: 'Forbidden' } },
    'POST /backups': () => {
      made = true;
      return { status: 201, body: NEW };
    },
  });
}

describe('backups', () => {
  it('shows the Backups link to admins only', async () => {
    api('admin');
    const first = renderApp('/');
    expect(await screen.findByRole('link', { name: 'Backups' })).toHaveAttribute(
      'href',
      '/admin/backups',
    );
    first.unmount();
    api('maintainer');
    renderApp('/');
    await screen.findByRole('link', { name: 'Devices' });
    expect(screen.queryByRole('link', { name: 'Backups' })).not.toBeInTheDocument();
  });

  it('lists backups with download links and makes a new one', async () => {
    const { calls } = api('admin');
    renderApp('/admin/backups');
    expect(await screen.findByText(OLD.name)).toBeInTheDocument();
    expect(screen.getByText('2.4 MB')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: `Download ${OLD.name}` })).toHaveAttribute(
      'href',
      `/api/v1/backups/${OLD.name}`,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Make a backup now' }));
    expect(await screen.findByText(`Backup ${NEW.name} saved.`)).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByRole('link', { name: /^Download/ })).toHaveLength(2));
    const post = calls.find((c) => c.method === 'POST' && c.path === '/backups');
    expect(post?.headers['accept']).toBe('application/json');
  });

  it('explains why an admin of only some properties is refused', async () => {
    api('admin', 403);
    renderApp('/admin/backups');
    expect(
      await screen.findByText(/only someone who is an Admin of all of them/),
    ).toBeInTheDocument();
  });

  it('does not call the API for non-admins, and still shows the restore commands', async () => {
    const { calls } = api('resident');
    renderApp('/admin/backups');
    expect(
      await screen.findByText('Only Admins can make or download backups.'),
    ).toBeInTheDocument();
    expect(screen.getByText('domus restore --merge --dry-run FILE.hiotbak')).toBeInTheDocument();
    expect(calls.some((c) => c.path === '/backups')).toBe(false);
  });
});

describe('formatBytes', () => {
  it.each([
    [0, '0 bytes'],
    [1023, '1023 bytes'],
    [1536, '1.5 KB'],
    [5 * 1024 ** 3, '5.0 GB'],
  ])('%d -> %s', (bytes, text) => {
    expect(formatBytes(bytes)).toBe(text);
  });
});

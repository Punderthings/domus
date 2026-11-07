// Hooks that change data: device add/edit and marking maintenance done. Kept apart
// from queries.ts so read and write code are easy to review separately.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, unwrap } from './client';
import { keys } from './queries';
import type { components } from './schema';
import type { MaintenanceTask, Page } from './types';

type Schemas = components['schemas'];
export type AssetInput = Schemas['AssetIn'];
export type AssetUpdateInput = Schemas['AssetUpdate'];
export type ProductInput = Schemas['ProductIn'];
export type LocationInput = Schemas['LocationIn'];
export type CompleteInput = Schemas['CompleteIn'];

export const mutationKeys = {
  locations: (areaId: string) => ['locations', { areaId }] as const,
};

/** The places (wall, cabinet, closet...) inside one area. */
export function useLocations(areaId: string | null | undefined) {
  return useQuery({
    queryKey: mutationKeys.locations(areaId ?? ''),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/locations', {
          params: { query: { area_id: areaId ?? '', limit: 200 } },
          signal,
        }),
      ),
    enabled: Boolean(areaId),
  });
}

export function useCreateLocation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: LocationInput) => unwrap(api.POST('/api/v1/locations', { body })),
    onSuccess: (location) =>
      client.invalidateQueries({ queryKey: mutationKeys.locations(location.area_id) }),
  });
}

export function useCreateProduct(propertyId: string | undefined) {
  return useMutation({
    mutationFn: (body: ProductInput) =>
      unwrap(
        api.POST('/api/v1/products', { params: { query: { property_id: propertyId } }, body }),
      ),
  });
}

export function useCreateAsset() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AssetInput) => unwrap(api.POST('/api/v1/assets', { body })),
    onSuccess: async (asset) => {
      client.setQueryData(keys.asset(asset.id), asset);
      await client.invalidateQueries({ queryKey: ['assets'] });
    },
  });
}

export function useUpdateAsset(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AssetUpdateInput) =>
      unwrap(api.PATCH('/api/v1/assets/{asset_id}', { params: { path: { asset_id: id } }, body })),
    onSuccess: async (asset) => {
      client.setQueryData(keys.asset(asset.id), asset);
      await client.invalidateQueries({ queryKey: ['assets'] });
    },
  });
}

/** Replace one task in every cached task list, so the new due date shows at once. */
function replaceTask(client: ReturnType<typeof useQueryClient>, updated: MaintenanceTask) {
  client.setQueriesData<Page<MaintenanceTask>>({ queryKey: ['tasks'] }, (page) =>
    page ? { ...page, items: page.items.map((t) => (t.id === updated.id ? updated : t)) } : page,
  );
}

/** Log work on a task ("mark done"); the server reschedules it and returns the new task. */
export function useCompleteTask() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, body }: { taskId: string; body: CompleteInput }) =>
      unwrap(
        api.POST('/api/v1/maintenance/tasks/{task_id}/complete', {
          params: { path: { task_id: taskId } },
          body,
        }),
      ),
    onSuccess: async (result) => {
      replaceTask(client, result.task);
      await client.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
}

export type Backup = Schemas['BackupOut'];

export const backupKeys = { all: ['backups'] as const };

/** Backups in the server's data folder (Admins of every property only). */
export function useBackups(enabled: boolean) {
  return useQuery({
    queryKey: backupKeys.all,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/backups', { signal })),
    enabled,
    retry: false,
  });
}

export function useCreateBackup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/backups')),
    onSuccess: () => client.invalidateQueries({ queryKey: backupKeys.all }),
  });
}

/** Where the browser downloads a backup; the session cookie authorizes it. */
export function backupDownloadUrl(name: string): string {
  return `/api/v1/backups/${encodeURIComponent(name)}`;
}

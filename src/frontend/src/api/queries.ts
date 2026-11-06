// TanStack Query hooks for each API resource, so pages never build URLs themselves.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, api, unwrap } from './client';
import type { HaApplyInput, HaConnectInput, LoginInput, SetupInput } from './types';

export type { LoginInput, SetupInput };

/** The API's largest page size; v0.1 views show one page per list. */
const LIMIT = 200;

export const keys = {
  me: ['auth', 'me'] as const,
  setup: ['auth', 'setup'] as const,
  property: (id: string) => ['properties', id] as const,
  buildings: (propertyId: string) => ['buildings', { propertyId }] as const,
  floors: (buildingId: string) => ['floors', { buildingId }] as const,
  areas: (propertyId: string) => ['areas', { propertyId }] as const,
  assets: (propertyId: string, filters: AssetFilters) =>
    ['assets', { propertyId, ...filters }] as const,
  asset: (id: string) => ['assets', id] as const,
  tasks: (propertyId: string, filters: TaskFilters) =>
    ['tasks', { propertyId, ...filters }] as const,
};

/** The signed-in user, or null when not signed in (401). */
export function useCurrentUser() {
  return useQuery({
    queryKey: keys.me,
    queryFn: async ({ signal }) => {
      try {
        return await unwrap(api.GET('/api/v1/auth/me', { signal }));
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 60_000,
  });
}

export function useSetupStatus() {
  return useQuery({
    queryKey: keys.setup,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/auth/setup', { signal })),
    staleTime: Infinity,
  });
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: LoginInput) => unwrap(api.POST('/api/v1/auth/login', { body })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.me }),
  });
}

export function useSetup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: SetupInput) => unwrap(api.POST('/api/v1/auth/setup', { body })),
    onSuccess: async () => {
      client.setQueryData(keys.setup, { needs_setup: false });
      await client.invalidateQueries({ queryKey: keys.me });
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/auth/logout')),
    onSettled: () => {
      client.clear();
      client.setQueryData(keys.me, null);
    },
  });
}

export function useProperty(id: string | undefined) {
  return useQuery({
    queryKey: keys.property(id ?? ''),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/properties/{property_id}', {
          params: { path: { property_id: id ?? '' } },
          signal,
        }),
      ),
    enabled: Boolean(id),
  });
}

export function useBuildings(propertyId: string | undefined) {
  return useQuery({
    queryKey: keys.buildings(propertyId ?? ''),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/buildings', {
          params: { query: { property_id: propertyId, limit: LIMIT } },
          signal,
        }),
      ),
    enabled: Boolean(propertyId),
  });
}

export function useFloors(buildingId: string | undefined) {
  return useQuery({
    queryKey: keys.floors(buildingId ?? ''),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/floors', {
          params: { query: { building_id: buildingId ?? '', limit: LIMIT } },
          signal,
        }),
      ),
    enabled: Boolean(buildingId),
  });
}

export function useAreas(propertyId: string | undefined) {
  return useQuery({
    queryKey: keys.areas(propertyId ?? ''),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/areas', {
          params: { query: { property_id: propertyId, limit: LIMIT } },
          signal,
        }),
      ),
    enabled: Boolean(propertyId),
  });
}

export interface AssetFilters {
  area_id?: string;
  q?: string;
}

export function useAssets(propertyId: string | undefined, filters: AssetFilters = {}) {
  return useQuery({
    queryKey: keys.assets(propertyId ?? '', filters),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/assets', {
          params: { query: { property_id: propertyId, limit: LIMIT, ...filters } },
          signal,
        }),
      ),
    enabled: Boolean(propertyId),
  });
}

export function useAsset(id: string) {
  return useQuery({
    queryKey: keys.asset(id),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/assets/{asset_id}', { params: { path: { asset_id: id } }, signal })),
  });
}

export interface TaskFilters {
  asset_id?: string;
  due_before?: string;
  active?: boolean;
}

export function useTasks(propertyId: string | undefined, filters: TaskFilters = {}) {
  return useQuery({
    queryKey: keys.tasks(propertyId ?? '', filters),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/maintenance/tasks', {
          params: { query: { property_id: propertyId, limit: LIMIT, ...filters } },
          signal,
        }),
      ),
    enabled: Boolean(propertyId),
  });
}

/** Read Home Assistant's registries and show what an import would do. Changes nothing. */
export function useHaPreview() {
  return useMutation({
    mutationFn: (body: HaConnectInput) =>
      unwrap(api.POST('/api/v1/homeassistant/preview', { body })),
  });
}

/** Apply a Home Assistant import, then refresh everything it may have added. */
export function useHaApply() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: HaApplyInput) => unwrap(api.POST('/api/v1/homeassistant/apply', { body })),
    onSuccess: async () => {
      await Promise.all(
        ['assets', 'areas', 'floors', 'buildings'].map((key) =>
          client.invalidateQueries({ queryKey: [key] }),
        ),
      );
    },
  });
}

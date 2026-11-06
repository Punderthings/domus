// TanStack Query hooks for each API resource, so pages never build URLs themselves.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, apiRequest } from './client';
import type {
  Area,
  Asset,
  AssetDetail,
  Building,
  CurrentUser,
  Floor,
  MaintenanceTask,
  Page,
  Property,
  SetupStatus,
} from './types';

export const keys = {
  me: ['auth', 'me'] as const,
  setup: ['auth', 'setup'] as const,
  properties: ['properties'] as const,
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
        return await apiRequest<CurrentUser>('/auth/me', { signal });
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
    queryFn: ({ signal }) => apiRequest<SetupStatus>('/auth/setup', { signal }),
    staleTime: Infinity,
  });
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface SetupInput extends LoginInput {
  display_name: string;
  property_name: string;
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: LoginInput) =>
      apiRequest<undefined>('/auth/login', { method: 'POST', body: input }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.me }),
  });
}

export function useSetup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: SetupInput) =>
      apiRequest<undefined>('/auth/setup', { method: 'POST', body: input }),
    onSuccess: async () => {
      client.setQueryData(keys.setup, { needs_setup: false });
      await client.invalidateQueries({ queryKey: keys.me });
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<undefined>('/auth/logout', { method: 'POST' }),
    onSettled: () => {
      client.clear();
      client.setQueryData(keys.me, null);
    },
  });
}

export function useProperties() {
  return useQuery({
    queryKey: keys.properties,
    queryFn: ({ signal }) => apiRequest<Page<Property>>('/properties', { signal }),
  });
}

export function useProperty(id: string | undefined) {
  return useQuery({
    queryKey: keys.property(id ?? ''),
    queryFn: ({ signal }) =>
      apiRequest<Property>(`/properties/${encodeURIComponent(id ?? '')}`, { signal }),
    enabled: Boolean(id),
  });
}

export function useBuildings(propertyId: string | undefined) {
  return useQuery({
    queryKey: keys.buildings(propertyId ?? ''),
    queryFn: ({ signal }) =>
      apiRequest<Page<Building>>('/buildings', {
        params: { property_id: propertyId, limit: 200 },
        signal,
      }),
    enabled: Boolean(propertyId),
  });
}

export function useFloors(buildingId: string | undefined) {
  return useQuery({
    queryKey: keys.floors(buildingId ?? ''),
    queryFn: ({ signal }) =>
      apiRequest<Page<Floor>>('/floors', {
        params: { building_id: buildingId, limit: 200 },
        signal,
      }),
    enabled: Boolean(buildingId),
  });
}

export function useAreas(propertyId: string | undefined) {
  return useQuery({
    queryKey: keys.areas(propertyId ?? ''),
    queryFn: ({ signal }) =>
      apiRequest<Page<Area>>('/areas', { params: { property_id: propertyId, limit: 200 }, signal }),
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
      apiRequest<Page<Asset>>('/assets', {
        params: { property_id: propertyId, limit: 200, ...filters },
        signal,
      }),
    enabled: Boolean(propertyId),
  });
}

export function useAsset(id: string) {
  return useQuery({
    queryKey: keys.asset(id),
    queryFn: ({ signal }) =>
      apiRequest<AssetDetail>(`/assets/${encodeURIComponent(id)}`, { signal }),
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
      apiRequest<Page<MaintenanceTask>>('/maintenance/tasks', {
        params: { property_id: propertyId, limit: 200, ...filters },
        signal,
      }),
    enabled: Boolean(propertyId),
  });
}

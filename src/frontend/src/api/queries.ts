// TanStack Query hooks for each API resource, so pages never build URLs themselves.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { setActivePropertyId } from '../auth/activeProperty';
import { ApiError, api, unwrap, uploadFile } from './client';
import type {
  CanvasKind,
  Document,
  HaApplyInput,
  HaConnectInput,
  LoginInput,
  Placement,
  SetupInput,
} from './types';

export type { LoginInput, SetupInput };

/** The API's largest page size; v0.1 views show one page per list. */
const LIMIT = 200;

export const keys = {
  me: ['auth', 'me'] as const,
  setup: ['auth', 'setup'] as const,
  properties: ['properties'] as const,
  property: (id: string) => ['properties', id] as const,
  sampleData: ['sample-data'] as const,
  buildings: (propertyId: string) => ['buildings', { propertyId }] as const,
  floors: (buildingId: string) => ['floors', { buildingId }] as const,
  areas: (propertyId: string) => ['areas', { propertyId }] as const,
  assets: (propertyId: string, filters: AssetFilters) =>
    ['assets', { propertyId, ...filters }] as const,
  asset: (id: string) => ['assets', id] as const,
  tasks: (propertyId: string, filters: TaskFilters) =>
    ['tasks', { propertyId, ...filters }] as const,
  floor: (id: string) => ['floors', id] as const,
  canvases: (propertyId: string, scopeId: string, kind: CanvasKind) =>
    ['canvases', { propertyId, scopeId, kind }] as const,
  placements: (canvasId: string) => ['placements', { canvasId }] as const,
  assetPlacements: (assetId: string) => ['placements', { assetId }] as const,
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

/** Every property the user is a member of (for the property switcher). */
export function useProperties(enabled = true) {
  return useQuery({
    queryKey: keys.properties,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/properties', { signal })),
    enabled,
  });
}

/** Whether an Admin can load the sample home. Ask only as an Admin; others get 403. */
export function useSampleDataStatus(enabled: boolean) {
  return useQuery({
    queryKey: keys.sampleData,
    queryFn: ({ signal }) => unwrap(api.GET('/api/v1/sample-data', { signal })),
    enabled,
  });
}

/** Add the sample home as a new property, then switch to it. */
export function useLoadSampleData() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/sample-data')),
    onSuccess: async (status) => {
      client.setQueryData(keys.sampleData, status);
      if (status.property_id) setActivePropertyId(status.property_id);
      await client.invalidateQueries();
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

export function useFloor(id: string) {
  return useQuery({
    queryKey: keys.floor(id),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/floors/{floor_id}', { params: { path: { floor_id: id } }, signal })),
  });
}

/** Canvases of one kind on one floor or area, for example the floor plan of a floor. */
export function useCanvases(
  propertyId: string | undefined,
  scope: { type: 'floor' | 'area' | 'building' | 'property'; id: string },
  kind: CanvasKind,
) {
  return useQuery({
    queryKey: keys.canvases(propertyId ?? '', scope.id, kind),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/canvases', {
          params: {
            query: {
              property_id: propertyId,
              scope_type: scope.type,
              scope_id: scope.id,
              kind,
              limit: LIMIT,
            },
          },
          signal,
        }),
      ),
    enabled: Boolean(propertyId),
  });
}

export function usePlacements(canvasId: string) {
  return useQuery({
    queryKey: keys.placements(canvasId),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET('/api/v1/canvases/{canvas_id}/placements', {
          params: { path: { canvas_id: canvasId } },
          signal,
        }),
      ),
  });
}

/** Where one device is pinned, on the floor plans and photos the user can see. */
export function useAssetPlacements(assetId: string) {
  return useQuery({
    queryKey: keys.assetPlacements(assetId),
    queryFn: ({ signal }) =>
      unwrap(api.GET('/api/v1/placements', { params: { query: { asset_id: assetId } }, signal })),
  });
}

export interface NewCanvas {
  propertyId: string;
  scope: { type: 'floor' | 'area'; id: string };
  kind: CanvasKind;
  name?: string;
  file: File;
}

/** Upload an image and make it a new canvas. */
export function useCreateCanvas() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ propertyId, scope, kind, name, file }: NewCanvas) => {
      const doc = await uploadFile<Document>('/api/v1/documents', file, {
        property_id: propertyId,
        kind,
        filename: file.name,
        title: name,
        // Anyone who can see the floor or area can see its plan or photo.
        sensitivity: 'guest',
      });
      return unwrap(
        api.POST('/api/v1/canvases', {
          body: {
            property_id: propertyId,
            document_id: doc.id,
            scope_type: scope.type,
            scope_id: scope.id,
            kind,
            name: name || null,
          },
        }),
      );
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ['canvases'] }),
  });
}

/** Upload a new image for an existing canvas. Pins keep their 0-1 positions. */
export function useReplaceCanvasImage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      canvasId,
      propertyId,
      kind,
      file,
    }: {
      canvasId: string;
      propertyId: string;
      kind: CanvasKind;
      file: File;
    }) => {
      const doc = await uploadFile<Document>('/api/v1/documents', file, {
        property_id: propertyId,
        kind,
        filename: file.name,
        sensitivity: 'guest',
      });
      return unwrap(
        api.PATCH('/api/v1/canvases/{canvas_id}', {
          params: { path: { canvas_id: canvasId } },
          body: { document_id: doc.id },
        }),
      );
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ['canvases'] }),
  });
}

export function useDeleteCanvas() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (canvasId: string) =>
      unwrap(
        api.DELETE('/api/v1/canvases/{canvas_id}', { params: { path: { canvas_id: canvasId } } }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ['canvases'] }),
  });
}

export function useAddPin(canvasId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { asset_id: string; x: number; y: number }) =>
      unwrap(api.POST('/api/v1/placements', { body: { canvas_id: canvasId, ...body } })),
    onSuccess: () => client.invalidateQueries({ queryKey: ['placements'] }),
  });
}

/** Move a pin, updating the cached list first so the pin does not jump back while saving. */
export function useMovePin(canvasId: string) {
  const client = useQueryClient();
  const key = keys.placements(canvasId);
  return useMutation({
    mutationFn: ({ id, x, y }: { id: string; x: number; y: number }) =>
      unwrap(
        api.PATCH('/api/v1/placements/{placement_id}', {
          params: { path: { placement_id: id } },
          body: { x, y },
        }),
      ),
    onMutate: async ({ id, x, y }) => {
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<{ items: Placement[] }>(key);
      if (previous)
        client.setQueryData(key, {
          ...previous,
          items: previous.items.map((p) => (p.id === id ? { ...p, x, y } : p)),
        });
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(key, context.previous);
    },
    onSettled: () => client.invalidateQueries({ queryKey: ['placements'] }),
  });
}

export function useRemovePin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE('/api/v1/placements/{placement_id}', {
          params: { path: { placement_id: id } },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: ['placements'] }),
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

// One floor plan or wall photo with its device pins: view, drag, place, and remove.
// The pin list under the image is the keyboard and screen reader way to reach every pin.

import { Button, FileButton, Group, Select, Stack, Text } from '@mantine/core';
import { useNavigate } from '@tanstack/react-router';
import { Suspense, lazy, useState } from 'react';
import {
  useAddPin,
  useDeleteCanvas,
  useMovePin,
  usePlacements,
  useRemovePin,
  useReplaceCanvasImage,
} from '../api/queries';
import type { Asset, Canvas, CanvasKind } from '../api/types';
import { allows } from '../auth/permissions';
import { terms } from '../terms';
import { AnchorLink } from './links';
import { roundPosition } from './pins';
import { ErrorNotice, PageLoader } from './States';

// Konva is loaded only on pages that show a plan or photo, keeping it out of the main bundle.
const PinCanvas = lazy(() => import('./PinCanvas').then((m) => ({ default: m.PinCanvas })));

export const IMAGE_ACCEPT = 'image/jpeg,image/png,image/webp,image/gif';

interface Props {
  canvas: Canvas;
  /** Devices that may be pinned here, for example those on this floor. */
  devices: Asset[];
  alt: string;
}

export function CanvasEditor({ canvas, devices, alt }: Props) {
  const navigate = useNavigate();
  const placements = usePlacements(canvas.id);
  const addPin = useAddPin(canvas.id);
  const movePin = useMovePin(canvas.id);
  const removePin = useRemovePin();
  const replace = useReplaceCanvasImage();
  const remove = useDeleteCanvas();
  const [editing, setEditing] = useState(false);
  const [placing, setPlacing] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const canEdit = allows(canvas.access, 'manage');

  if (placements.isPending) return <PageLoader />;
  if (placements.isError) return <ErrorNotice error={placements.error} />;
  const pins = placements.data.items;
  const pinned = new Set(pins.map((p) => p.asset_id));
  const unpinned = devices
    .filter((d) => !pinned.has(d.id))
    .sort((a, b) => a.name.localeCompare(b.name));
  const error = addPin.error ?? movePin.error ?? removePin.error ?? replace.error ?? remove.error;

  const place = (x: number, y: number) => {
    if (!placing) return;
    addPin.mutate({ asset_id: placing, ...roundPosition({ x, y }) });
    setPlacing(null);
  };

  return (
    <Stack gap="sm">
      {canEdit && (
        <Group gap="xs">
          <Button
            variant={editing ? 'filled' : 'default'}
            size="xs"
            onClick={() => {
              setEditing(!editing);
              setPlacing(null);
            }}
          >
            {editing ? 'Done editing' : 'Edit pins'}
          </Button>
          <FileButton
            accept={IMAGE_ACCEPT}
            onChange={(file) =>
              file &&
              replace.mutate({
                canvasId: canvas.id,
                propertyId: canvas.property_id,
                kind: canvas.kind as CanvasKind,
                file,
              })
            }
          >
            {(props) => (
              <Button {...props} variant="default" size="xs" loading={replace.isPending}>
                Replace image
              </Button>
            )}
          </FileButton>
          <Button
            variant={confirmDelete ? 'filled' : 'subtle'}
            color="red"
            size="xs"
            loading={remove.isPending}
            onClick={() => (confirmDelete ? remove.mutate(canvas.id) : setConfirmDelete(true))}
            onBlur={() => setConfirmDelete(false)}
          >
            {confirmDelete ? 'Click again to delete' : 'Delete'}
          </Button>
        </Group>
      )}
      {editing && (
        <Group gap="xs" align="end">
          <Select
            label={`${terms.device} to place`}
            placeholder={
              unpinned.length ? 'Choose one' : `Every ${terms.device.toLowerCase()} is placed`
            }
            data={unpinned.map((d) => ({ value: d.id, label: d.name }))}
            value={placing}
            onChange={setPlacing}
            searchable
            clearable
            disabled={unpinned.length === 0}
            w={260}
          />
          <Button size="sm" variant="default" disabled={!placing} onClick={() => place(0.5, 0.5)}>
            Place in the middle
          </Button>
        </Group>
      )}
      {placing && (
        <Text size="sm">Click the image where it is, or place it in the middle and drag it.</Text>
      )}
      {error && <ErrorNotice error={error} />}
      <Suspense fallback={<PageLoader />}>
        <PinCanvas
          imageUrl={canvas.image_url}
          alt={alt}
          pins={pins.map((p) => ({ id: p.id, x: p.x, y: p.y, label: p.label ?? p.asset_name }))}
          editable={editing}
          placing={Boolean(placing)}
          onPlace={place}
          onPinMove={(id, x, y) => movePin.mutate({ id, ...roundPosition({ x, y }) })}
          onPinClick={(id) => {
            const pin = pins.find((p) => p.id === id);
            if (pin && !editing)
              void navigate({ to: '/devices/$deviceId', params: { deviceId: pin.asset_id } });
          }}
        />
      </Suspense>
      {pins.length === 0 ? (
        <Text size="sm" c="dimmed">
          No {terms.devices.toLowerCase()} placed yet.
        </Text>
      ) : (
        <Stack gap={4} component="ul" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {pins.map((p) => (
            <Group key={p.id} component="li" gap="xs">
              <AnchorLink to="/devices/$deviceId" params={{ deviceId: p.asset_id }}>
                {p.label ?? p.asset_name}
              </AnchorLink>
              {editing && (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color="red"
                  aria-label={`Remove pin for ${p.asset_name}`}
                  onClick={() => removePin.mutate(p.id)}
                >
                  Remove
                </Button>
              )}
            </Group>
          ))}
        </Stack>
      )}
    </Stack>
  );
}

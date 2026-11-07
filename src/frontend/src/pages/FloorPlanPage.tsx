import { Breadcrumbs, Stack, Text, Title } from '@mantine/core';
import { useParams } from '@tanstack/react-router';
import { useAreas, useAssets, useCanvases, useFloor } from '../api/queries';
import { allows, hasRole, toRole } from '../auth/permissions';
import { useActiveMembership } from '../auth/useActiveProperty';
import { CanvasEditor } from '../components/CanvasEditor';
import { AnchorLink } from '../components/links';
import { NewCanvasButton } from '../components/NewCanvasButton';
import { ErrorNotice, PageLoader } from '../components/States';
import { terms } from '../terms';

export function FloorPlanPage() {
  const { floorId } = useParams({ from: '/app/floors/$floorId' });
  const membership = useActiveMembership();
  const propertyId = membership?.property_id;
  const floor = useFloor(floorId);
  const plans = useCanvases(propertyId, { type: 'floor', id: floorId }, 'floor_plan');
  const areas = useAreas(propertyId);
  const devices = useAssets(propertyId);

  if (floor.isPending || plans.isPending || areas.isPending || devices.isPending)
    return <PageLoader />;
  const error = floor.error ?? plans.error ?? areas.error ?? devices.error;
  if (error) return <ErrorNotice error={error} />;

  // Devices on this floor can be pinned; the device's area says which floor it is on.
  const floorAreas = new Set(
    (areas.data?.items ?? []).filter((a) => a.floor_id === floorId).map((a) => a.id),
  );
  const onFloor = (devices.data?.items ?? []).filter((d) => d.area_id && floorAreas.has(d.area_id));
  const plan = plans.data?.items[0];
  const canAdd =
    hasRole(membership && toRole(membership.role), 'maintainer') &&
    allows(floor.data?.access, 'manage');

  return (
    <Stack>
      <Breadcrumbs>
        <AnchorLink to="/">Overview</AnchorLink>
        <Text>{floor.data?.name}</Text>
      </Breadcrumbs>
      <Title order={2}>{floor.data?.name} floor plan</Title>
      {plan ? (
        <CanvasEditor canvas={plan} devices={onFloor} alt={`Floor plan of ${floor.data?.name}`} />
      ) : (
        <Stack gap="xs" align="start">
          <Text c="dimmed">
            No floor plan yet.{' '}
            {canAdd
              ? `Upload a photo or drawing of this floor, then place each ${terms.device.toLowerCase()} on it.`
              : 'A Maintainer or Admin can add one.'}
          </Text>
          {canAdd && propertyId && (
            <NewCanvasButton
              propertyId={propertyId}
              scope={{ type: 'floor', id: floorId }}
              kind="floor_plan"
              label="Upload floor plan"
            />
          )}
        </Stack>
      )}
    </Stack>
  );
}

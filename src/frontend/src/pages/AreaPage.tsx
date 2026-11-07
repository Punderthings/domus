import { AnchorLink } from '../components/links';
import { Badge, Breadcrumbs, Card, Group, Stack, Text, Title } from '@mantine/core';
import { useParams } from '@tanstack/react-router';
import { useAreas, useAssets, useCanvases } from '../api/queries';
import type { Area, Asset } from '../api/types';
import { allows, hasRole, toRole } from '../auth/permissions';
import { useActiveMembership } from '../auth/useActiveProperty';
import { CanvasEditor } from '../components/CanvasEditor';
import { DeviceTable } from '../components/DeviceTable';
import { NewCanvasButton } from '../components/NewCanvasButton';
import { ErrorNotice, PageLoader } from '../components/States';
import { humanize } from '../format';
import { terms } from '../terms';

function WallPhotos({ area, devices }: { area: Area; devices: Asset[] }) {
  const membership = useActiveMembership();
  const photos = useCanvases(area.property_id, { type: 'area', id: area.id }, 'wall_photo');
  const canAdd =
    hasRole(membership && toRole(membership.role), 'maintainer') && allows(area.access, 'manage');
  if (photos.isPending) return <PageLoader />;
  if (photos.isError) return <ErrorNotice error={photos.error} />;
  const items = photos.data.items;
  return (
    <Stack>
      <Title order={3}>Wall photos</Title>
      {items.length === 0 && (
        <Text c="dimmed">
          No wall photos yet. A photo of a wall with pins shows which switch or panel is which.
        </Text>
      )}
      {items.map((photo) => (
        <Card key={photo.id} withBorder>
          {photo.name && (
            <Title order={4} mb="xs">
              {photo.name}
            </Title>
          )}
          <CanvasEditor
            canvas={photo}
            devices={devices}
            alt={photo.name ?? `Wall photo in ${area.name}`}
          />
        </Card>
      ))}
      {canAdd && (
        <NewCanvasButton
          propertyId={area.property_id}
          scope={{ type: 'area', id: area.id }}
          kind="wall_photo"
          label="Add wall photo"
          askName
        />
      )}
    </Stack>
  );
}

export function AreaPage() {
  const { areaId } = useParams({ from: '/app/areas/$areaId' });
  const propertyId = useActiveMembership()?.property_id;
  const areas = useAreas(propertyId);
  const devices = useAssets(propertyId, { area_id: areaId });

  if (areas.isPending) return <PageLoader />;
  if (areas.isError) return <ErrorNotice error={areas.error} />;
  const area = areas.data.items.find((item) => item.id === areaId);
  if (!area)
    return (
      <Text>This {terms.area.toLowerCase()} was not found, or you do not have access to it.</Text>
    );

  return (
    <Stack>
      <Breadcrumbs>
        <AnchorLink to="/">Overview</AnchorLink>
        <Text>{area.name}</Text>
      </Breadcrumbs>
      <Group gap="xs">
        <Title order={2}>{area.name}</Title>
        <Badge variant="light">{humanize(area.kind)}</Badge>
        {area.is_critical && (
          <Badge color="orange" variant="light">
            Critical
          </Badge>
        )}
      </Group>
      <Title order={3}>{terms.devices}</Title>
      {devices.isPending && <PageLoader />}
      {devices.isError && <ErrorNotice error={devices.error} />}
      {devices.isSuccess && <DeviceTable devices={devices.data.items} />}
      {area.floor_id && (
        <AnchorLink to="/floors/$floorId" params={{ floorId: area.floor_id }}>
          See the floor plan
        </AnchorLink>
      )}
      {devices.isSuccess && <WallPhotos area={area} devices={devices.data.items} />}
    </Stack>
  );
}

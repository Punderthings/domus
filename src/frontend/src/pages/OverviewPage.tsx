import { AnchorLink, CardLink } from '../components/links';
import { Badge, Card, Group, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { useAreas, useBuildings, useFloors, useProperty, useTasks } from '../api/queries';
import type { Area, Building } from '../api/types';
import { useActiveMembership } from '../auth/useActiveProperty';
import { DueBadge } from '../components/DueBadge';
import { ErrorNotice, PageLoader } from '../components/States';
import { humanize, isoDay } from '../format';
import { terms } from '../terms';

/** Upcoming maintenance shown on the overview: anything due in the next 30 days. */
export const DUE_WINDOW_DAYS = 30;

function AreaGrid({ areas }: { areas: Area[] }) {
  if (areas.length === 0) return <Text c="dimmed">No {terms.areas.toLowerCase()} yet.</Text>;
  return (
    <SimpleGrid cols={{ base: 1, xs: 2, md: 3 }}>
      {areas.map((area) => (
        <CardLink key={area.id} withBorder to="/areas/$areaId" params={{ areaId: area.id }}>
          <Group justify="space-between" wrap="nowrap">
            <Text fw={500}>{area.name}</Text>
            {area.is_critical && (
              <Badge size="xs" color="orange" variant="light">
                Critical
              </Badge>
            )}
          </Group>
          <Text size="sm" c="dimmed">
            {humanize(area.kind)}
          </Text>
        </CardLink>
      ))}
    </SimpleGrid>
  );
}

function BuildingSection({ building, areas }: { building: Building; areas: Area[] }) {
  const floors = useFloors(building.id);
  const inBuilding = areas.filter((area) => area.building_id === building.id);
  const sortedFloors = [...(floors.data?.items ?? [])].sort((a, b) => b.level - a.level);
  const unfloored = inBuilding.filter(
    (area) => !area.floor_id || !sortedFloors.some((floor) => floor.id === area.floor_id),
  );

  return (
    <Stack gap="sm">
      <Group gap="xs">
        <Title order={3}>{building.name}</Title>
        <Badge variant="light">{humanize(building.kind)}</Badge>
      </Group>
      {floors.isPending && <PageLoader />}
      {floors.isError && <ErrorNotice error={floors.error} />}
      {sortedFloors.map((floor) => (
        <Stack key={floor.id} gap="xs">
          <Group gap="sm">
            <Title order={4} c="dimmed">
              {floor.name}
            </Title>
            <AnchorLink size="sm" to="/floors/$floorId" params={{ floorId: floor.id }}>
              Floor plan
            </AnchorLink>
          </Group>
          <AreaGrid areas={inBuilding.filter((area) => area.floor_id === floor.id)} />
        </Stack>
      ))}
      {floors.isSuccess && unfloored.length > 0 && <AreaGrid areas={unfloored} />}
    </Stack>
  );
}

function DueSoon({ propertyId }: { propertyId: string }) {
  const tasks = useTasks(propertyId, { due_before: isoDay(DUE_WINDOW_DAYS), active: true });
  if (tasks.isPending) return <PageLoader />;
  if (tasks.isError) return <ErrorNotice error={tasks.error} />;
  const items = [...tasks.data.items].sort((a, b) =>
    (a.next_due ?? '').localeCompare(b.next_due ?? ''),
  );
  return (
    <Card withBorder>
      <Title order={3} mb="sm">
        Maintenance due soon
      </Title>
      {items.length === 0 ? (
        <Text c="dimmed">Nothing due in the next {DUE_WINDOW_DAYS} days.</Text>
      ) : (
        <Stack gap="xs">
          {items.map((task) => (
            <Group key={task.id} justify="space-between" gap="xs">
              {task.asset_id ? (
                <AnchorLink to="/devices/$deviceId" params={{ deviceId: task.asset_id }}>
                  {task.title}
                </AnchorLink>
              ) : (
                <Text>{task.title}</Text>
              )}
              <DueBadge nextDue={task.next_due} leadDays={task.lead_days} />
            </Group>
          ))}
        </Stack>
      )}
    </Card>
  );
}

export function OverviewPage() {
  const membership = useActiveMembership();
  const propertyId = membership?.property_id;
  const property = useProperty(propertyId);
  const buildings = useBuildings(propertyId);
  const areas = useAreas(propertyId);

  if (property.isPending || buildings.isPending || areas.isPending) return <PageLoader />;
  const error = property.error ?? buildings.error ?? areas.error;
  if (error) return <ErrorNotice error={error} />;

  const allAreas = areas.data?.items ?? [];
  const sortedBuildings = [...(buildings.data?.items ?? [])].sort(
    (a, b) => Number(b.is_primary) - Number(a.is_primary) || a.name.localeCompare(b.name),
  );
  const outdoor = allAreas.filter((area) => !area.building_id);

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>{property.data?.name}</Title>
        {property.data?.address && <Text c="dimmed">{property.data.address}</Text>}
      </div>
      {propertyId && <DueSoon propertyId={propertyId} />}
      {sortedBuildings.map((building) => (
        <BuildingSection key={building.id} building={building} areas={allAreas} />
      ))}
      {outdoor.length > 0 && (
        <Stack gap="sm">
          <Title order={3}>Outdoor</Title>
          <AreaGrid areas={outdoor} />
        </Stack>
      )}
    </Stack>
  );
}

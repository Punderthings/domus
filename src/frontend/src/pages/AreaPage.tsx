import { AnchorLink } from '../components/links';
import { Badge, Breadcrumbs, Group, Stack, Text, Title } from '@mantine/core';
import { useParams } from '@tanstack/react-router';
import { useAreas, useAssets } from '../api/queries';
import { useActiveMembership } from '../auth/useActiveProperty';
import { DeviceTable } from '../components/DeviceTable';
import { ErrorNotice, PageLoader } from '../components/States';
import { humanize } from '../format';
import { terms } from '../terms';

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
    </Stack>
  );
}

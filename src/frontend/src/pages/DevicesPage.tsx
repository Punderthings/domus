import { Group, Select, Stack, TextInput, Title } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { useAreas, useAssets } from '../api/queries';
import { hasRole, toRole } from '../auth/permissions';
import { useActiveMembership } from '../auth/useActiveProperty';
import { ButtonLink } from '../components/links';
import { DeviceTable } from '../components/DeviceTable';
import { ErrorNotice, PageLoader } from '../components/States';
import { terms } from '../terms';

export function DevicesPage() {
  const search = useSearch({ from: '/app/devices' });
  const navigate = useNavigate({ from: '/devices' });
  const membership = useActiveMembership();
  const propertyId = membership?.property_id;
  const canAdd = membership !== undefined && hasRole(toRole(membership.role), 'maintainer');
  const areas = useAreas(propertyId);
  const [text, setText] = useState(search.q ?? '');
  const [debounced] = useDebouncedValue(text, 300);

  useEffect(() => {
    if ((debounced || undefined) !== search.q) {
      void navigate({ search: (prev) => ({ ...prev, q: debounced || undefined }), replace: true });
    }
  }, [debounced, search.q, navigate]);

  const devices = useAssets(propertyId, { q: search.q, area_id: search.area });
  const areaOptions = (areas.data?.items ?? [])
    .map((area) => ({ value: area.id, label: area.name }))
    .sort((a, b) => a.label.localeCompare(b.label));

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{terms.devices}</Title>
        {canAdd && <ButtonLink to="/devices/new">Add {terms.device.toLowerCase()}</ButtonLink>}
      </Group>
      <Group grow preventGrowOverflow={false} wrap="wrap">
        <TextInput
          label="Search"
          placeholder="Name, model, or serial"
          value={text}
          onChange={(event) => setText(event.currentTarget.value)}
        />
        <Select
          label={terms.area}
          placeholder={`All ${terms.areas.toLowerCase()}`}
          data={areaOptions}
          value={search.area ?? null}
          onChange={(value) =>
            void navigate({
              search: (prev) => ({ ...prev, area: value ?? undefined }),
              replace: true,
            })
          }
          clearable
          searchable
        />
      </Group>
      {devices.isPending && <PageLoader />}
      {devices.isError && <ErrorNotice error={devices.error} />}
      {devices.isSuccess && <DeviceTable devices={devices.data.items} />}
    </Stack>
  );
}

import { Badge, Group, List, Stack, Text, TextInput, Title } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useNavigate, useSearch } from '@tanstack/react-router';
import { useEffect, useState } from 'react';
import { useSearchResults } from '../api/queries';
import { useActiveMembership } from '../auth/useActiveProperty';
import { DeviceTable } from '../components/DeviceTable';
import { AnchorLink } from '../components/links';
import { ErrorNotice, PageLoader } from '../components/States';
import { humanize } from '../format';
import { terms } from '../terms';

export function SearchPage() {
  const search = useSearch({ from: '/app/search' });
  const navigate = useNavigate({ from: '/search' });
  const propertyId = useActiveMembership()?.property_id;
  const q = search.q ?? '';
  const [text, setText] = useState(q);
  const [debounced] = useDebouncedValue(text, 300);

  useEffect(() => {
    const next = debounced.trim() || undefined;
    if (next !== search.q) {
      void navigate({ search: { q: next }, replace: true });
    }
  }, [debounced, search.q, navigate]);

  const results = useSearchResults(propertyId, q);
  const areas = results.data?.areas ?? [];
  const devices = results.data?.assets ?? [];

  return (
    <Stack>
      <Title order={2}>Search</Title>
      <TextInput
        label="Search everything"
        description={`${terms.devices}, ${terms.areas.toLowerCase()}, models, serials, tags, and notes`}
        value={text}
        onChange={(event) => setText(event.currentTarget.value)}
        data-autofocus
      />
      {!q.trim() && <Text c="dimmed">Type a word, or the start of one.</Text>}
      {results.isFetching && !results.data && <PageLoader />}
      {results.isError && <ErrorNotice error={results.error} />}
      {results.isSuccess && areas.length === 0 && devices.length === 0 && (
        <Text c="dimmed">Nothing matches “{q}”.</Text>
      )}
      {areas.length > 0 && (
        <section aria-label={terms.areas}>
          <Title order={3} mb="xs">
            {terms.areas}
          </Title>
          <List spacing={4}>
            {areas.map((area) => (
              <List.Item key={area.id}>
                <Group gap="xs">
                  <AnchorLink to="/areas/$areaId" params={{ areaId: area.id }}>
                    {area.name}
                  </AnchorLink>
                  <Badge size="xs" variant="light">
                    {humanize(area.kind)}
                  </Badge>
                </Group>
              </List.Item>
            ))}
          </List>
        </section>
      )}
      {devices.length > 0 && (
        <section aria-label={terms.devices}>
          <Title order={3} mb="xs">
            {terms.devices}
          </Title>
          <DeviceTable devices={devices} />
        </section>
      )}
    </Stack>
  );
}

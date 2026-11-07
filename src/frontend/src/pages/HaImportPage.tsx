// Import Devices, Areas, and floors from Home Assistant: connect, preview, apply.
// The access token lives only in this page's state: it is sent with each request,
// never saved in the browser, and the server never stores it either.

import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  List,
  PasswordInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useState, type FormEvent } from 'react';
import { useBuildings, useHaApply, useHaPreview } from '../api/queries';
import type {
  Building,
  HaDeviceChoice,
  HaDevicePlan,
  HaFloorPlan,
  HaImportResult,
  HaPreview,
} from '../api/types';
import { hasRole, toRole } from '../auth/permissions';
import { useActiveMembership } from '../auth/useActiveProperty';
import { ErrorNotice } from '../components/States';
import { AnchorLink } from '../components/links';
import { terms } from '../terms';
import { ACTION_LABELS, REASON_LABELS, STATUS_LABELS, actionsFor, type Action } from '../haImport';

function ConnectForm({
  onPreview,
  pending,
}: {
  onPreview: (baseUrl: string, token: string) => void;
  pending: boolean;
}) {
  const [baseUrl, setBaseUrl] = useState('http://homeassistant.local:8123');
  const [token, setToken] = useState('');
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (baseUrl.trim() && token.trim()) onPreview(baseUrl.trim(), token.trim());
  };
  return (
    <form onSubmit={submit} aria-label="Connect to Home Assistant">
      <Stack maw={560}>
        <TextInput
          label="Home Assistant address"
          description="The address you open Home Assistant at."
          value={baseUrl}
          onChange={(event) => setBaseUrl(event.currentTarget.value)}
          required
        />
        <PasswordInput
          label="Long-lived access token"
          description="Create one in Home Assistant under your profile, Security tab. Use an admin user. Domus uses it for this import only and does not save it."
          value={token}
          onChange={(event) => setToken(event.currentTarget.value)}
          autoComplete="off"
          required
        />
        <Group>
          <Button type="submit" loading={pending}>
            Preview import
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

function FloorBuildings({
  floors,
  buildings,
  value,
  onChange,
}: {
  floors: HaFloorPlan[];
  buildings: Building[];
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  const fresh = floors.filter((f) => f.status === 'new');
  if (fresh.length === 0 || buildings.length < 2) return null;
  const options = buildings.map((b) => ({ value: b.id, label: b.name }));
  return (
    <Stack gap="xs">
      <Title order={4}>New floors</Title>
      <Text size="sm" c="dimmed">
        Home Assistant has no {terms.buildings.toLowerCase()}. Pick the{' '}
        {terms.building.toLowerCase()} each new floor belongs to, then preview again.
      </Text>
      {fresh.map((floor) => (
        <Select
          key={floor.ha_floor_id}
          label={floor.name}
          data={options}
          value={value[floor.ha_floor_id] ?? floor.building_id}
          onChange={(id) => id && onChange({ ...value, [floor.ha_floor_id]: id })}
          allowDeselect={false}
          maw={360}
        />
      ))}
    </Stack>
  );
}

function DeviceRow({
  device,
  action,
  onAction,
}: {
  device: HaDevicePlan;
  action: Action;
  onAction: (action: Action) => void;
}) {
  const status = STATUS_LABELS[device.status];
  const product = [device.manufacturer, device.model].filter(Boolean).join(' ');
  const options = actionsFor(device).map((a) => ({ value: a, label: ACTION_LABELS[a] }));
  return (
    <Table.Tr>
      <Table.Td>
        <Text fw={500}>{device.name}</Text>
        {product && (
          <Text size="sm" c="dimmed">
            {product}
          </Text>
        )}
      </Table.Td>
      <Table.Td>{device.area_name ?? '—'}</Table.Td>
      <Table.Td>
        <Badge color={status.color} variant="light">
          {status.label}
        </Badge>
        {device.match_reason && device.status === 'matched' && (
          <Text size="xs" c="dimmed">
            {REASON_LABELS[device.match_reason]}
            {device.asset_name ? `: ${device.asset_name}` : ''}
          </Text>
        )}
        {device.changes.map((c) => (
          <Text size="xs" c="dimmed" key={c.field}>
            {c.field}: {c.old ?? '—'} → {c.new ?? '—'}
          </Text>
        ))}
        {device.note && (
          <Text size="xs" c="orange">
            {device.note}
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        <Select
          aria-label={`Action for ${device.name}`}
          data={options}
          value={action}
          onChange={(value) => value && onAction(value as Action)}
          allowDeselect={false}
          disabled={options.length === 1}
          size="xs"
          miw={200}
        />
      </Table.Td>
    </Table.Tr>
  );
}

function ImportDone({ result, onAgain }: { result: HaImportResult; onAgain: () => void }) {
  const counts = result.counts;
  return (
    <Stack>
      <Alert color="green" title="Import finished">
        <List size="sm">
          <List.Item>
            {counts.created ?? 0} added, {counts.updated ?? 0} updated, {counts.unchanged ?? 0}{' '}
            unchanged, {counts.skipped ?? 0} skipped
          </List.Item>
          <List.Item>
            {result.areas_created} new {terms.areas.toLowerCase()}, {result.floors_created} new
            floors
          </List.Item>
        </List>
      </Alert>
      <Group>
        <AnchorLink to="/devices">See all {terms.devices.toLowerCase()}</AnchorLink>
        <Anchor component="button" type="button" onClick={onAgain}>
          Import again
        </Anchor>
      </Group>
    </Stack>
  );
}

export function HaImportPage() {
  const membership = useActiveMembership();
  const propertyId = membership?.property_id;
  const buildings = useBuildings(propertyId);
  const preview = useHaPreview();
  const apply = useHaApply();
  const [connection, setConnection] = useState<{ base_url: string; token: string } | null>(null);
  const [floorBuildings, setFloorBuildings] = useState<Record<string, string>>({});
  const [choices, setChoices] = useState<Record<string, Action>>({});
  const [plan, setPlan] = useState<HaPreview | null>(null);

  if (!hasRole(membership ? toRole(membership.role) : undefined, 'maintainer')) {
    return (
      <Alert color="gray" title="Maintainers only">
        Ask a Maintainer or Admin to import from Home Assistant.
      </Alert>
    );
  }

  const runPreview = (base_url: string, token: string, mapping = floorBuildings) => {
    setConnection({ base_url, token });
    apply.reset();
    preview.mutate(
      { property_id: propertyId, base_url, token, building_for_floor: mapping },
      {
        onSuccess: (data) => {
          setPlan(data);
          setChoices(Object.fromEntries(data.devices.map((d) => [d.ha_device_id, d.action])));
        },
      },
    );
  };

  const runApply = () => {
    if (!connection || !plan) return;
    const devices: HaDeviceChoice[] = plan.devices.map((d) => ({
      ha_device_id: d.ha_device_id,
      action: choices[d.ha_device_id] ?? d.action,
      asset_id: d.asset_id,
    }));
    apply.mutate(
      { property_id: propertyId, ...connection, building_for_floor: floorBuildings, devices },
      {
        onSuccess: () => {
          // Forget the token as soon as it is no longer needed.
          setConnection(null);
          setPlan(null);
        },
      },
    );
  };

  const reset = () => {
    setConnection(null);
    setPlan(null);
    preview.reset();
    apply.reset();
  };

  const selected = plan
    ? plan.devices.filter((d) => (choices[d.ha_device_id] ?? d.action) !== 'skip').length
    : 0;
  const newAreas = plan?.areas.filter((a) => a.status === 'new') ?? [];

  return (
    <Stack>
      <Title order={2}>Import from Home Assistant</Title>
      <Text c="dimmed" maw={720}>
        Domus reads your Home Assistant floors, {terms.areas.toLowerCase()}, and{' '}
        {terms.devices.toLowerCase()}, matches them with what is already here, and shows you every
        change before anything is saved. Importing again later only adds what is new.
      </Text>

      {apply.isSuccess ? (
        <ImportDone result={apply.data} onAgain={reset} />
      ) : (
        <>
          {!plan && <ConnectForm onPreview={runPreview} pending={preview.isPending} />}
          {preview.isError && <ErrorNotice error={preview.error} />}
          {apply.isError && <ErrorNotice error={apply.error} />}
          {plan && (
            <Stack>
              <Group gap="xs">
                {Object.entries(plan.counts).map(([status, n]) => (
                  <Badge
                    key={status}
                    variant="light"
                    color={STATUS_LABELS[status as HaDevicePlan['status']]?.color ?? 'gray'}
                  >
                    {STATUS_LABELS[status as HaDevicePlan['status']]?.label ?? status}: {n}
                  </Badge>
                ))}
              </Group>
              <FloorBuildings
                floors={plan.floors}
                buildings={buildings.data?.items ?? []}
                value={floorBuildings}
                onChange={(next) => {
                  setFloorBuildings(next);
                  if (connection) runPreview(connection.base_url, connection.token, next);
                }}
              />
              {newAreas.length > 0 && (
                <Text size="sm">
                  New {terms.areas.toLowerCase()}: {newAreas.map((a) => a.name).join(', ')}
                </Text>
              )}
              <Table.ScrollContainer minWidth={640}>
                <Table striped verticalSpacing="xs" aria-label="Devices to import">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{terms.device}</Table.Th>
                      <Table.Th>{terms.area}</Table.Th>
                      <Table.Th>Status</Table.Th>
                      <Table.Th>Action</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {plan.devices.map((device) => (
                      <DeviceRow
                        key={device.ha_device_id}
                        device={device}
                        action={choices[device.ha_device_id] ?? device.action}
                        onAction={(action) =>
                          setChoices((prev) => ({ ...prev, [device.ha_device_id]: action }))
                        }
                      />
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
              <Group>
                <Button onClick={runApply} loading={apply.isPending}>
                  Import {selected} {selected === 1 ? terms.device : terms.devices}
                </Button>
                <Button variant="default" onClick={reset} disabled={apply.isPending}>
                  Cancel
                </Button>
              </Group>
            </Stack>
          )}
        </>
      )}
    </Stack>
  );
}

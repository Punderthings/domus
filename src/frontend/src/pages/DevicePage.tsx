import { AnchorLink, ButtonLink } from '../components/links';
import {
  Anchor,
  Badge,
  Breadcrumbs,
  Card,
  Group,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { useParams } from '@tanstack/react-router';
import type { ReactNode } from 'react';
import { useAsset, useProperty, useTasks } from '../api/queries';
import { allows, hasRole, toRole } from '../auth/permissions';
import { useActiveMembership } from '../auth/useActiveProperty';
import { DueBadge } from '../components/DueBadge';
import { MarkDoneButton } from '../components/MarkDoneButton';
import { ErrorNotice, PageLoader } from '../components/States';
import { formatDate, formatMoney, humanize, safeHttpUrl } from '../format';
import { terms } from '../terms';

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text component="div">{children}</Text>
    </div>
  );
}

export function DevicePage() {
  const { deviceId } = useParams({ from: '/app/devices/$deviceId' });
  const membership = useActiveMembership();
  const property = useProperty(membership?.property_id);
  const device = useAsset(deviceId);
  const tasks = useTasks(membership?.property_id, { asset_id: deviceId });

  if (device.isPending) return <PageLoader />;
  if (device.isError) return <ErrorNotice error={device.error} />;
  const d = device.data;
  const manual = safeHttpUrl(d.product?.manual_url);
  const currency = property.data?.default_currency ?? 'USD';
  const role = membership ? toRole(membership.role) : undefined;
  const canEdit = hasRole(role, 'maintainer') && allows(d.access, 'manage');
  const canLog = hasRole(role, 'resident');

  return (
    <Stack>
      <Breadcrumbs>
        <AnchorLink to="/devices">{terms.devices}</AnchorLink>
        <Text>{d.name}</Text>
      </Breadcrumbs>
      <Group justify="space-between" align="flex-start">
        <Group gap="xs">
          <Title order={2}>{d.name}</Title>
          <Badge variant="light">{humanize(d.category)}</Badge>
          {d.is_critical && (
            <Badge color="orange" variant="light">
              Critical
            </Badge>
          )}
          {(d.tags ?? []).map((tag) => (
            <Badge key={tag.id} variant="outline" color={tag.color ?? undefined}>
              {tag.name}
            </Badge>
          ))}
        </Group>
        {canEdit && (
          <ButtonLink to="/devices/$deviceId/edit" params={{ deviceId }} variant="default">
            Edit
          </ButtonLink>
        )}
      </Group>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder>
          <Title order={3} mb="sm">
            Details
          </Title>
          <SimpleGrid cols={2}>
            <Field label="Manufacturer">{d.product?.manufacturer ?? '—'}</Field>
            <Field label="Model">{d.product?.model ?? '—'}</Field>
            <Field label="Status">{humanize(d.status)}</Field>
            {'install_date' in d && <Field label="Installed">{formatDate(d.install_date)}</Field>}
            {'warranty_expires' in d && (
              <Field label="Warranty until">{formatDate(d.warranty_expires)}</Field>
            )}
            {'purchase_price' in d && (
              <Field label="Purchase price">{formatMoney(d.purchase_price, currency)}</Field>
            )}
            {manual && (
              <Field label="Manual">
                <Anchor href={manual} target="_blank" rel="noopener noreferrer">
                  Open manual
                </Anchor>
              </Field>
            )}
          </SimpleGrid>
          {d.notes && (
            <Text mt="md" style={{ whiteSpace: 'pre-wrap' }}>
              {d.notes}
            </Text>
          )}
        </Card>

        <Card withBorder>
          <Title order={3} mb="sm">
            Where it is
          </Title>
          {d.location ? (
            <Stack gap="xs">
              <Field label="Location">{d.location.name}</Field>
              {d.location.position_note && (
                <Field label="Position">{d.location.position_note}</Field>
              )}
              <AnchorLink to="/areas/$areaId" params={{ areaId: d.location.area_id }}>
                Open {terms.area.toLowerCase()}
              </AnchorLink>
            </Stack>
          ) : (
            <Text c="dimmed">No location recorded.</Text>
          )}
        </Card>
      </SimpleGrid>

      {'identifiers' in d && d.identifiers.length > 0 && (
        <Card withBorder>
          <Title order={3} mb="sm">
            Identifiers
          </Title>
          <Table>
            <Table.Tbody>
              {d.identifiers.map((identifier) => (
                <Table.Tr key={identifier.id}>
                  <Table.Td>{humanize(identifier.kind)}</Table.Td>
                  <Table.Td ff="monospace">{identifier.value}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}

      <Card withBorder>
        <Title order={3} mb="sm">
          Maintenance
        </Title>
        {tasks.isPending && <PageLoader />}
        {tasks.isError && <ErrorNotice error={tasks.error} />}
        {tasks.isSuccess &&
          (tasks.data.items.length === 0 ? (
            <Text c="dimmed">No maintenance tasks.</Text>
          ) : (
            <Stack gap="xs">
              {tasks.data.items.map((task) => (
                <Group key={task.id} justify="space-between" gap="xs">
                  <Text>{task.title}</Text>
                  <Group gap="xs">
                    <DueBadge nextDue={task.next_due} leadDays={task.lead_days} />
                    {canLog && <MarkDoneButton task={task} currency={currency} />}
                  </Group>
                </Group>
              ))}
            </Stack>
          ))}
      </Card>
    </Stack>
  );
}

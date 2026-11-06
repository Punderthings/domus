import { AnchorLink } from './links';
import { Badge, Group, Table, Text } from '@mantine/core';
import type { Asset } from '../api/types';
import { humanize } from '../format';
import { terms } from '../terms';

export function DeviceTable({ devices }: { devices: Asset[] }) {
  if (devices.length === 0) {
    return <Text c="dimmed">No {terms.devices.toLowerCase()} here yet.</Text>;
  }
  return (
    <Table.ScrollContainer minWidth={420}>
      <Table striped highlightOnHover verticalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Name</Table.Th>
            <Table.Th>Category</Table.Th>
            <Table.Th>Tags</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {devices.map((device) => (
            <Table.Tr key={device.id}>
              <Table.Td>
                <Group gap="xs" wrap="nowrap">
                  <AnchorLink to="/devices/$deviceId" params={{ deviceId: device.id }}>
                    {device.name}
                  </AnchorLink>
                  {device.is_critical && (
                    <Badge size="xs" color="orange" variant="light">
                      Critical
                    </Badge>
                  )}
                </Group>
              </Table.Td>
              <Table.Td>{humanize(device.category)}</Table.Td>
              <Table.Td>
                <Group gap={4}>
                  {(device.tags ?? []).map((tag) => (
                    <Badge key={tag.id} size="sm" variant="outline" color={tag.color ?? undefined}>
                      {tag.name}
                    </Badge>
                  ))}
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

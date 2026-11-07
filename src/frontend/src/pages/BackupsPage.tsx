import { Alert, Anchor, Button, Card, Code, Group, Stack, Table, Text, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { ApiError } from '../api/client';
import { backupDownloadUrl, useBackups, useCreateBackup } from '../api/mutations';
import { hasRole, toRole } from '../auth/permissions';
import { useActiveMembership } from '../auth/useActiveProperty';
import { ErrorNotice, PageLoader } from '../components/States';
import { formatBytes } from '../format';

function BackupList() {
  const backups = useBackups(true);
  const create = useCreateBackup();

  if (backups.isPending) return <PageLoader />;
  if (backups.isError) {
    if (backups.error instanceof ApiError && backups.error.status === 403) {
      return (
        <Alert color="yellow" title="Not allowed">
          A backup holds every property on this server, so only someone who is an Admin of all of
          them can make or download one.
        </Alert>
      );
    }
    return <ErrorNotice error={backups.error} />;
  }

  const makeBackup = () =>
    create.mutate(undefined, {
      onSuccess: (made) =>
        notifications.show({
          message: made.missing_files
            ? `Backup ${made.name} saved, but ${made.missing_files} attached files were missing.`
            : `Backup ${made.name} saved.`,
          color: made.missing_files ? 'yellow' : undefined,
        }),
    });

  return (
    <Card withBorder>
      <Group justify="space-between" mb="sm">
        <Title order={3}>Backups on this server</Title>
        <Button onClick={makeBackup} loading={create.isPending}>
          Make a backup now
        </Button>
      </Group>
      {create.isError && <ErrorNotice error={create.error} />}
      {backups.data.items.length === 0 ? (
        <Text c="dimmed">No backups yet.</Text>
      ) : (
        <Table.ScrollContainer minWidth={480}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>File</Table.Th>
                <Table.Th>Made</Table.Th>
                <Table.Th>Size</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {backups.data.items.map((backup) => (
                <Table.Tr key={backup.name}>
                  <Table.Td ff="monospace">{backup.name}</Table.Td>
                  <Table.Td>
                    {new Intl.DateTimeFormat(undefined, {
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    }).format(new Date(backup.modified_at))}
                  </Table.Td>
                  <Table.Td>{formatBytes(backup.size_bytes)}</Table.Td>
                  <Table.Td>
                    <Anchor
                      href={backupDownloadUrl(backup.name)}
                      download={backup.name}
                      aria-label={`Download ${backup.name}`}
                    >
                      Download
                    </Anchor>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Card>
  );
}

export function BackupsPage() {
  const membership = useActiveMembership();
  const isAdmin = membership !== undefined && hasRole(toRole(membership.role), 'admin');

  return (
    <Stack>
      <Title order={2}>Backup and restore</Title>
      <Text c="dimmed">
        A backup is one <Code>.hiotbak</Code> file with the database, every attached file, and a
        plain JSON copy of all records. Keep a copy somewhere other than this server.
      </Text>
      {isAdmin ? (
        <BackupList />
      ) : (
        <Alert color="yellow" title="Not allowed">
          Only Admins can make or download backups.
        </Alert>
      )}
      <Card withBorder>
        <Title order={3} mb="xs">
          Restore or export
        </Title>
        <Text mb="sm">
          Restoring replaces data under the running server, so it is done from the command line.
          Stop Domus first, then run one of these on the server:
        </Text>
        <Stack gap="xs">
          <Text>
            Check a backup: <Code>domus backup verify FILE.hiotbak</Code>
          </Text>
          <Text>
            Preview a merge: <Code>domus restore --merge --dry-run FILE.hiotbak</Code>
          </Text>
          <Text>
            Merge it into the current data: <Code>domus restore --merge FILE.hiotbak</Code>
          </Text>
          <Text>
            Replace all data (a safety copy is saved first): <Code>domus restore FILE.hiotbak</Code>
          </Text>
          <Text>
            Export every record as JSON lines: <Code>domus export NEW_FOLDER</Code>
          </Text>
        </Stack>
      </Card>
    </Stack>
  );
}

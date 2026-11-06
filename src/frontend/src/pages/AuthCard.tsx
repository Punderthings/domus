import { Center, Paper, Stack, Text, Title } from '@mantine/core';
import type { ReactNode } from 'react';

export function AuthCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <Center mih="100vh" p="md">
      <Paper withBorder shadow="sm" p="xl" w="100%" maw={420}>
        <Stack>
          <div>
            <Title order={2}>{title}</Title>
            {subtitle && <Text c="dimmed">{subtitle}</Text>}
          </div>
          {children}
        </Stack>
      </Paper>
    </Center>
  );
}

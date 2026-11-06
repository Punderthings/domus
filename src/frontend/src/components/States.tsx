import { Alert, Center, Loader, Stack, Text, Title } from '@mantine/core';
import { Link } from '@tanstack/react-router';
import { ApiError } from '../api/client';

export function PageLoader() {
  return (
    <Center py="xl">
      <Loader aria-label="Loading" />
    </Center>
  );
}

export function ErrorNotice({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError
      ? error.status === 403
        ? 'You do not have access to this.'
        : error.status === 404
          ? 'This was not found. It may have been removed.'
          : error.message
      : 'Could not reach the Domus server. Check that it is running.';
  return (
    <Alert color="red" title="Something went wrong" role="alert">
      {message}
    </Alert>
  );
}

export function NotFound() {
  return (
    <Stack align="center" py="xl">
      <Title order={2}>Page not found</Title>
      <Text c="dimmed">
        <Link to="/">Go to the overview</Link>
      </Text>
    </Stack>
  );
}

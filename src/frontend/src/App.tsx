import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { RouterProvider, createBrowserHistory, type RouterHistory } from '@tanstack/react-router';
import { useState } from 'react';
import { createQueryClient } from './queryClient';
import { createAppRouter } from './router';
import { theme } from './theme';

interface AppProps {
  queryClient?: QueryClient;
  history?: RouterHistory;
}

export function App({ queryClient, history }: AppProps) {
  const [client] = useState(() => queryClient ?? createQueryClient());
  const [router] = useState(() => createAppRouter(history ?? createBrowserHistory()));
  return (
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <Notifications />
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </MantineProvider>
  );
}

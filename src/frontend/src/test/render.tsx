import { createMemoryHistory } from '@tanstack/react-router';
import { render } from '@testing-library/react';
import { App } from '../App';
import { createQueryClient } from '../queryClient';

/** Render the whole app at a URL, with a fresh cache and no retries. */
export function renderApp(url = '/') {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false, refetchOnWindowFocus: false } });
  const history = createMemoryHistory({ initialEntries: [url] });
  return { history, queryClient, ...render(<App queryClient={queryClient} history={history} />) };
}

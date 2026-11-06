import { createTheme } from '@mantine/core';

// System font stack: nothing is fetched at runtime, so the app works offline.
export const theme = createTheme({
  primaryColor: 'blue',
  defaultRadius: 'md',
  fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
});

/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';

// The built app is served by the FastAPI backend from src/domus/static/.
// Relative to this folder (Vite's root).
const outDir = '../domus/static';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir,
    emptyOutDir: true,
    // Served from the local server, not a CDN; Mantine plus React is about 210 kB gzipped.
    chunkSizeWarningLimit: 800,
  },
  server: {
    // During development, forward API calls to a local `domus serve`.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/calendar.ics': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});

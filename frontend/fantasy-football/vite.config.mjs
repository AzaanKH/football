import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Same port and output folder the project used under Create React App
  server: { port: 3000 },
  preview: { port: 3000 },
  build: { outDir: 'build' },
  // Env vars exposed to the app (REACT_APP_ kept for older .env files)
  envPrefix: ['VITE_', 'REACT_APP_'],
  test: {
    environment: 'jsdom',
    // Threads start faster than forked processes here (forks timed out on Windows)
    pool: 'threads',
    globals: true,
    setupFiles: './src/setupTests.js',
    // Fresh mock implementations for every test (CRA's resetMocks behavior)
    mockReset: true,
    css: false,
  },
});

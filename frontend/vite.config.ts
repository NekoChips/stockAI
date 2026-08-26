import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  base: '/',
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/healthz': 'http://127.0.0.1:8765',
      '/readyz': 'http://127.0.0.1:8765',
    },
  },
  build: {
    outDir: path.resolve(__dirname, '../src/stock_ai_agent/spa'),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;

          if (id.includes('/react/') || id.includes('/react-dom/') || id.includes('/react-router')) {
            return 'react-vendor';
          }
          if (id.includes('/@tanstack/')) return 'query-vendor';
          if (id.includes('/dayjs/')) return 'dayjs-vendor';
          return undefined;
        },
      },
    },
  },
});

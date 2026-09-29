import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    port: 5177,
    proxy: {
      '/api/cad': {
        target: 'http://127.0.0.1:8787',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/cad/, '/api'),
      },
      '/api': { target: 'http://127.0.0.1:8787', changeOrigin: true },
    },
  },
});

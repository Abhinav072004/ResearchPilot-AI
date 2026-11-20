import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [tailwindcss()],
  server: { host: '0.0.0.0', proxy: { '/api': 'http://localhost:8000', '/health': 'http://localhost:8000' } },
});

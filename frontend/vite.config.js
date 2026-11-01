import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  return {
    base: env.VITE_BASE || '/',
    server: { proxy: { '/api': env.VITE_PROXY || 'http://localhost:8000' } },
    test: { environment: 'jsdom', setupFiles: './src/setupTests.js', restoreMocks: true },
  };
});

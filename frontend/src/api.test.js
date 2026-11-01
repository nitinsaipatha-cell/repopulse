import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });
it('strips trailing API-base slashes and appends /api exactly once', async () => {
  vi.stubEnv('VITE_API_BASE', 'https://api.example.test///');
  vi.resetModules();
  const { apiUrl, absoluteApiUrl } = await import('./api');
  expect(apiUrl('/analyze/a/b', { activity: 25 })).toBe('https://api.example.test/api/analyze/a/b?activity=25');
  expect(absoluteApiUrl('/badge/a/b.svg')).toBe('https://api.example.test/api/badge/a/b.svg');
});

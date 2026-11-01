import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { apiUrl, CATEGORIES, DEFAULT_WEIGHTS, normalizeRepo } from './api';

const config = { categories: CATEGORIES, default_weights: DEFAULT_WEIGHTS, risk_thresholds: { Low: 80, Medium: 50 } };
const status = { ok: true, token_configured: false, rate_limit: { limit: 60, remaining: 40, reset: 1793500000 } };
function analysis(name = 'pallets/flask', score = 73.9) {
  return { full_name: name, repo: { html_url: `https://github.com/${name}`, description: 'An explainable repository result.', stars: 1000, forks: 100, language: 'Python', license: 'MIT' },
    score, risk: score >= 80 ? 'Low' : score >= 50 ? 'Medium' : 'High', weights: DEFAULT_WEIGHTS, categories: Object.fromEntries(CATEGORIES.map(({ key, label }) => [key, { label, score: key === 'security' ? null : score, metrics: [{ key: `${key}_metric`, label: `${label} metric`, value: 20, score: key === 'security' ? null : .9, detail: `${label} evidence from public data.` }] }])),
    overrides: ['A recorded override.'], concerns: ['Activity: A recorded concern.'], strengths: ['Documentation: Clear documentation.'],
    mature: true, adjustments: [{ category: 'activity', before: 40, after: 60, note: 'Established project adjustment.' }],
    scorecard: { score: 8, date: '2026-10-01' }, from_cache: false, fetched_at: '2026-11-01T00:00:00Z' };
}
const ok = data => Promise.resolve({ ok: true, status: 200, json: async () => data });
let handler;
beforeEach(() => {
  handler = (path, options) => {
    if (path === '/api/config') return ok(config);
    if (path === '/api/status') return ok(status);
    if (path.startsWith('/api/analyze/')) return ok(analysis());
    if (path.startsWith('/api/history/')) return ok([]);
    throw new Error(`Unexpected fetch: ${path}`);
  };
  vi.stubGlobal('fetch', vi.fn((path, options) => handler(path, options)));
});
async function start() { render(<App />); await screen.findByLabelText('GitHub repository'); }
function checkRepo(value = 'pallets/flask') {
  fireEvent.change(screen.getByLabelText('GitHub repository'), { target: { value } });
  fireEvent.click(screen.getByRole('button', { name: 'Check health' }));
}
const analyzeCalls = () => fetch.mock.calls.filter(([path]) => path.startsWith('/api/analyze/'));

it('normalizes repository references with backend-compatible validation', () => {
  for (const input of ['pallets/flask', 'https://github.com/pallets/flask/tree/main/src', 'git+https://github.com/pallets/flask.git', 'github:pallets/flask']) expect(normalizeRepo(input)).toBe('pallets/flask');
  for (const input of ['wrong', 'a/b/c', 'https://evil.test/a/b', '../b', 'a/b c', 'https://github.com:443/a/b']) expect(() => normalizeRepo(input)).toThrow('is not a GitHub repository');
  expect(normalizeRepo('https://github.com/a/b/../c')).toBe('a/b');
  expect(apiUrl('/config')).toBe('/api/config');
});

it('renders startup banners, full analysis, expandable null metrics, history hint and badge actions', async () => {
  await start();
  expect(screen.getByText(/60 requests per hour/)).toBeTruthy();
  expect(screen.getByText(/Only 40 GitHub requests remain/)).toBeTruthy();
  checkRepo();
  expect(screen.getByText(/Collecting commits, issues/)).toBeTruthy();
  await screen.findByRole('link', { name: 'pallets/flask' });
  expect(screen.getByText('An explainable repository result.')).toBeTruthy();
  expect(screen.getByRole('img', { name: /Repository pulse: 73.9/ })).toBeTruthy();
  expect(screen.getByText('Needs attention')).toBeTruthy();
  expect(screen.getByText('Going well')).toBeTruthy();
  expect(screen.getByText(/Maturity adjustment:/)).toBeTruthy();
  expect(screen.getByText(/The two should agree in direction/)).toBeTruthy();
  expect(screen.getByText(/At least two history points/)).toBeTruthy();
  const security = screen.getByRole('button', { name: /Security.*Details/ });
  expect(security.getAttribute('aria-expanded')).toBe('false');
  fireEvent.click(security);
  expect(security.getAttribute('aria-expanded')).toBe('true');
  expect(screen.getByText('Security evidence from public data.')).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Download PDF report' }).href).toContain('/api/report/pallets/flask.pdf');
  const writeText = vi.fn().mockResolvedValue();
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  fireEvent.click(screen.getByRole('button', { name: 'Copy README badge' }));
  await screen.findByText('README badge copied.');
  expect(writeText.mock.calls[0][0]).toContain('http://localhost:3000/api/badge/pallets/flask.svg');
});

it('debounces slider requests with weights, keeps the result visible, and resets defaults', async () => {
  await start(); checkRepo();
  await screen.findByRole('link', { name: 'pallets/flask' });
  const count = analyzeCalls().length;
  const slider = screen.getByRole('slider', { name: 'Activity' });
  fireEvent.change(slider, { target: { value: '60' } });
  fireEvent.change(slider, { target: { value: '80' } });
  expect(screen.getByRole('link', { name: 'pallets/flask' })).toBeTruthy();
  expect(document.querySelector('.result.updating')).toBeTruthy();
  expect(analyzeCalls().length).toBe(count);
  await waitFor(() => expect(analyzeCalls().length).toBe(count + 1));
  expect(analyzeCalls().at(-1)[0]).toContain('activity=80');
  expect(analyzeCalls().at(-1)[0]).not.toContain('refresh=true');
  fireEvent.click(screen.getByRole('button', { name: 'Reset to defaults' }));
  await waitFor(() => expect(analyzeCalls().at(-1)[0]).toContain('activity=25'));
});

it('shows plain-language API errors', async () => {
  const original = handler;
  handler = (path, options) => path.startsWith('/api/analyze/') ? Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: 'Repository not found. Check the name; it may also be private.' }) }) : original(path, options);
  await start(); checkRepo();
  expect((await screen.findByRole('alert')).textContent).toBe('Repository not found. Check the name; it may also be private.');
});

it('rejects invalid repository input before a request', async () => {
  await start(); checkRepo('not a repository');
  expect(screen.getByRole('alert').textContent).toContain('Use owner/repo or a github.com URL.');
  expect(analyzeCalls()).toHaveLength(0);
});

it.each([true, false])('renders compare verdict, table, stability and weighted re-request (%s)', async stable => {
  const original = handler;
  handler = (path, options) => path.startsWith('/api/compare') ? ok({ repos: [analysis('a/one', 90), analysis('b/two', 60)], sensitivity: { ranking_stable: stable, trials: 300, repos: [{ full_name: 'a/one', first_pct: 95 }, { full_name: 'b/two', first_pct: 5 }] } }) : original(path, options);
  await start(); fireEvent.click(screen.getByRole('tab', { name: 'Compare' }));
  fireEvent.change(screen.getByLabelText('GitHub repositories'), { target: { value: 'a/one\nb/two' } });
  fireEvent.click(screen.getByRole('button', { name: 'Compare health' }));
  await screen.findByText('a/one has the highest score');
  expect(screen.getByText(stable ? /ranking is stable/ : /ranking depends on weights/)).toBeTruthy();
  expect(screen.getByRole('table', { name: 'Repository health comparison' })).toBeTruthy();
  expect(screen.getByText('95.0%')).toBeTruthy();
  fireEvent.change(screen.getByRole('slider', { name: 'Security' }), { target: { value: '70' } });
  await waitFor(() => expect(fetch.mock.calls.some(([path]) => path.startsWith('/api/compare') && path.includes('security=70'))).toBe(true));
});

it('polls dependency scans and shows vulnerable and unscored rows, sorting, CSV and repository links', async () => {
  let polls = 0;
  const rows = [
    { name: 'vulnerable', ecosystem: 'npm', declared_version: '1.2.3', score: 40, risk: 'High', repo: 'pallets/flask', vuln_count: 2, high_vuln_count: 1, vuln_ids: ['GHSA-test'], concerns: ['An actionable concern.'], note: 'Declared version has known vulnerabilities' },
    { name: 'unlinked', ecosystem: 'npm', declared_version: null, score: null, risk: null, repo: null, vuln_count: 0, concerns: [], note: 'No GitHub repository linked from the registry' },
  ];
  const original = handler;
  handler = (path, options) => {
    if (path === '/api/scan') return ok({ job_id: '123456abcdef', total: 2, truncated: false });
    if (path === '/api/scan/123456abcdef') return ok({ status: ++polls === 1 ? 'running' : 'done', total: 2, done: polls === 1 ? 1 : 2, rows: polls === 1 ? rows.slice(0, 1) : rows, filename: 'package.json', truncated: false, message: null });
    return original(path, options);
  };
  await start(); fireEvent.click(screen.getByRole('tab', { name: 'Scan dependencies' }));
  fireEvent.change(screen.getByLabelText(/Drag and drop/), { target: { files: [new File(['{"dependencies":{"a":"1"}}'], 'package.json', { type: 'application/json' })] } });
  fireEvent.click(screen.getByLabelText('Include devDependencies'));
  fireEvent.click(screen.getByRole('button', { name: 'Scan dependencies' }));
  await screen.findByText('0 of 2 checked');
  await screen.findByText('1 of 2 checked', {}, { timeout: 1800 });
  await screen.findByText('Dependency health', {}, { timeout: 1800 });
  expect(screen.getByText('No GitHub repository linked from the registry')).toBeTruthy();
  expect(screen.getByText(/2 known vulnerabilities/)).toBeTruthy();
  expect(screen.getAllByText('Not scored').length).toBeGreaterThan(0);
  expect(screen.getByText(/ranges are checked at their lowest version/)).toBeTruthy();
  const sent = JSON.parse(fetch.mock.calls.find(([path]) => path === '/api/scan')[1].body);
  expect(sent.include_dev).toBe(true);
  expect(screen.getByRole('link', { name: 'Download scan CSV' }).href).toContain('/api/scan/123456abcdef/csv');
  fireEvent.change(screen.getByLabelText('Sort dependencies'), { target: { value: 'name' } });
  const table = screen.getByRole('table', { name: 'package.json' });
  expect(within(table).getAllByRole('row')[1].textContent).toContain('unlinked');
  fireEvent.click(screen.getByRole('button', { name: 'Check pallets/flask' }));
  await screen.findByRole('link', { name: 'pallets/flask' });
  expect(screen.getByRole('tab', { name: 'Check a repository' }).getAttribute('aria-selected')).toBe('true');
});

it('ignores an out-of-date response even when fetch does not honor cancellation', async () => {
  let resolveOld;
  let seen = 0;
  const original = handler;
  handler = (path, options) => {
    if (path.startsWith('/api/analyze/')) {
      if (++seen === 1) return new Promise(resolve => { resolveOld = resolve; });
      return ok(analysis('new/repo', 80));
    }
    return original(path, options);
  };
  await start(); checkRepo('old/repo');
  await waitFor(() => expect(seen).toBe(1));
  checkRepo('new/repo');
  await screen.findByRole('link', { name: 'new/repo' });
  await act(async () => { resolveOld(await ok(analysis('old/repo', 30))); });
  expect(screen.queryByRole('link', { name: 'old/repo' })).toBeNull();
});

it('refreshes once, then rescoring returns to the cached path', async () => {
  await start(); checkRepo();
  await screen.findByRole('link', { name: 'pallets/flask' });
  fireEvent.click(screen.getByRole('button', { name: 'Refresh data' }));
  await waitFor(() => expect(analyzeCalls().at(-1)[0]).toContain('refresh=true'));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Refresh data' }).disabled).toBe(false));
  fireEvent.change(screen.getByRole('slider', { name: 'Activity' }), { target: { value: '75' } });
  await waitFor(() => expect(analyzeCalls().at(-1)[0]).toContain('activity=75'));
  expect(analyzeCalls().at(-1)[0]).not.toContain('refresh=true');
});

it('rejects duplicate comparisons without an API request', async () => {
  await start(); fireEvent.click(screen.getByRole('tab', { name: 'Compare' }));
  fireEvent.change(screen.getByLabelText('GitHub repositories'), { target: { value: 'a/one,A/ONE' } });
  fireEvent.click(screen.getByRole('button', { name: 'Compare health' }));
  expect(screen.getByRole('alert').textContent).toContain('2 to 4 unique');
  expect(fetch.mock.calls.some(([path]) => path.startsWith('/api/compare'))).toBe(false);
});

it('renders the history chart when two measurements exist', async () => {
  const original = handler;
  handler = (path, options) => path.startsWith('/api/history/') ? ok([{ ts: '2026-10-01', score: 80 }, { ts: '2026-11-01', score: 90 }]) : original(path, options);
  await start(); checkRepo();
  await screen.findByRole('img', { name: 'Repository score over time' });
  expect(screen.queryByText(/At least two history points/)).toBeNull();
});

it('shows an alert for an empty repository without native validation or an analysis request', async () => {
  await start();
  const input = screen.getByLabelText('GitHub repository');
  expect(input.required).toBe(false);
  expect(input.closest('form').noValidate).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Check health' }));
  expect(screen.getByRole('alert').textContent).toBe("'' is not a GitHub repository. Use owner/repo or a github.com URL.");
  expect(analyzeCalls()).toHaveLength(0);
});

it('shows an alert for an empty comparison without native validation or a compare request', async () => {
  await start();
  fireEvent.click(screen.getByRole('tab', { name: 'Compare' }));
  const input = screen.getByLabelText('GitHub repositories');
  expect(input.required).toBe(false);
  expect(input.closest('form').noValidate).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Compare health' }));
  expect(screen.getByRole('alert').textContent).toBe('Compare 2 to 4 unique GitHub repositories. Enter one per line or separate them with commas.');
  expect(fetch.mock.calls.some(([path]) => path.startsWith('/api/compare'))).toBe(false);
});

it.each([49, 50])('shows the low-requests banner only below 50 (%s remaining)', async remaining => {
  const original = handler;
  handler = (path, options) => path === '/api/status' ? ok({ ...status, token_configured: true, rate_limit: { ...status.rate_limit, remaining } }) : original(path, options);
  await start();
  const banner = screen.queryByText(/Only .* GitHub requests remain/);
  expect(Boolean(banner)).toBe(remaining === 49);
  if (banner) expect(banner.textContent).toContain('Only 49 GitHub requests remain');
});

it('fires the debounced slider request at exactly 250 ms, not at 249 ms', async () => {
  await start(); checkRepo();
  await screen.findByRole('link', { name: 'pallets/flask' });
  const before = analyzeCalls().length;
  vi.useFakeTimers();
  try {
    fireEvent.change(screen.getByRole('slider', { name: 'Activity' }), { target: { value: '65' } });
    expect(analyzeCalls()).toHaveLength(before);
    await act(async () => { await vi.advanceTimersByTimeAsync(249); });
    expect(analyzeCalls()).toHaveLength(before);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(analyzeCalls()).toHaveLength(before + 1);
    expect(analyzeCalls().at(-1)[0]).toContain('activity=65');
  } finally { vi.useRealTimers(); }
});

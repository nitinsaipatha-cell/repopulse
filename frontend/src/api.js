export const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/+$/, '');
export const DEFAULT_WEIGHTS = { activity: 25, bus_factor: 20, responsiveness: 20, documentation: 15, security: 20 };
export const CATEGORIES = [
  { key: 'activity', label: 'Activity' }, { key: 'bus_factor', label: 'Bus factor' },
  { key: 'responsiveness', label: 'Responsiveness' }, { key: 'documentation', label: 'Documentation' },
  { key: 'security', label: 'Security' },
];

export function normalizeRepo(reference) {
  const original = reference;
  let value = reference.trim();
  const invalid = () => { throw new Error(`'${original}' is not a GitHub repository. Use owner/repo or a github.com URL.`); };
  if (/^github:/i.test(value)) value = value.slice(7);
  else if (/^(git\+)?https?:\/\//i.test(value)) {
    const rawUrl = value.replace(/^git\+/i, '');
    let url;
    try { url = new URL(rawUrl); } catch { return invalid(); }
    const parts = rawUrl.match(/^https?:\/\/([^/?#]*)([^?#]*)/i);
    if (!parts || !/^github\.com$/i.test(parts[1]) || url.hostname.toLowerCase() !== 'github.com' || url.username || url.password || url.port) return invalid();
    value = parts[2].replace(/^\/+|\/+$/g, '').split('/').slice(0, 2).join('/');
  }
  const parts = value.split('/');
  if (parts.length === 2) parts[1] = parts[1].replace(/\.git$/i, '');
  if (parts.length !== 2 || parts.some(p => !/^[A-Za-z0-9_.-]+$/.test(p) || p === '.' || p === '..')) return invalid();
  return parts.join('/');
}

export function apiUrl(path, params = {}) {
  const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined));
  return `${API_BASE}/api${path}${query.size ? `?${query}` : ''}`;
}

export function absoluteApiUrl(path, params = {}) {
  return new URL(apiUrl(path, params), window.location.origin).href;
}

export async function request(path, { params, signal, body } = {}) {
  let response;
  try {
    response = await fetch(apiUrl(path, params), {
      signal, ...(body !== undefined ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('Could not reach RepoPulse. Check your connection and try again.');
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map(item => `${item.loc?.slice(1).join(' ') || 'Input'}: ${item.msg}`).join('. ')
      : `RepoPulse could not complete the request (HTTP ${response.status}). Please try again.`);
  }
  return response.json();
}

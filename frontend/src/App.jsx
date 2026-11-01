import React, { useEffect, useRef, useState } from 'react';
import { CATEGORIES, DEFAULT_WEIGHTS, request } from './api';
import Analyze from './Analyze';
import Compare from './Compare';
import Deps from './Deps';
import { ErrorMessage } from './shared';

const TABS = ['Check a repository', 'Compare', 'Scan dependencies'];
export default function App() {
  const [tab, setTab] = useState(0);
  const [config, setConfig] = useState(null);
  const [status, setStatus] = useState(null);
  const [startupError, setStartupError] = useState('');
  const [retry, setRetry] = useState(0);
  const [selectedRepo, setSelectedRepo] = useState(null);
  const tabButtons = useRef([]);
  useEffect(() => {
    const controller = new AbortController();
    setStartupError('');
    Promise.allSettled([request('/config', { signal: controller.signal }), request('/status', { signal: controller.signal })]).then(([configuration, health]) => {
      if (controller.signal.aborted) return;
      setConfig(configuration.status === 'fulfilled' ? configuration.value : { categories: CATEGORIES, default_weights: DEFAULT_WEIGHTS });
      setStatus(health.status === 'fulfilled' ? health.value : null);
      const errors = [configuration, health].filter(value => value.status === 'rejected').map(value => value.reason.message);
      if (errors.length) setStartupError(errors.join(' '));
    });
    return () => controller.abort();
  }, [retry]);
  function switchKey(event, index) {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % 3;
    else if (event.key === 'ArrowLeft') next = (index + 2) % 3;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = 2;
    else return;
    event.preventDefault(); setTab(next); tabButtons.current[next]?.focus();
  }
  function openRepository(repo) {
    setSelectedRepo({ repo }); setTab(0);
    tabButtons.current[0]?.focus();
  }
  return <><a className="skip-link" href="#main-content">Skip to content</a><header className="site-header"><div className="brand"><svg viewBox="0 0 45 36" aria-hidden="true"><path d="M0 20 H12 L17 10 L23 29 L28 15 L32 20 H45" fill="none" stroke="currentColor" strokeWidth="2" /></svg><h1>RepoPulse</h1></div><p className="tagline">A clearer read on repository health.</p><nav className="tabs" role="tablist" aria-label="Repository health tools">{TABS.map((label, index) => <button type="button" role="tab" id={`tab-${index}`} aria-controls={`panel-${index}`} aria-selected={tab === index} tabIndex={tab === index ? 0 : -1} key={label} ref={element => { tabButtons.current[index] = element; }} onClick={() => setTab(index)} onKeyDown={event => switchKey(event, index)}>{label}</button>)}</nav></header>
    <main id="main-content"><div className="startup-notices">{status && !status.token_configured && <aside className="notice"><p>No GitHub token is configured. GitHub allows 60 requests per hour. Set GITHUB_TOKEN on the backend to a classic personal access token with no scopes, then restart the API to raise the limit to 5,000/hour.</p></aside>}{status?.rate_limit && status.rate_limit.remaining < 50 && <aside className="notice"><p>Only {status.rate_limit.remaining} GitHub requests remain. Cached results are still available. The limit resets {new Date(status.rate_limit.reset * 1000).toLocaleString()}.</p></aside>}<ErrorMessage>{startupError}</ErrorMessage>{startupError && <button type="button" className="quiet" onClick={() => setRetry(value => value + 1)}>Retry connection</button>}</div>
      {!config ? <p role="status">Loading repository health tools.</p> : <><div id="panel-0" role="tabpanel" aria-labelledby="tab-0" hidden={tab !== 0}><Analyze config={config} selectedRepo={selectedRepo} /></div><div id="panel-1" role="tabpanel" aria-labelledby="tab-1" hidden={tab !== 1}><Compare config={config} /></div><div id="panel-2" role="tabpanel" aria-labelledby="tab-2" hidden={tab !== 2}><Deps openRepository={openRepository} /></div></>}
    </main><footer className="site-footer"><p>Explainable scores from public data. Missing measurements are excluded. A health score is one part of choosing a dependency.</p></footer></>;
}

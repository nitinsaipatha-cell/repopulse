import React, { useEffect, useState } from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { absoluteApiUrl, apiUrl, normalizeRepo, request } from './api';
import { AreaRadar, ErrorMessage, formatScore, Pulse, RiskTag, ScoreBar, useWeightedResult, WeightSliders } from './shared';

export default function Analyze({ config, selectedRepo }) {
  const [input, setInput] = useState('');
  const [path, setPath] = useState(null);
  const [weights, setWeights] = useState({ ...config.default_weights });
  const [refresh, setRefresh] = useState(0);
  const [validation, setValidation] = useState('');
  const [expanded, setExpanded] = useState({});
  const [history, setHistory] = useState([]);
  const [historyError, setHistoryError] = useState('');
  const [copyStatus, setCopyStatus] = useState('');
  const { result, loading, error } = useWeightedResult(path, weights, refresh);
  useEffect(() => {
    if (selectedRepo) {
      setInput(selectedRepo.repo); setValidation('');
      setPath({ route: `/analyze/${normalizeRepo(selectedRepo.repo)}` });
    }
  }, [selectedRepo]);
  useEffect(() => {
    if (!result) return;
    const controller = new AbortController();
    setHistory([]); setHistoryError('');
    request(`/history/${result.full_name}`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setHistory(value); })
      .catch(reason => { if (!controller.signal.aborted) setHistoryError(reason.message); });
    return () => controller.abort();
  }, [result?.full_name, result?.fetched_at]);
  function submit(event) {
    event.preventDefault(); setValidation(''); setCopyStatus('');
    try { setPath({ route: `/analyze/${normalizeRepo(input)}` }); }
    catch (reason) { setValidation(reason.message); }
  }
  async function copyBadge() {
    try {
      const url = absoluteApiUrl(`/badge/${result.full_name}.svg`);
      await navigator.clipboard.writeText(`[![Repo health](${url})](${result.repo.html_url || `https://github.com/${result.full_name}`})`);
      setCopyStatus('README badge copied.');
    } catch { setCopyStatus('Could not copy the badge. Check your browser clipboard permissions and try again.'); }
  }
  return <div>
    <section className="intro"><h2>Check a repository</h2><p>Understand the health of a project before you depend on it.</p>
      <form noValidate onSubmit={submit}><label htmlFor="repository">GitHub repository</label><div className="input-action"><input id="repository" value={input} onChange={event => setInput(event.target.value)} placeholder="pallets/flask or a GitHub URL" /><button type="submit">Check health</button></div></form>
      <ErrorMessage>{validation || error}</ErrorMessage>
      {loading && <p role="status">Collecting commits, issues, contributors and security data from GitHub. This takes 5 to 20 seconds the first time.</p>}
    </section>
    {result && <div className={loading ? 'result updating' : 'result'} aria-busy={loading}>
      <section className="repository-result"><div className="section-heading"><h2><a href={result.repo.html_url || `https://github.com/${result.full_name}`} target="_blank" rel="noreferrer">{result.full_name}</a></h2><RiskTag risk={result.risk} /></div>
        <p>{result.repo.description || 'No repository description provided.'}</p>
        <ul className="repo-facts"><li>{result.repo.stars ?? 'n/a'} stars</li><li>{result.repo.forks ?? 'n/a'} forks</li><li>{result.repo.language || 'Language n/a'}</li><li>{result.repo.license || 'License n/a'}</li></ul>
        <Pulse score={result.score} risk={result.risk} />
        <div className="findings"><div><h3>Needs attention</h3>{[...result.overrides, ...result.concerns].length ? <ul>{[...result.overrides, ...result.concerns].map((text, i) => <li key={i}>{text}</li>)}</ul> : <p>No concerns identified from the available data.</p>}</div>
          <div><h3>Going well</h3><ul>{result.strengths.map((text, i) => <li key={i}>{text}</li>)}</ul>{!result.strengths.length && <p>No strengths identified from the available data.</p>}</div></div>
        {result.adjustments.map((item, i) => <p className="maturity-note" key={i}>Maturity adjustment: {item.note} Activity changed from {formatScore(item.before)} to {formatScore(item.after)}.</p>)}
      </section>
      <section><h3>Score by area</h3><div className="area-layout"><div>{config.categories.map(({ key, label }) => {
        const category = result.categories[key];
        return <div className="area" key={key}><button type="button" className="area-toggle" aria-expanded={!!expanded[key]} aria-controls={`metrics-${key}`} onClick={() => setExpanded(old => ({ ...old, [key]: !old[key] }))}>
          <span>{label}<small>{result.weights[key].toFixed(1)}% weight share</small></span><ScoreBar score={category.score} /><strong>{formatScore(category.score)}</strong><span className="expand-label">{expanded[key] ? 'Hide' : 'Details'}</span></button>
          {expanded[key] && <ul className="metrics" id={`metrics-${key}`}>{category.metrics.map(metric => <li key={metric.key}><div><strong>{metric.label}</strong><span>{metric.detail}</span></div><ScoreBar score={metric.score == null ? null : metric.score * 100} /><span>{metric.score == null ? 'n/a' : `${(metric.score * 100).toFixed(1)} / 100`}</span></li>)}</ul>}
        </div>;
      })}</div><AreaRadar results={[result]} categories={config.categories} /></div></section>
      <WeightSliders weights={weights} setWeights={setWeights} config={config} id="analyze-weight" />
      <section><h3>Score over time</h3><ErrorMessage>{historyError}</ErrorMessage>{history.length >= 2 ? <figure className="chart history-chart"><figcaption>Default-priority scores from fresh data collections</figcaption><div className="chart-canvas" role="img" aria-label="Repository score over time"><ResponsiveContainer width="100%" height="100%"><LineChart data={history.map(point => ({ ...point, date: new Date(point.ts).toLocaleDateString() }))} margin={{ top: 12, right: 20, bottom: 10, left: 0 }}><CartesianGrid stroke="#d3dcdf" /><XAxis dataKey="date" /><YAxis domain={[0, 100]} /><Tooltip /><Line type="monotone" dataKey="score" stroke="#0e6b73" strokeWidth={2} isAnimationActive={false} connectNulls={false} /></LineChart></ResponsiveContainer></div></figure> : !historyError && <p>Refresh the data on another occasion to start a trend. At least two history points are needed.</p>}</section>
      {result.scorecard && <section><h3>An independent cross-check</h3><p>Our score: {formatScore(result.score)} / 100. OpenSSF Scorecard: {formatScore(result.scorecard.score)} / 10.</p><p>The two should agree in direction, not in number. Scorecard is a cross-check and is never part of our score.</p>{result.scorecard.date && <p>Scorecard date: {result.scorecard.date}</p>}</section>}
      <section><h3>Use this report</h3><div className="actions"><button type="button" disabled={loading} onClick={() => setRefresh(value => value + 1)}>Refresh data</button><a className="button quiet" href={apiUrl(`/report/${result.full_name}.pdf`, weights)}>Download PDF report</a><a className="button quiet" href={apiUrl(`/report/${result.full_name}.csv`, weights)}>Download CSV</a><button type="button" className="quiet" onClick={copyBadge}>Copy README badge</button></div><p role="status">{copyStatus}</p><img className="live-badge" src={apiUrl(`/badge/${result.full_name}.svg`)} alt={`Live repository health badge for ${result.full_name}`} /><p className="muted">{result.from_cache ? 'Using cached data' : 'Fresh data collected'} · {new Date(result.fetched_at).toLocaleString()}</p></section>
    </div>}
  </div>;
}

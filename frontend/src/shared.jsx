import React, { useEffect, useRef, useState } from 'react';
import { ResponsiveContainer, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Legend } from 'recharts';
import { CATEGORIES, request } from './api';

export const formatScore = value => value == null ? 'n/a' : Number(value).toFixed(1);
export function normalizedShares(weights) {
  const total = Object.values(weights).reduce((sum, value) => sum + value, 0);
  return total ? Object.fromEntries(Object.entries(weights).map(([key, value]) => [key, value * 100 / total])) : null;
}

export function useWeightedResult(path, weights, refresh) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const lastRefresh = useRef(refresh);
  const serialized = JSON.stringify(weights);
  useEffect(() => {
    const id = ++sequence.current;
    if (!path) return;
    const controller = new AbortController();
    setLoading(true); setError('');
    const timer = setTimeout(() => {
      const refreshData = refresh !== lastRefresh.current;
      lastRefresh.current = refresh;
      request(path.route, { params: { ...path.params, ...JSON.parse(serialized), ...(refreshData ? { refresh: true } : {}) }, signal: controller.signal })
        .then(value => { if (id === sequence.current) setResult(value); })
        .catch(reason => { if (id === sequence.current && reason.name !== 'AbortError') setError(reason.message); })
        .finally(() => { if (id === sequence.current) setLoading(false); });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); sequence.current++; };
  }, [path, serialized, refresh]);
  return { result, loading, error };
}

export function RiskTag({ risk }) {
  return <span className={`risk-tag risk-${risk?.toLowerCase() || 'unknown'}`}>{risk ? `${risk} risk` : 'Not scored'}</span>;
}
export function ScoreBar({ score, risk }) {
  return <span className={`score-bar ${score == null ? 'missing' : ''} ${risk ? `risk-${risk.toLowerCase()}` : ''}`} aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(100, score ?? 0))}%` }} /></span>;
}
export function Pulse({ score, risk }) {
  const amplitude = Math.max(0, Math.min(100, score ?? 0)) * .5;
  const points = `0,65 100,65 130,${65 - amplitude * .2} 150,65 210,65 235,${65 + amplitude * .35} 262,${65 - amplitude} 290,${65 + amplitude * .7} 315,65 355,65 375,${65 - amplitude * .25} 400,65 500,65`;
  return <div className={`pulse risk-${risk?.toLowerCase() || 'unknown'}`}>
    <svg viewBox="0 0 500 130" role="img" aria-label={`Repository pulse: ${formatScore(score)} out of 100, ${risk || 'unknown'} risk`} preserveAspectRatio="none">
      <polyline key={`${score}-${risk}`} points={points} fill="none" stroke="currentColor" strokeWidth="2.5" vectorEffect="non-scaling-stroke" pathLength="1" />
    </svg><div className="pulse-score"><strong>{formatScore(score)}</strong><span>out of 100</span></div>
  </div>;
}
export function WeightSliders({ weights, setWeights, config, id }) {
  const categories = config?.categories || CATEGORIES;
  const defaults = config?.default_weights;
  const shares = normalizedShares(weights) || defaults;
  return <section className="priorities"><div className="section-heading"><h3>Try different priorities</h3><button type="button" className="quiet" onClick={() => setWeights({ ...defaults })}>Reset to defaults</button></div>
    <p>Adjust what matters to you. Scores update from cached measurements.</p>
    <div className="sliders">{categories.map(({ key, label }) => <div className="slider-row" key={key}>
      <label htmlFor={`${id}-${key}`}>{label}</label><input id={`${id}-${key}`} type="range" min="0" max="100" step="5" value={weights[key]} onChange={event => setWeights(old => ({ ...old, [key]: Number(event.target.value) }))} />
      <output htmlFor={`${id}-${key}`}>{weights[key]} <span>({(shares?.[key] ?? 0).toFixed(1)}% share)</span></output>
    </div>)}</div>
  </section>;
}
const CHART_COLORS = ['#0e6b73', '#645587', '#386a92', '#7c643e'];
export function AreaRadar({ results, categories = CATEGORIES }) {
  const data = categories.map(({ key, label }) => Object.fromEntries([['area', label], ...results.map((result, i) => [`repo${i}`, result.categories[key]?.score ?? null])]));
  return <figure className="chart"><figcaption>Health across five areas</figcaption><div className="chart-canvas" role="img" aria-label={`Category radar chart for ${results.map(r => r.full_name).join(', ')}. Values are also listed in the score table.`}>
    <ResponsiveContainer width="100%" height="100%"><RadarChart data={data} outerRadius="68%"><PolarGrid /><PolarAngleAxis dataKey="area" tick={{ fill: '#55666e', fontSize: 12 }} /><PolarRadiusAxis domain={[0, 100]} tickCount={3} />
      {results.map((result, i) => <Radar key={result.full_name} name={result.full_name} dataKey={`repo${i}`} stroke={CHART_COLORS[i]} fill={CHART_COLORS[i]} fillOpacity={results.length === 1 ? .12 : .04} isAnimationActive={false} />)}
      {results.length > 1 && <Legend />}
    </RadarChart></ResponsiveContainer></div></figure>;
}
export function ErrorMessage({ children }) { return children ? <p className="error" role="alert">{children}</p> : null; }

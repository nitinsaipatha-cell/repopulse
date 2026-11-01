import React, { useState } from 'react';
import { normalizeRepo } from './api';
import { AreaRadar, ErrorMessage, formatScore, RiskTag, ScoreBar, useWeightedResult, WeightSliders } from './shared';

export default function Compare({ config }) {
  const [input, setInput] = useState('');
  const [path, setPath] = useState(null);
  const [weights, setWeights] = useState({ ...config.default_weights });
  const [validation, setValidation] = useState('');
  const { result, loading, error } = useWeightedResult(path, weights, 0);
  function submit(event) {
    event.preventDefault(); setValidation('');
    try {
      const refs = input.split(/[\n,]+/).map(value => value.trim()).filter(Boolean).map(normalizeRepo);
      if (refs.length < 2 || refs.length > 4 || new Set(refs.map(r => r.toLowerCase())).size !== refs.length) throw new Error('Compare 2 to 4 unique GitHub repositories. Enter one per line or separate them with commas.');
      setPath({ route: '/compare', params: { repos: refs.join(',') } });
    } catch (reason) { setValidation(reason.message); }
  }
  const ranked = result ? [...result.repos].sort((a, b) => (b.score ?? -1) - (a.score ?? -1)) : [];
  const winner = ranked[0];
  const tied = winner && ranked.filter(repo => repo.score === winner.score);
  return <div><section className="intro"><h2>Compare repositories</h2><p>Compare health side by side, then see how the ranking holds up when priorities change.</p><form noValidate onSubmit={submit}><label htmlFor="compare-repos">GitHub repositories</label><textarea id="compare-repos" rows="4" value={input} onChange={event => setInput(event.target.value)} placeholder={'pallets/flask\ndjango/django'} /><button type="submit">Compare health</button></form><ErrorMessage>{validation || error}</ErrorMessage>{loading && <p role="status">Collecting repository data and checking ranking stability.</p>}</section>
    {result && <div className={loading ? 'result updating' : 'result'} aria-busy={loading}><section><h3>{winner.score == null ? 'No repositories could be scored' : tied.length > 1 ? `${tied.map(r => r.full_name).join(' and ')} share the highest score` : `${winner.full_name} has the highest score`}</h3><p>{result.sensitivity?.ranking_stable ? 'The ranking is stable across 300 trials with different category weights.' : 'The ranking depends on weights. Different priorities can change the order.'}</p>
      <div className="table-scroll" role="region" aria-label="Repository comparison" tabIndex="0"><table><caption>Repository health comparison</caption><thead><tr><th scope="col">Repository</th><th scope="col">Score</th><th scope="col">Risk</th>{config.categories.map(c => <th scope="col" key={c.key}>{c.label}</th>)}<th scope="col">Ranked first</th></tr></thead><tbody>{ranked.map(repo => {
        const stability = result.sensitivity?.repos.find(item => item.full_name === repo.full_name);
        return <tr key={repo.full_name}><th scope="row"><a href={repo.repo.html_url || `https://github.com/${repo.full_name}`} target="_blank" rel="noreferrer">{repo.full_name}</a></th><td><strong>{formatScore(repo.score)}</strong></td><td><RiskTag risk={repo.risk} /></td>{config.categories.map(c => <td key={c.key}><span>{formatScore(repo.categories[c.key]?.score)}</span><ScoreBar score={repo.categories[c.key]?.score} /></td>)}<td>{stability ? `${stability.first_pct.toFixed(1)}%` : 'n/a'}</td></tr>;
      })}</tbody></table></div><AreaRadar results={result.repos} categories={config.categories} /></section><WeightSliders weights={weights} setWeights={setWeights} config={config} id="compare-weight" /></div>}
  </div>;
}

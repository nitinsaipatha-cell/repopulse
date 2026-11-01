import React, { useEffect, useRef, useState } from 'react';
import { apiUrl, request } from './api';
import { ErrorMessage, formatScore, RiskTag, ScoreBar } from './shared';

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Could not read the file. Choose it again and retry.'));
    reader.readAsText(file);
  });
}
export function sortScanRows(rows, sort) {
  return [...rows].sort((a, b) => {
    if (sort === 'name') return a.name.localeCompare(b.name);
    if ((a.score == null) !== (b.score == null)) return a.score == null ? 1 : -1;
    if (sort === 'risk') {
      const order = { High: 0, Medium: 1, Low: 2 };
      const difference = (order[a.risk] ?? 3) - (order[b.risk] ?? 3);
      if (difference) return difference;
    }
    return (a.score ?? Infinity) - (b.score ?? Infinity) || a.name.localeCompare(b.name);
  });
}
export default function Deps({ openRepository }) {
  const [file, setFile] = useState(null);
  const [includeDev, setIncludeDev] = useState(false);
  const [jobId, setJobId] = useState('');
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const [sort, setSort] = useState('risk');
  const [dragging, setDragging] = useState(false);
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController();
    let timer;
    async function poll() {
      try {
        const value = await request(`/scan/${jobId}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setJob(value);
        if (value.status === 'running') timer = setTimeout(poll, 1000);
      } catch (reason) { if (!controller.signal.aborted) { setError(reason.message); setJob(old => ({ ...old, status: 'failed', message: reason.message })); } }
    }
    timer = setTimeout(poll, 1000);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [jobId]);
  async function submit(event) {
    event.preventDefault(); setError('');
    if (!file) { setError('Choose a package.json or requirements.txt file first.'); return; }
    const id = ++sequence.current;
    setStarting(true); setJobId(''); setJob(null);
    try {
      const content = await readFile(file);
      const started = await request('/scan', { body: { filename: file.name, content, include_dev: includeDev } });
      if (id !== sequence.current) return;
      setJobId(started.job_id);
      setJob({ status: 'running', total: started.total, done: 0, rows: [], truncated: started.truncated, filename: file.name, message: null });
    } catch (reason) { if (id === sequence.current) setError(reason.message); }
    finally { if (id === sequence.current) setStarting(false); }
  }
  const busy = starting || job?.status === 'running';
  return <div><section className="intro"><h2>Scan dependencies</h2><p>Find the dependencies that need attention, using repository health and known vulnerabilities.</p><form onSubmit={submit}><div className={`drop-zone ${dragging ? 'dragging' : ''}`} onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (!busy) setFile(event.dataTransfer.files[0] || null); }}><label htmlFor="manifest">Drag and drop a package.json or requirements.txt, or choose a file</label><input type="file" id="manifest" accept=".json,.txt" disabled={busy} onChange={event => setFile(event.target.files[0] || null)} /><p>{file ? `Selected: ${file.name}` : 'No file selected'}</p></div><label className="checkbox-label"><input type="checkbox" checked={includeDev} disabled={busy} onChange={event => setIncludeDev(event.target.checked)} />Include devDependencies</label><button type="submit" disabled={busy}>Scan dependencies</button></form><p>Version ranges are checked at their lowest version. When no version is declared, the latest registry version is checked.</p><ErrorMessage>{error || (job?.status === 'failed' ? job.message || 'The scan failed. Please try again.' : '')}</ErrorMessage>
      {starting && <p role="status">Reading the manifest and starting the scan.</p>}
      {job && <div className="scan-progress" role="status"><label htmlFor="scan-progress">{job.done} of {job.total} checked</label><progress id="scan-progress" max={Math.max(1, job.total)} value={job.done} /></div>}
      {job?.message && job.status !== 'failed' && <p role="alert" className="notice">{job.message}</p>}
      {job?.truncated && <p className="notice">This manifest exceeds the scan limit. Only the first {job.total} packages are included.</p>}
    </section>
    {job?.status === 'done' && <section><h3>Dependency health</h3><p>{job.done} packages checked · {job.rows.filter(r => r.risk === 'High').length} High · {job.rows.filter(r => r.risk === 'Medium').length} Medium · {job.rows.filter(r => r.risk === 'Low').length} Low · {job.rows.filter(r => r.score == null).length} Not scored</p><div className="section-heading"><div><label htmlFor="scan-sort">Sort dependencies</label><select id="scan-sort" value={sort} onChange={event => setSort(event.target.value)}><option value="risk">Riskiest first</option><option value="score">Lowest score</option><option value="name">Name</option></select></div><a className="button quiet" href={apiUrl(`/scan/${jobId}/csv`)}>Download scan CSV</a></div>
      <div className="table-scroll" role="region" aria-label="Dependency scan results" tabIndex="0"><table><caption>{job.filename}</caption><thead><tr><th scope="col">Package</th><th scope="col">Declared version</th><th scope="col">Score</th><th scope="col">Risk</th><th scope="col">Why</th></tr></thead><tbody>{sortScanRows(job.rows, sort).map(row => <tr key={`${row.ecosystem}-${row.name}`}><th scope="row">{row.name}{row.dev && <small>Development dependency</small>}</th><td>{row.declared_version || 'Not declared'}</td><td>{row.score == null ? 'Not scored' : <><strong>{formatScore(row.score)}</strong><ScoreBar score={row.score} risk={row.risk} /></>}</td><td><RiskTag risk={row.risk} /></td><td className="why">{row.vuln_count > 0 && <p className="vulnerability">{row.vuln_count} known {row.vuln_count === 1 ? 'vulnerability' : 'vulnerabilities'} at the checked version{row.high_vuln_count ? `, including ${row.high_vuln_count} high or critical` : ''}. {row.vuln_ids?.join(', ')}</p>}{row.note && <p>{row.note}</p>}{row.concerns?.slice(0, 2).map((text, i) => <p key={i}>{text}</p>)}{row.repo && <button type="button" className="text-button" onClick={() => openRepository(row.repo)}>Check {row.repo}</button>}</td></tr>)}</tbody></table></div>
    </section>}
  </div>;
}

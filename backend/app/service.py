"""Cached repository analysis, comparison, and persisted background scans."""
import asyncio
import secrets
from datetime import datetime, timedelta

from app.collectors import collect
from app.config import Settings
from app.deps import parse_manifest, scan_dependencies
from app.scoring import score, sensitivity
from app.utils import parse_repo_ref, utc_now


class Service:
    def __init__(self, db, github, external, settings=None, clock=utc_now):
        self.db, self.github, self.external = db, github, external
        self.settings = settings or Settings()
        self.clock = clock
        self.locks = {}
        self.aliases = {}
        self.tasks = set()

    async def analyze(self, reference, weights=None, refresh=False):
        name = parse_repo_ref(reference).lower()
        name = self.aliases.get(name, name)
        lock = self.locks.setdefault(name, asyncio.Lock())
        async with lock:
            now = self.clock()
            cached = self.db.get_cache(name)
            fresh = cached is not None and now - datetime.fromisoformat(cached['fetched_at'].replace('Z', '+00:00')) < timedelta(hours=self.settings.cache_ttl_hours)
            if fresh and not refresh:
                raw = cached['raw']
                from_cache = True
            else:
                owner, repo = name.split('/')
                raw = await collect(self.github, self.external, owner, repo, now)
                canonical = raw['repo']['full_name'].lower()
                self.aliases[name] = canonical
                self.locks[canonical] = lock
                self.db.put_cache(canonical, raw['fetched_at'], raw)
                if name != canonical:
                    self.db.put_cache(name, raw['fetched_at'], raw)
                baseline = score(raw, now=now)
                self.db.add_history(canonical, raw['fetched_at'], baseline['score'], baseline['risk'], baseline['category_scores'])
                from_cache = False
            result = score(raw, weights, now)
            result.update(from_cache=from_cache, fetched_at=raw['fetched_at'])
            return result

    async def compare(self, references, weights=None, refresh=False):
        results = await asyncio.gather(*(self.analyze(ref, weights, refresh) for ref in references))
        return {'repos': results, 'sensitivity': sensitivity(results, self.clock()) if len(results) >= 2 else None}

    def history(self, reference):
        name = parse_repo_ref(reference).lower()
        return self.db.get_history(self.aliases.get(name, name))

    def start_scan(self, filename, content, include_dev=False):
        packages = parse_manifest(filename, content, include_dev)
        if not packages:
            raise ValueError('No dependencies found. Upload a non-empty package.json or requirements.txt.')
        truncated = len(packages) > self.settings.max_scan_deps
        packages = packages[:self.settings.max_scan_deps]
        job_id, created = secrets.token_hex(6), self.clock().isoformat()
        payload = {'filename': filename, 'rows': [], 'truncated': truncated, 'message': None}
        self.db.save_scan(job_id, created, 'running', len(packages), 0, payload)

        async def run():
            async def progress(rows, message):
                payload.update(rows=rows, message=message)
                self.db.save_scan(job_id, created, 'running', len(packages), len(rows), payload)
            try:
                rows, message = await scan_dependencies(packages, self, progress)
                payload.update(rows=rows, message=message)
                self.db.save_scan(job_id, created, 'done', len(packages), len(rows), payload)
            except asyncio.CancelledError:
                payload['message'] = 'Dependency scan was cancelled.'
                self.db.save_scan(job_id, created, 'failed', len(packages), len(payload['rows']), payload)
                raise
            except Exception as exc:
                payload['message'] = f'Dependency scan failed: {exc}'
                self.db.save_scan(job_id, created, 'failed', len(packages), len(payload['rows']), payload)
        task = asyncio.create_task(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return {'job_id': job_id, 'total': len(packages), 'truncated': truncated}

    def get_scan(self, job_id):
        job = self.db.get_scan(job_id)
        if job is None:
            return None
        return {'status': job['status'], 'total': job['total'], 'done': job['done'], **job['payload']}

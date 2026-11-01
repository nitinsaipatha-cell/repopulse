"""RepoPulse HTTP API. Run with uvicorn app.main:app."""
import asyncio
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.badge import repository_badge
from app.config import Settings
from app.db import Database
from app.external import ExternalClient
from app.github_client import GitHubClient, GitHubError
from app.ratelimit import RateLimitMiddleware
from app.report import report_csv, report_pdf, scan_csv
from app.scoring import CATEGORIES, DEFAULT_WEIGHTS, RISK_THRESHOLDS
from app.service import Service
from app.utils import parse_repo_ref

Weight = Annotated[float, Query(ge=0, le=100, allow_inf_nan=False)]


def query_weights(activity: Weight = 25, bus_factor: Weight = 20,
                  responsiveness: Weight = 20, documentation: Weight = 15,
                  security: Weight = 20):
    return dict(activity=activity, bus_factor=bus_factor, responsiveness=responsiveness,
                documentation=documentation, security=security)


class ScanRequest(BaseModel):
    filename: str
    content: str
    include_dev: bool = False


def create_app(service=None, settings=None, rate_clock=None):
    settings = settings or (service.settings if service is not None else Settings())

    @asynccontextmanager
    async def lifespan(application):
        owned = service is None
        if owned:
            db = Database(settings.db_path)
            github = GitHubClient(settings.github_token)
            external = ExternalClient()
            application.state.service = Service(db, github, external, settings)
        try:
            yield
        finally:
            if owned:
                active = application.state.service
                tasks = list(active.tasks)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await active.github.close()
                await active.external.close()
                active.db.close()

    application = FastAPI(title='RepoPulse', lifespan=lifespan,
                          docs_url='/api/docs', redoc_url=None, openapi_url='/api/openapi.json',
                          swagger_ui_oauth2_redirect_url='/api/docs/oauth2-redirect')
    if service is not None:
        application.state.service = service

    # Starlette wraps the most recently registered middleware around earlier ones.
    # Register the limiter first so CORS also wraps its early 429 responses.
    limiter_options = {'limit': settings.rate_limit_per_min}
    if rate_clock is not None:
        limiter_options['clock'] = rate_clock
    application.add_middleware(RateLimitMiddleware, **limiter_options)
    application.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                               allow_methods=['*'], allow_headers=['*'])

    @application.exception_handler(GitHubError)
    async def github_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=exc.status_code)

    def active(request: Request):
        return request.app.state.service

    def reference(owner, repo):
        try:
            return parse_repo_ref(f'{owner}/{repo}')
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @application.get('/api/status')
    async def status(svc=Depends(active)):
        rate = None
        try:
            data = await svc.github.get('/rate_limit')
            core = data['resources']['core']
            rate = {key: core[key] for key in ('limit', 'remaining', 'reset')}
        except (GitHubError, KeyError, TypeError):
            pass
        return {'ok': True, 'token_configured': bool(svc.github.token), 'rate_limit': rate}

    @application.get('/api/config')
    async def config():
        return {'categories': [{'key': key, 'label': label} for key, label in CATEGORIES.items()],
                'default_weights': DEFAULT_WEIGHTS, 'risk_thresholds': RISK_THRESHOLDS}

    @application.get('/api/analyze/{owner}/{repo}')
    async def analyze(owner: str, repo: str, refresh: bool = False,
                      weights=Depends(query_weights), svc=Depends(active)):
        return await svc.analyze(reference(owner, repo), weights, refresh)

    @application.get('/api/compare')
    async def compare(repos: str, refresh: bool = False, weights=Depends(query_weights), svc=Depends(active)):
        try:
            references = [parse_repo_ref(value.strip()) for value in repos.split(',')]
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not 2 <= len(references) <= 4 or len({ref.lower() for ref in references}) != len(references):
            raise HTTPException(422, 'Compare 2 to 4 unique GitHub repositories.')
        return await svc.compare(references, weights, refresh)

    @application.get('/api/history/{owner}/{repo}')
    async def history(owner: str, repo: str, svc=Depends(active)):
        return svc.history(reference(owner, repo))

    @application.get('/api/badge/{owner}/{repo}.svg')
    async def badge(owner: str, repo: str, svc=Depends(active)):
        svg, headers = await repository_badge(svc, reference(owner, repo))
        return Response(svg, media_type='image/svg+xml', headers=headers)

    @application.get('/api/report/{owner}/{repo}.pdf')
    async def pdf(owner: str, repo: str, weights=Depends(query_weights), svc=Depends(active)):
        ref = reference(owner, repo)
        result = await svc.analyze(ref, weights)
        return Response(report_pdf(result), media_type='application/pdf',
                        headers={'Content-Disposition': f'attachment; filename="{ref.replace("/", "-")}.pdf"'})

    @application.get('/api/report/{owner}/{repo}.csv')
    async def csv(owner: str, repo: str, weights=Depends(query_weights), svc=Depends(active)):
        ref = reference(owner, repo)
        result = await svc.analyze(ref, weights)
        return Response(report_csv(result), media_type='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="{ref.replace("/", "-")}.csv"'})

    @application.post('/api/scan')
    async def scan(body: ScanRequest, svc=Depends(active)):
        try:
            return svc.start_scan(body.filename, body.content, body.include_dev)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def find_scan(svc, job_id):
        job = svc.get_scan(job_id)
        if job is None:
            raise HTTPException(404, 'Scan not found.')
        return job

    @application.get('/api/scan/{job_id}')
    async def scan_status(job_id: str, svc=Depends(active)):
        return find_scan(svc, job_id)

    @application.get('/api/scan/{job_id}/csv')
    async def scan_export(job_id: str, svc=Depends(active)):
        return Response(scan_csv(find_scan(svc, job_id)), media_type='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="dependency-scan.csv"'})

    return application


app = create_app()

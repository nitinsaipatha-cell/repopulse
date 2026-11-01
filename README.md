# RepoPulse

RepoPulse turns public GitHub measurements into an explainable repository health score from 0 to 100 and a Low, Medium, or High risk rating. It is a semester project designed to make each result testable and defensible. Machine learning is out of scope.

## Features

- Check one repository, inspect every metric, and read concerns, strengths, and risk overrides.
- Adjust five category weights and rescore cached measurements without extra GitHub requests.
- Compare 2 to 4 repositories with an overlaid radar chart and a deterministic 300-trial ranking sensitivity analysis.
- Upload package.json or requirements.txt, map packages to GitHub, and check OSV vulnerabilities at the declared base version, or latest version when none is declared.
- View score history and its trend line. Stable, established libraries can receive an Activity maturity adjustment.
- Download PDF and metric CSV reports, dependency scan CSV, and an embeddable SVG badge.
- Run a CLI dependency risk gate in your own GitHub Actions workflow.
- Run locally with Docker or Python/Node, or publish a static frontend on GitHub Pages with the API on Render.

## Requirements and fixed stack

Use Python 3.12 and Node.js 20. Docker instructions require Docker Engine/Desktop with Compose. Versions are pinned in backend/requirements.txt, backend/requirements-dev.txt, and frontend/package.json; install the frontend with npm ci to use its lockfile.

Backend: FastAPI 0.115.6, uvicorn 0.34.0, httpx 0.28.1, pydantic 2.10.4, reportlab 4.2.5, and standard-library sqlite3. Frontend: React/React DOM 18.3.1, Vite 5.4.11, and Recharts 2.15.0, with one plain CSS stylesheet and no UI framework, router, or state library. Tests use pytest 8.3.4, pytest-asyncio 0.25.0, Vitest 2.1.8, jsdom 25.0.1, and Testing Library React 16.1.0. pypdf is a development-only dependency for PDF text assertions.

## Optional GitHub token

An unauthenticated GitHub client normally has 60 requests per hour. A token is strongly recommended because collecting a repository uses multiple requests. The application displays whether a token is configured and the remaining request count; it never sends the token to the frontend.

1. Open GitHub account **Settings > Developer settings > Personal access tokens > Tokens (classic)**.
2. Choose **Generate new token > Generate new token (classic)**. Give it a descriptive name and an expiry date.
3. Leave every scope unchecked: this project reads public repository data. Generate the token.
4. Copy .env.example to .env. Edit .env privately and put the value after GITHUB_TOKEN=. Do not place it in frontend configuration, commands saved in shell history, screenshots, reports, commits, or logs.
5. Restart the API after changing its environment. GitHub normally allows 5,000 requests per hour for authenticated user requests.

GitHub documents the classic-token creation flow in [Managing personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens). A token is not required to run tests. On Render, enter it through the dashboard instead of uploading .env.

## Run with Docker

From the repository root:

```sh
cp .env.example .env
# Edit .env privately if you want to supply GITHUB_TOKEN.
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080). Nginx serves the frontend and proxies /api/ to the backend, preserving that prefix and allowing a 120-second read timeout. The backend listens internally on port 8000; it is not published directly to the host.

The named repopulse-data volume stores SQLite at /data/repopulse.db. Compose overrides DB_PATH from .env with this path. The volume survives docker compose down. Do not remove the volume if you want to retain local cache/history. The local Compose setup needs no separate frontend API URL because calls use the same origin.

```sh
docker compose logs backend
docker compose down
```

Docker build contexts exclude local environment files, database files, caches, and virtual environments. The frontend image builds with node:20-alpine and runs with nginx:1.27-alpine; the backend uses python:3.12-slim.

## Run locally

Start in the repository root:

```sh
cp .env.example .env
cd backend
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
set -a
. ../.env
set +a
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The application reads process environment variables, not .env automatically. The set -a block exports the local .env values. These commands use a POSIX shell; on Windows, activate the environment and set the same process variables using your shell's syntax.

In a second terminal, from the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Vite proxies /api to http://localhost:8000. Keep the backend terminal running.

## First-run check and validation

For Docker, use port 8080 below. For local Python, replace 8080 with 8000.

```sh
curl -f http://localhost:8080/api/config
curl -f http://localhost:8080/api/status
curl -f http://localhost:8080/api/analyze/pallets/flask
```

1. Confirm config lists five categories. Confirm status reports ok and the expected token_configured value; it exposes no token value.
2. Check pallets/flask in the UI. First collection commonly takes 5 to 20 seconds, depending on API latency. The live check on 1 November 2026 returned 73.9 / Medium. This is an observed result, not a promise of Low risk; public data and elapsed-time metrics change.
3. Change a priority. The next result should have from_cache=true and updated normalised weights. The offline API test also verifies zero extra GitHub calls for cached custom-weight analysis.
4. Refresh data and confirm history gains a point. A cache hit should not add one.
5. Compare two clearly different projects and inspect stability. Check an archived or long-abandoned repository and inspect the High-risk override.
6. Scan a manifest containing a version with an OSV advisory, a missing registry package, and a package without a GitHub link. Confirm the explanations, ordering, and scan CSV.
7. Download the PDF and metric CSV, copy the README badge, and inspect the live badge. Scorecard is only an independent cross-check.

Observed live results from 1 November 2026 (default weights; results may change):

| Repository | Score | Risk |
| --- | ---: | --- |
| django/django | 91.2 | Low |
| psf/requests | 83.2 | Low |
| pallets/click | 82.2 | Low |
| pallets/flask | 73.9 | Medium |

For an oral exam, trace one raw measurement through its ramp, category average, maturity adjustment if applicable, normalised weighting, and any risk override. Compare the original public data with the plain-language findings. A health score is evidence for a decision, not a guarantee that code is safe or vulnerability-free.

## Configuration

| Backend variable | Default | Meaning |
| --- | --- | --- |
| GITHUB_TOKEN | empty | Optional public-data authentication; backend only |
| DB_PATH | data/repopulse.db | SQLite path relative to the backend working directory |
| CACHE_TTL_HOURS | 6 | Raw measurement reuse period |
| MAX_SCAN_DEPS | 50 | Maximum packages included in a scan |
| RATE_LIMIT_PER_MIN | 30 | Requests per IP for expensive routes; 0 disables |
| CORS_ORIGINS | http://localhost:5173 | Comma-separated browser origins, with no paths |

| Frontend build/dev variable | Default | Meaning |
| --- | --- | --- |
| VITE_BASE | / | Asset base path; /repopulse/ for this project's Pages site |
| VITE_API_BASE | empty | API origin, without /api; empty means same origin; trailing slashes are stripped |
| VITE_PROXY | http://localhost:8000 | Development proxy target for /api |

All VITE variables can become public browser code. They must never contain credentials. VITE_API_BASE is a build-time value: rebuild and redeploy after changing API_URL in GitHub. Docker frontend builds also accept VITE_BASE and VITE_API_BASE as build arguments.

## Scoring

Each metric is scored from 0 to 1. lin(x, lo, hi) is 0 at or below lo, 1 at or above hi, and linear between. inv(x, good, bad) = 1 - lin(x, good, bad). Unavailable metrics are null and excluded from the category average. Category scores are the mean of available metrics times 100, rounded to one decimal.

| Category | Default weight |
| --- | ---: |
| Activity | 25% |
| Bus factor | 20% |
| Responsiveness | 20% |
| Documentation | 15% |
| Security | 20% |

User weights are clamped to zero or above and normalised to percentages; all-zero weights restore defaults. The final score is the weighted average of available categories, redistributing missing-category weight over the rest, rounded to one decimal.

| Category / metric | Rule |
| --- | --- |
| Activity: commits in 90 days | lin(count, 0, 30); collection caps at 300 and displays + |
| Activity: days since commit | inv(days, 30, 365); falls back to pushed_at |
| Activity: releases in 365 days | lin(count, 0, 4); null when there are no releases |
| Activity: days since release | inv(days, 90, 730); null when there are no releases |
| Activity: not archived | 1 when not archived, 0 when archived |
| Bus factor | Smallest number of contributors accounting for at least 50% of commits; lin(value, 1, 5) |
| Largest contributor share | inv(share, 0.5, 0.9); display uses a whole percentage |
| Total contributors | lin(count, 1, 20) |
| Active authors in 90 days | lin(count, 1, 5); only when there were recent commits |
| First response | Median hours to a non-author, non-bot response; inv(hours, 24, 336) |
| Unanswered ratio | inv(ratio, 0.1, 0.6); at least 5 issues older than 14 days |
| Issue closing time | Median days from creation to closure; inv(days, 7, 180) |
| Issue closing share | lin(closed share, 0.3, 0.9); at least 5 sampled issues |
| PR merge time | Median days to merge; inv(days, 3, 60); at least 3 merged PRs |
| README | lin(bytes, 300, 4000); missing README is 0, unavailable response is null |
| Other documentation | Boolean checks for license, contributing, code of conduct, issue/PR templates, docs directory, and examples |
| Security policy | SECURITY.md in root or .github |
| Continuous integration | .github/workflows or a recognised root CI configuration |
| Dependency updates | Dependabot or Renovate configuration in the supported locations |
| Known vulnerabilities | 0 → 1; 1 → 0.6; 2 → 0.3; 3 or more → 0; null when no package is detected |

File checks are case-insensitive. Missing issue data makes issue-based metrics null; PR merge data is evaluated independently. Root CI names are .travis.yml, .circleci, azure-pipelines.yml, .gitlab-ci.yml, jenkinsfile, .drone.yml, and appveyor.yml. Update files are dependabot.yml/.yaml, renovate.json/.json5 in root or .github, or .renovaterc in root. Documentation recognises license/copying prefixes, contributing and code_of_conduct prefixes, template names, docs/doc/documentation, and examples/example/samples/demo/demos.

A repository is mature only when it is not archived, at least 1,095 days old, has at least 200 stars, has a commit within 365 days, has no high/critical known package vulnerabilities, and has a manageable backlog (at most 30 open issues, or at least 60% of sampled issues closed). When mature and Activity is below 60, Activity is raised to 60 before weighting and an explanation is recorded. Stars are not a metric; they affect this adjustment's eligibility only.

| Base score | Risk |
| --- | --- |
| 80 or more | Low |
| 50 to 79.9 | Medium |
| Below 50 | High |

Archived status or no commit for 730 days forces High. Any high/critical known vulnerability forces at least Medium. Bus factor 1 with at least 90% top-contributor share forces at least Medium. The highest applicable risk wins.

Concerns use metrics below 0.4, ordered by weight × (1 - metric score), with a 10× priority multiplier for archived status and known vulnerabilities: at most 2 per category, 6 total. Strengths use metrics at least 0.85, ordered by weight × metric score: at most 1 per category, 3 total. Sensitivity uses seed 7 and 300 trials, perturbing each default weight by a factor uniform in [0.5, 1.5]; a stable ranking means every repository's best and worst ranks are equal.

## Data and dependency scans

Data comes from GitHub REST, npm, PyPI, OSV.dev, and OpenSSF Scorecard. GitHub requests follow redirects, use a 25-second timeout, and allow up to 8 concurrent requests. Commits cover up to three pages of 100; issues, contributors, releases, and pull requests are sampled rather than exhaustive. Pull requests are filtered from the issues endpoint. First responses inspect up to 5 comments on each of the 12 most recent commented issues, excluding the author and bots.

Package detection accepts a registry package only when its linked GitHub repository matches the analysed repository. Repository health uses vulnerabilities at the detected package's latest version. A dependency scan separately checks its declared base version: ^1.2.3 becomes 1.2.3. Specs without a version, including URLs, git references, file/link/workspace/npm aliases, * and latest, use the latest registry version. This is a base-version heuristic, not a complete dependency resolver. requirements.txt strips extras, comments and environment markers for lookup; it does not evaluate the environment markers.

Scans include dependencies and optionally devDependencies, truncate at MAX_SCAN_DEPS, and run with concurrency 4. Every completed package updates a persisted job. Scored rows sort High first, then by score ascending within each risk; unscored rows come last. A rate limit stops new package work and marks the remaining packages skipped with the message; already-running packages may finish. History records default-weight scores only on fresh collection.

## API

All product routes are under /api. Interactive documentation: /api/docs; OpenAPI schema: /api/openapi.json. Weight query parameters are activity, bus_factor, responsiveness, documentation, and security, each 0–100; invalid values return 422.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | /api/status | ok, token_configured, and GitHub rate-limit information or null |
| GET | /api/config | Ordered categories, default weights, risk thresholds |
| GET | /api/analyze/{owner}/{repo} | Full score and findings; accepts weights and refresh=true |
| GET | /api/compare?repos=a/b,c/d | 2–4 unique repositories, weights, and ranking sensitivity |
| GET | /api/history/{owner}/{repo} | History ordered by time |
| GET | /api/badge/{owner}/{repo}.svg | Score/risk badge; unknown on GitHub errors; public max-age=3600 |
| GET | /api/report/{owner}/{repo}.pdf | PDF report; accepts weights |
| GET | /api/report/{owner}/{repo}.csv | One metric per CSV row; accepts weights |
| POST | /api/scan | JSON filename, content, include_dev; returns job_id, total, truncated |
| GET | /api/scan/{id} | Job status, total, done, filename, rows, truncated, message |
| GET | /api/scan/{id}/csv | Dependency scan CSV |

Example scan body, with no credentials:

```json
{"filename":"package.json","content":"{\"dependencies\":{\"example-package\":\"^1.2.3\"}}","include_dev":false}
```

GitHub errors return their mapped HTTP status with a detail body. Invalid inputs are 422; unknown scan jobs are 404. Rate limiting covers analyze, compare, reports, and POST scan. Polling, badges, status, config, history, and preflight requests are exempt. A local limit response is 429 with Retry-After: 60 and a plain-language retry message. CORS allows the configured origins, methods, and headers.

## CLI and dependency workflow

From backend with the Python environment active and variables exported as above:

```sh
python -m app.cli ../frontend/package.json
python -m app.cli ../frontend/package.json --max-risk medium --min-score 50 --include-dev
python -m app.cli /path/to/requirements.txt --max-risk low
```

The table lists package, score, risk, and GitHub repository. --max-risk accepts low, medium, high and defaults to medium; --min-score defaults to 0; --include-dev includes npm development dependencies. It returns 1 if any scored dependency exceeds the allowed risk or is below the minimum score. Invalid manifests and failed jobs also return 1. Rate-limit warnings go to stderr. Unscored packages are displayed as Not scored; they do not themselves fail these gates.

To use the example in a different project:

1. Copy .github/workflows/dependency-risk.yml.example into that project's .github/workflows/dependency-risk.yml. The .example extension keeps the template inactive in RepoPulse itself.
2. Keep package.json at that project's root, or edit the final CLI command to its manifest path.
3. Review --max-risk and --min-score. Add --include-dev if wanted.
4. The workflow checks out the target project and RepoPulse separately, installs its backend requirements, sets PYTHONPATH, and runs the CLI. Its GITHUB_TOKEN uses the runner-provided secret expression; no literal credential is stored.
5. For reproducible tooling, replace the RepoPulse checkout's ref: main with a reviewed full commit SHA. The token needs read access only. Review logs for unscored/skipped packages as well as the exit code.

## Publish the API on Render

These instructions describe deployment; creating these files does not deploy the application. Make the completed files available on your GitHub main branch when you are ready.

1. Sign in to [Render Dashboard](https://dashboard.render.com), connect your GitHub account, and grant access to this repository.
2. Choose **New > Blueprint**, select nitinsaipatha-cell/repopulse (or your fork), and use branch main with Blueprint Path render.yaml.
3. Review the proposed repopulse-api Docker web service on the Free plan. The blueprint sets dockerfilePath to ./backend/Dockerfile and dockerContext to ./backend; leave the repository root available for reading render.yaml.
4. When prompted for unsynchronised environment variables, enter GITHUB_TOKEN privately and CORS_ORIGINS as your Pages origin. For this repository that origin is https://nitinsaipatha-cell.github.io, without /repopulse/ or a trailing slash. For a fork, use https://YOUR-ACCOUNT.github.io. These values are entered in Render, not committed. You can leave the token empty if accepting the 60-request limit.
5. Choose **Deploy Blueprint** and wait for the service to become live. It listens on 0.0.0.0:8000 and uses /api/config as its health check.
6. Copy the actual service URL shown by Render, for example https://YOUR-SERVICE.onrender.com. Names may be suffixed for uniqueness, so do not assume the hostname from the service name.
7. Open that URL followed by /api/config, then /api/status. Confirm categories and token_configured. Avoid using a full analysis as the health check because it consumes GitHub requests.
8. The blueprint sets DB_PATH=/tmp/repopulse.db and RATE_LIMIT_PER_MIN=30. To change the token or browser origin later, use the service's **Environment** settings and save/redeploy so the process receives the new values.

The dashboard reads [render.yaml using the Blueprint format](https://render.com/docs/blueprint-spec); variables with sync: false are supplied during setup rather than stored in YAML.

### Free-plan caveats

Render's Free web service sleeps after 15 idle minutes. Its next request has a cold start, typically about a minute; wait and retry if the frontend initially reports a connection problem. The filesystem is ephemeral: /tmp/repopulse.db, cache, history, and scan jobs are lost on restart, redeploy, or spin-down. There is no persistent history on this deployment. The frontend on GitHub Pages remains static and available while the API sleeps. Other free-tier usage limits may also suspend service; check the dashboard. See [Render's free-instance limitations](https://render.com/docs/free).

## Publish the frontend on GitHub Pages

Deploy Render first so you know the API origin.

1. In the GitHub repository, open **Settings > Pages**. Under **Build and deployment > Source**, select **GitHub Actions**.
2. Open **Settings > Secrets and variables > Actions > Variables > New repository variable**. Name it API_URL and set it to the actual Render origin, such as https://YOUR-SERVICE.onrender.com. Do not add /api. API_URL is public configuration, not a token or secret.
3. Confirm Render's CORS_ORIGINS matches the origin https://YOUR-ACCOUNT.github.io. A repository subpath belongs in VITE_BASE, not in CORS_ORIGINS.
4. Ensure .github/workflows/deploy-pages.yml is on main. Open **Actions > Deploy GitHub Pages > Run workflow**, choose main, and run it. Future pushes to main that touch frontend/** also trigger deployment. Changes to API_URL alone require another manual run.
5. The build fails with a clear message when API_URL is empty. Otherwise it sets VITE_API_BASE from API_URL and VITE_BASE=/<repository name>/ (for this repository, /repopulse/). Official configure-pages and upload-pages-artifact actions prepare and upload frontend/dist; deploy-pages publishes it in the github-pages environment with pages: write and id-token: write permissions.
6. If the github-pages environment requires approval, approve it in the Actions run. Check **Settings > Environments > github-pages** if deployment branch rules block main.
7. Follow the deployment URL emitted by Actions. For this repository the expected URL is https://nitinsaipatha-cell.github.io/repopulse/. Confirm the assets load, status banner appears as appropriate, and a repository analysis completes against Render.
8. If requests fail, verify API_URL contains only the API origin, wake Render via /api/config, and confirm its CORS origin exactly matches the browser's origin. If assets return 404, check the repository name used for VITE_BASE and rebuild.

This workflow targets a project site with a repository subpath. An account-root site or custom domain needs a corresponding VITE_BASE and CORS origin change. GitHub explains the workflow permissions, artifact, and environment requirements in [Using custom workflows with GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Tests and builds

No token or real network is required for tests. Backend HTTP calls use httpx.MockTransport and SQLite tests use an in-memory database; an automatic socket guard fails attempted real connections. Frontend tests use mocked fetch, jsdom, and a ResizeObserver stub in setupTests.js.

```sh
cd backend
. .venv/bin/activate
python -m pytest -q
cd ../frontend
npm ci
npm test
npm run build
VITE_BASE=/repopulse/ npm run build
```

The CI workflow runs backend tests and frontend tests/builds on pushes and pull requests, including a subpath build. Live GitHub acceptance checks and a running Docker Compose check are separate from offline tests. The fixed ReportLab version emits a known Python deprecation warning; the frontend build emits the expected bundle-size warning. The pinned development tools also have npm advisories; review them before deployment rather than silently changing the specification's versions.

## Implementation choices and known limitations

The following decisions are carried from docs/README-notes.md so they remain visible in the final project documentation.
### Scoring and time

- Three years means 1,095 elapsed days (3 × 365), rather than three calendar years.
- Elapsed times use fractional days or hours. Future commit or release dates are treated as zero days old.
- A timestamp without a timezone is interpreted as UTC by the scoring engine.
- Public scoring functions accept an injected `now`. When omitted, analysis uses the current UTC time; functions that only combine existing scores do not need the clock.
- Equal priorities in concerns or strengths retain category order and then metric order.
- Equal scores in sensitivity trials retain the input repository order, assigning distinct ranks. Repositories with no combined score rank after scored repositories.
- Sensitivity output uses `spread: 0.5` to describe the ±50% weight perturbation and `repos` for the per-repository statistics.
- When every category is unavailable, the combined score is null. Finalization currently assigns High risk because there is no score meeting the Medium or Low thresholds.
- When every available category has zero user weight, the combined score is also null. The all-zero weight fallback applies when all five supplied category weights are zero.
- Normalized weights use floating-point percentages without display rounding; their sum may differ from 100 by floating-point precision.
- The top contributor share is displayed as a rounded whole percentage. Its metric score and 90% risk override use the unrounded share.
- Stars are not a metric. The specification's 200-star maturity condition can indirectly affect the final score through the Activity adjustment.

### Missing data and collection

- For a boolean metric with several possible sources, positive evidence from any source is enough to score it as present. If no positive evidence exists and a required source is unavailable, the metric remains null.
- Failed or malformed subresources are isolated. A failed comment lookup leaves the issue intact and omits its optional first-response timestamp.
- When commit collection is unavailable, the author map is empty and `commits_capped` is false; the commit count remains null.
- A missing README (404) produces size zero, while an unavailable or malformed README response produces null.
- External vulnerability service failures return an empty vulnerability list, as required by section 6.4. This means an empty list cannot distinguish a successful clean lookup from a failed lookup; document this limitation.

### Foundation

- The Python virtual environment is local to `backend/.venv` and is ignored by Git.
- SQLite operations use one connection guarded by a threading lock. Repository cache and history keys are stored in lowercase.

### Service and exports

- Manifest dependencies retain declaration order before the scan limit is applied. Duplicate npm names in dependencies and devDependencies keep the production declaration; requirements duplicates keep the first case-insensitive name.
- Dependency scan rows with a score sort by risk first and score second; rows without scores follow all scored rows.
- History records default-weight scores on fresh collection so changing priorities does not change the historical baseline.
- Renamed repository aliases are remembered in the service process; raw cache entries for the requested and canonical names permit reuse, while history uses the canonical name.
- A scan failure cancels its remaining workers and persists a failed status. A service shutdown cancellation also marks its job failed. Automatic recovery of interrupted jobs after process restart is not implemented in this version.
- Badge and report modules generate their content in Phase 4. HTTP route wiring, response media types and attachment headers are implemented in Phase 5.
- Repository CSV exports have one row per metric; scan CSV exports include all specified row fields, with lists separated by semicolons.
- ReportLab 4.2.5, as pinned by the specification, emits an `ast.NameConstant` deprecation warning on Python 3.12.15. PDF generation still works; do not change the pinned dependency solely to hide the warning.
- Alias-race limitation: simultaneous requests for a previously unknown renamed repository and its canonical name may acquire different locks and collect twice before the alias is learned. Per-key deduplication works for the same normalized name.
- After a scan observes a rate limit, it skips packages that have not started and records the rate-limit message. Packages already running are allowed to finish.
- PDF text assertions use `pypdf` as a development-only dependency; it is not required by the production report generator.

### API and CLI

- The API application factory owns and closes production resources through FastAPI lifespan. Tests inject a service with mock HTTP transports and in-memory SQLite; importing the API module does not open a database or network connection.
- The HTTP compare endpoint enforces section 10's explicit 2-to-4 unique repository requirement, returning 422 for a single repository. The service's single-repository comparison returns null sensitivity to cover the no-sensitivity behavior mentioned elsewhere in the specification.
- Rate limiting uses a sliding 60-second window and a monotonic clock. CORS is registered after the limiter so Starlette wraps early 429 responses with the configured CORS headers. Preflight OPTIONS requests do not consume the quota.
- The limiter follows the specification by trusting the first x-forwarded-for entry; deployment should use a trusted proxy that supplies that header.
- CLI risk and minimum-score gates apply to dependencies with reported risks and scores. Unscored rows are printed as Not scored; rate-limit messages are printed to stderr. Invalid manifests and failed scan jobs return status 1. The specification does not define an additional fail-on-unscored rule.
- API documentation and the OpenAPI schema are available under /api/docs and /api/openapi.json.

### Frontend

- The frontend uses React state and three accessible tabs. Tab panels remain mounted to retain results, priorities, and active scan jobs when switching views.
- Slider changes debounce for 250 ms. Requests carry cancellation signals and sequence checks so stale responses cannot replace newer results. Explicit refresh applies once; later priority changes return to cached analysis.
- History displays the default-priority scores recorded by the service rather than retrospectively applying the current custom weights.
- Chart series use teal, purple, blue, and brown to distinguish repositories; risk colours are reserved for risk tags, risk bars, vulnerabilities, and the pulse.
- Null chart values remain missing. The numeric tables and expanded metrics also expose unavailable measurements as n/a.
- API startup failures show a retry action; default category configuration lets the forms remain available when config cannot be loaded.
- Tests stub ResizeObserver in setupTests.js and mock fetch. Browser layout checks use local fixture responses without contacting GitHub.
- A scan polling failure shows the error and enables starting a new scan. The scan is not cancelled on the backend.
- Google Fonts supplies Hanken Grotesk, with system-ui as the offline fallback. Clipboard copy requires a browser context that supports the Clipboard API.
- Frontend package versions remain pinned to section 3. npm reports advisories in the specified development tooling; review those before deployment rather than silently changing the required versions.
- Parser parity limitation: the frontend rejects `https://github.com:0/a/b`, while the backend currently accepts it because its port check treats zero as false. Ordinary supported repository references share the same rules.
- The Vite bundle-size warning is expected with the specified Recharts version and the current single-bundle build. Both the default and GitHub Pages subpath builds succeed despite that warning.

### Live calibration and data coverage

- In the 1 November 2026 live check, pallets/flask scored 73.9 / Medium because of its small maintainer group, a single release in the past year, and no recognised security policy or dependency-update configuration in the repository itself. The calculation follows the specified formulas; the original Flask 80+/Low acceptance expectation does not match this observed result.
- The security-policy check does not see organization-level policies. Flask has an inherited Pallets policy, so this repository-local check can under-credit Flask and similar projects.
- “Contributors” counts one page of up to 100 sampled contributors, not the true total. Contributor shares and bus factor are calculated from that returned sample.
- OSV HTTP status is not stored in the cache. An empty cached vulnerability list cannot prove that the original request succeeded; failed external requests also return an empty list.
- Other observed default-weight live results on 1 November 2026 were django/django 91.2 / Low, psf/requests 83.2 / Low, and pallets/click 82.2 / Low. These are dated observations, not fixed scoring guarantees.

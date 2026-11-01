# Choices to carry into the phase 7 README

These notes record simple implementation choices where the specification leaves details open. They describe the current implementation; update them if a later phase changes a choice.

## Scoring and time

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

## Missing data and collection

- For a boolean metric with several possible sources, positive evidence from any source is enough to score it as present. If no positive evidence exists and a required source is unavailable, the metric remains null.
- Failed or malformed subresources are isolated. A failed comment lookup leaves the issue intact and omits its optional first-response timestamp.
- When commit collection is unavailable, the author map is empty and `commits_capped` is false; the commit count remains null.
- A missing README (404) produces size zero, while an unavailable or malformed README response produces null.
- External vulnerability service failures return an empty vulnerability list, as required by section 6.4. This means an empty list cannot distinguish a successful clean lookup from a failed lookup; document this limitation.

## Foundation

- The Python virtual environment is local to `backend/.venv` and is ignored by Git.
- SQLite operations use one connection guarded by a threading lock. Repository cache and history keys are stored in lowercase.

## Phase 4

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

## Phase 5

- The API application factory owns and closes production resources through FastAPI lifespan. Tests inject a service with mock HTTP transports and in-memory SQLite; importing the API module does not open a database or network connection.
- The HTTP compare endpoint enforces section 10's explicit 2-to-4 unique repository requirement, returning 422 for a single repository. The service's single-repository comparison returns null sensitivity to cover the no-sensitivity behavior mentioned elsewhere in the specification.
- Rate limiting uses a sliding 60-second window and a monotonic clock. CORS is registered after the limiter so Starlette wraps early 429 responses with the configured CORS headers. Preflight OPTIONS requests do not consume the quota.
- The limiter follows the specification by trusting the first x-forwarded-for entry; deployment should use a trusted proxy that supplies that header.
- CLI risk and minimum-score gates apply to dependencies with reported risks and scores. Unscored rows are printed as Not scored; rate-limit messages are printed to stderr. Invalid manifests and failed scan jobs return status 1. The specification does not define an additional fail-on-unscored rule.
- API documentation and the OpenAPI schema are available under /api/docs and /api/openapi.json.

## Phase 6

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

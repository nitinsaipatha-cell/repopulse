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

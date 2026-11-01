"""Pure, explainable repository scoring. No I/O is performed here."""
from copy import deepcopy
from datetime import datetime, timezone
from random import Random
from statistics import median

CATEGORIES = {'activity': 'Activity', 'bus_factor': 'Bus factor', 'responsiveness': 'Responsiveness', 'documentation': 'Documentation', 'security': 'Security'}
DEFAULT_WEIGHTS = dict(zip(CATEGORIES, (25, 20, 20, 15, 20)))
RISK_THRESHOLDS = {'Low': 80, 'Medium': 50}


def lin(x, lo, hi):
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))


def inv(x, good, bad):
    return 1 - lin(x, good, bad)


def normalize_weights(weights=None):
    values = {k: max(0, (weights or {}).get(k, v)) for k, v in DEFAULT_WEIGHTS.items()}
    total = sum(values.values())
    if not total:
        return dict(DEFAULT_WEIGHTS)
    return {k: v * 100 / total for k, v in values.items()}


def combine(category_scores, weights=None, now=None):
    weights = normalize_weights(weights)
    present = [(v, weights[k]) for k, v in category_scores.items() if v is not None]
    total = sum(w for _, w in present)
    return round(sum(v * w for v, w in present) / total, 1) if total else None


def bus_factor(contributions):
    values = sorted(contributions, reverse=True)
    total = sum(values)
    if total <= 0:
        return None
    accumulated = 0
    for count, value in enumerate(values, 1):
        accumulated += value
        if accumulated >= total / 2:
            return count


def _date(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def analyze(raw, now=None):
    now = now or datetime.now(timezone.utc)
    repo = raw.get('repo') or {}
    categories = {k: {'label': label, 'score': None, 'metrics': []} for k, label in CATEGORIES.items()}

    def add(category, key, label, value, metric_score, detail):
        categories[category]['metrics'].append({'key': key, 'label': label, 'value': value, 'score': metric_score, 'detail': detail if metric_score is not None else f'{label} data is unavailable.'})

    def ramp(category, key, label, value, fn, lo, hi, detail):
        add(category, key, label, value, None if value is None else fn(value, lo, hi), detail)

    def days(value):
        date = _date(value)
        return max(0, (now - date).total_seconds() / 86400) if date else None

    count = raw.get('commits_90d')
    last_days = days(raw.get('last_commit_at') or repo.get('pushed_at'))
    ramp('activity', 'commits_90d', 'Recent commits', count, lin, 0, 30, f"{count}{'+' if raw.get('commits_capped') else ''} commits in the last 90 days.")
    ramp('activity', 'days_since_commit', 'Last commit', last_days, inv, 30, 365, f'Last commit was {last_days} days ago.')
    releases = raw.get('releases')
    release_days = [days(d) for d in releases or [] if d]
    release_count = sum(d <= 365 for d in release_days) if release_days else None
    release_age = min(release_days) if release_days else None
    ramp('activity', 'releases_365d', 'Recent releases', release_count, lin, 0, 4, f'{release_count} releases in the last year.')
    ramp('activity', 'days_since_release', 'Last release', release_age, inv, 90, 730, f'Last release was {release_age} days ago.')
    archived = repo.get('archived')
    add('activity', 'not_archived', 'Maintenance status', None if archived is None else not archived, None if archived is None else int(not archived), 'Repository is archived.' if archived else 'Repository is not archived.')
    contributors = raw.get('contributors')
    contributions = [c['contributions'] for c in contributors or []]
    bf = bus_factor(contributions)
    share = max(contributions) / sum(contributions) if sum(contributions) else None
    ramp('bus_factor', 'bus_factor', 'Bus factor', bf, lin, 1, 5, f'{bf} contributors account for half of all commits.')
    add('bus_factor', 'top_share', 'Largest contributor share', round(share * 100) if share is not None else None, inv(share, .5, .9) if share is not None else None, f'Top contributor accounts for {share * 100 if share is not None else None}% of commits.')
    ramp('bus_factor', 'contributors_total', 'Total contributors', len(contributors) if contributors is not None else None, lin, 1, 20, f'{len(contributors or [])} contributors.')
    authors = len(raw.get('commit_authors_90d') or {}) if count is not None and count > 0 else None
    ramp('bus_factor', 'active_authors_90d', 'Recent authors', authors, lin, 1, 5, f'{authors} authors committed in the last 90 days.')
    issues = raw.get('issues')
    responses = [(_date(i['first_response_at']) - _date(i['created_at'])).total_seconds() / 3600 for i in issues or [] if i.get('first_response_at')]
    closed = [i for i in issues or [] if i.get('closed_at')]
    close_days = [(_date(i['closed_at']) - _date(i['created_at'])).total_seconds() / 86400 for i in closed]
    old = raw.get('old_issues')
    unanswered = raw.get('old_issues_unanswered')
    ratio = unanswered / old if issues is not None and old is not None and old >= 5 and unanswered is not None else None
    closed_share = len(closed) / len(issues) if issues else None
    ramp('responsiveness', 'first_response_hours', 'First response time', median(responses) if responses else None, inv, 24, 336, f'Median first response is {median(responses) if responses else None} hours.')
    ramp('responsiveness', 'unanswered_ratio', 'Unanswered old issues', ratio, inv, .1, .6, f'{ratio} of older issues have no comments.')
    ramp('responsiveness', 'issue_close_days', 'Issue closing time', median(close_days) if close_days else None, inv, 7, 180, f'Median issue closing time is {median(close_days) if close_days else None} days.')
    ramp('responsiveness', 'issue_close_ratio', 'Issue closing share', closed_share if issues is not None and len(issues) >= 5 else None, lin, .3, .9, f'{closed_share} of sampled issues are closed.')
    pulls = raw.get('pulls')
    merged = pulls.get('merged', []) if pulls is not None else []
    merge_days = [(_date(p['merged_at']) - _date(p['created_at'])).total_seconds() / 86400 for p in merged]
    ramp('responsiveness', 'pr_merge_days', 'Pull request merge time', median(merge_days) if len(merged) >= 3 else None, inv, 3, 60, f'Median merge time is {median(merge_days) if merge_days else None} days.')
    root = raw.get('root_files')
    gh = raw.get('github_dir')
    root_set = {n.lower() for n in root or []}
    gh_set = {n.lower() for n in gh or []}
    files = root_set | gh_set
    community = raw.get('community')
    flags = community or {}

    def boolean(category, key, label, found, available):
        value = True if found else (False if available else None)
        add(category, key, label, value, int(value) if value is not None else None, f'{label} is present.' if found else f'{label} was not found.')

    size = raw.get('readme_size')
    ramp('documentation', 'readme', 'README', size, lin, 300, 4000, f'README contains {size} bytes.')
    both = root is not None and gh is not None
    boolean('documentation', 'license', 'License', flags.get('license') or repo.get('license') or any(n.startswith(('license', 'copying')) for n in root_set), community is not None and root is not None)
    for key, label in [('contributing', 'Contribution guide'), ('code_of_conduct', 'Code of conduct')]:
        boolean('documentation', key, label, flags.get(key) or any(n.startswith(key) for n in files), community is not None and both)
    boolean('documentation', 'templates', 'Issue and pull request templates', flags.get('issue_template') or flags.get('pull_request_template') or any(n.startswith(('issue_template', 'pull_request_template')) for n in gh_set), community is not None and gh is not None)
    boolean('documentation', 'docs_dir', 'Documentation directory', root_set & {'docs', 'doc', 'documentation'}, root is not None)
    boolean('documentation', 'examples', 'Examples', root_set & {'examples', 'example', 'samples', 'demo', 'demos'}, root is not None)
    boolean('security', 'security_policy', 'Security policy', 'security.md' in files, both)
    boolean('security', 'ci', 'Continuous integration', 'workflows' in gh_set or root_set & {'.travis.yml', '.circleci', 'azure-pipelines.yml', '.gitlab-ci.yml', 'jenkinsfile', '.drone.yml', 'appveyor.yml'}, both)
    boolean('security', 'dependency_updates', 'Dependency updates', files & {'dependabot.yml', 'dependabot.yaml', 'renovate.json', 'renovate.json5'} or '.renovaterc' in root_set, both)
    package = raw.get('package')
    vulns = package.get('vulns', []) if package else None
    vuln_count = len(vulns) if vulns is not None else None
    add('security', 'known_vulns', 'Known vulnerabilities', vuln_count, [1, .6, .3, 0][min(vuln_count, 3)] if vuln_count is not None else None, f'{vuln_count} known vulnerabilities in the detected package.')
    high = any((v.get('severity') or '').upper() in {'HIGH', 'CRITICAL'} for v in vulns or [])
    for cat in categories.values():
        values = [m['score'] for m in cat['metrics'] if m['score'] is not None]
        cat['score'] = round(sum(values) / len(values) * 100, 1) if values else None
    age = days(repo.get('created_at'))
    backlog = (repo.get('open_issues_count') is not None and repo['open_issues_count'] <= 30) or (closed_share is not None and closed_share >= .6)
    mature = bool(archived is False and age is not None and age >= 3 * 365 and (repo.get('stars') or 0) >= 200 and last_days is not None and last_days <= 365 and not high and backlog)
    adjustments = []
    activity = categories['activity']
    if mature and activity['score'] is not None and activity['score'] < 60:
        adjustments.append({'category': 'activity', 'before': activity['score'], 'after': 60, 'note': 'Stable, established project with a manageable backlog; activity is adjusted to 60.'})
        activity['score'] = 60
    return {'full_name': repo.get('full_name'), 'repo': deepcopy(repo), 'categories': categories, 'category_scores': {k: c['score'] for k, c in categories.items()}, 'facts': {'archived': archived, 'days_since_commit': last_days, 'bus_factor': bf, 'top_share': round(share * 100) if share is not None else None, 'top_share_ratio': share, 'high_vulns': high}, 'mature': mature, 'adjustments': adjustments, 'package': deepcopy(package), 'scorecard': deepcopy(raw.get('scorecard'))}


def finalize(analysis, weights=None, now=None):
    result = deepcopy(analysis)
    weights = normalize_weights(weights)
    value = combine(analysis['category_scores'], weights, now)
    risk = 'Low' if value is not None and value >= 80 else 'Medium' if value is not None and value >= 50 else 'High'
    overrides = []
    facts = analysis['facts']
    def override(level, text):
        nonlocal risk
        if ['Low', 'Medium', 'High'].index(level) > ['Low', 'Medium', 'High'].index(risk):
            risk = level
        overrides.append(text)
    if facts['archived']:
        override('High', 'Repository is archived, so it will not receive fixes.')
    if facts['days_since_commit'] is not None and facts['days_since_commit'] >= 730:
        override('High', 'Repository has had no commit for 730 days or more.')
    if facts['high_vulns']:
        override('Medium', 'The detected package has high or critical known vulnerabilities.')
    if facts['bus_factor'] == 1 and facts['top_share_ratio'] is not None and facts['top_share_ratio'] >= .9:
        override('Medium', 'One contributor accounts for at least 90 percent of commits.')
    def reasons(strength):
        candidates = []
        for key, cat in analysis['categories'].items():
            for metric in cat['metrics']:
                s = metric['score']
                if s is not None and (s >= .85 if strength else s < .4):
                    priority = weights[key] * (s if strength else 1 - s)
                    if not strength and metric['key'] in {'known_vulns', 'not_archived'}:
                        priority *= 10
                    candidates.append((priority, key, f"{cat['label']}: {metric['detail']}"))
        selected, counts = [], {}
        for _, key, text in sorted(candidates, key=lambda c: -c[0]):
            if counts.get(key, 0) < (1 if strength else 2):
                selected.append(text)
                counts[key] = counts.get(key, 0) + 1
            if len(selected) == (3 if strength else 6):
                break
        return selected
    result.update(score=value, risk=risk, weights=weights, overrides=overrides, concerns=reasons(False), strengths=reasons(True))
    return result


def score(raw, weights=None, now=None):
    return finalize(analyze(raw, now), weights, now)


def sensitivity(analyses, now=None):
    rng = Random(7)
    ranks = [[] for _ in analyses]
    for _ in range(300):
        weights = {k: v * rng.uniform(.5, 1.5) for k, v in DEFAULT_WEIGHTS.items()}
        values = [combine(a['category_scores'], weights, now) for a in analyses]
        order = sorted(range(len(analyses)), key=lambda i: -(values[i] if values[i] is not None else -1))
        for rank, index in enumerate(order, 1):
            ranks[index].append(rank)
    rows = [{'full_name': a.get('full_name'), 'mean_rank': sum(r) / 300, 'best_rank': min(r), 'worst_rank': max(r), 'first_pct': r.count(1) / 3} for a, r in zip(analyses, ranks)]
    return {'trials': 300, 'spread': .5, 'repos': rows, 'ranking_stable': all(r['best_rank'] == r['worst_rank'] for r in rows)}

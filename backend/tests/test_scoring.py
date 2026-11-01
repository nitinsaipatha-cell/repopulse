from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.scoring import (DEFAULT_WEIGHTS, analyze, bus_factor, combine, finalize,
                         inv, lin, normalize_weights, score, sensitivity)

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def ago(days):
    return (NOW - timedelta(days=days)).isoformat()


def healthy():
    return {
        'repo': {'full_name': 'owner/healthy', 'archived': False, 'created_at': ago(1500), 'pushed_at': ago(1), 'stars': 500, 'open_issues_count': 3, 'license': 'MIT'},
        'commits_90d': 40, 'commits_capped': False,
        'commit_authors_90d': {str(i): 8 for i in range(5)}, 'last_commit_at': ago(1),
        'contributors': [{'login': str(i), 'contributions': 10} for i in range(20)],
        'releases': [ago(i) for i in (10, 30, 60, 90)],
        'issues': [{'created_at': ago(20), 'closed_at': ago(19), 'first_response_at': ago(19.5)} for _ in range(10)],
        'old_issues': 10, 'old_issues_unanswered': 0,
        'pulls': {'closed': 3, 'merged': [{'created_at': ago(3), 'merged_at': ago(2)} for _ in range(3)]},
        'community': {k: True for k in ('license', 'contributing', 'code_of_conduct', 'issue_template', 'pull_request_template')},
        'readme_size': 5000, 'root_files': ['docs', 'examples', 'SECURITY.md'],
        'github_dir': ['workflows', 'dependabot.yml'],
        'package': {'ecosystem': 'npm', 'name': 'healthy', 'version': '1', 'vulns': []}, 'scorecard': None,
    }


def metric(result, category, key):
    return next(m for m in result['categories'][category]['metrics'] if m['key'] == key)


@pytest.mark.parametrize('x,expected', [(-1, 0), (0, 0), (15, .5), (30, 1), (31, 1)])
def test_ramps(x, expected):
    assert lin(x, 0, 30) == expected
    assert inv(x, 0, 30) == 1 - expected


@pytest.mark.parametrize('values,expected', [([100], 1), ([60, 20, 20], 1), ([10, 10, 10, 10], 2), ([], None), ([0], None)])
def test_bus_factor_definition(values, expected):
    assert bus_factor(values) == expected


def test_weights_normalization_and_zero_fallback():
    assert normalize_weights({k: 0 for k in DEFAULT_WEIGHTS}) == DEFAULT_WEIGHTS
    weights = normalize_weights({k: -5 if k == 'activity' else 10 for k in DEFAULT_WEIGHTS})
    assert weights['activity'] == 0 and sum(weights.values()) == 100
    assert normalize_weights() == DEFAULT_WEIGHTS


@pytest.mark.parametrize('value,risk', [(80, 'Low'), (79.9, 'Medium'), (50, 'Medium'), (49.9, 'High')])
def test_risk_thresholds(value, risk):
    analysis = analyze(healthy(), NOW)
    analysis['category_scores'] = {k: value for k in DEFAULT_WEIGHTS}
    assert finalize(analysis, now=NOW)['risk'] == risk


def test_healthy_is_low_and_pure():
    raw = healthy()
    before = deepcopy(raw)
    analysis = analyze(raw, NOW)
    saved = deepcopy(analysis)
    result = finalize(analysis, now=NOW)
    assert result['score'] == 100 and result['risk'] == 'Low'
    assert raw == before and analysis == saved
    assert score(raw, now=NOW) == result


def test_abandoned_is_high_with_overrides_and_concerns():
    raw = healthy()
    raw.update(commits_90d=0, last_commit_at=ago(800), releases=[])
    raw['repo']['pushed_at'] = ago(800)
    result = score(raw, now=NOW)
    assert result['risk'] == 'High'
    assert any('730' in text for text in result['overrides'])
    assert any('0 commits' in text for text in result['concerns'])
    assert not result['mature']


def test_archived_forces_high_and_prioritizes_concern():
    raw = healthy()
    raw['repo']['archived'] = True
    result = score(raw, now=NOW)
    assert result['risk'] == 'High'
    assert result['overrides'][0] == 'Repository is archived, so it will not receive fixes.'
    assert 'archived' in result['concerns'][0]


def test_critical_vulnerability_forces_medium():
    raw = healthy()
    raw['package']['vulns'] = [{'id': 'critical', 'severity': 'CRITICAL'}]
    result = score(raw, now=NOW)
    assert result['score'] >= 80 and result['risk'] == 'Medium'
    assert result['overrides'] and not result['mature']


def test_missing_data_is_excluded():
    raw = healthy()
    raw.update(contributors=None, commits_90d=None, commit_authors_90d={}, issues=None, pulls=None, package=None, releases=None)
    result = score(raw, now=NOW)
    assert result['score'] == 100
    assert result['category_scores']['bus_factor'] is None
    assert result['category_scores']['responsiveness'] is None
    assert metric(result, 'security', 'known_vulns')['score'] is None
    assert metric(result, 'activity', 'releases_365d')['score'] is None
    assert metric(result, 'bus_factor', 'active_authors_90d')['score'] is None
    assert combine({'activity': None, 'security': 80}, now=NOW) == 80
    assert combine({'activity': None}, now=NOW) is None


def test_all_data_missing_has_null_categories():
    result = score({'repo': {}}, now=NOW)
    assert all(value is None for value in result['category_scores'].values())
    assert result['score'] is None and result['concerns'] == []


def mature_quiet():
    raw = healthy()
    raw.update(commits_90d=1, last_commit_at=ago(300), releases=[ago(800)])
    return raw


def test_maturity_adjustment_before_weighting():
    result = score(mature_quiet(), {'activity': 100, **{k: 0 for k in DEFAULT_WEIGHTS if k != 'activity'}}, NOW)
    assert result['mature'] and result['score'] == 60
    adjustment = result['adjustments'][0]
    assert adjustment['category'] == 'activity' and adjustment['before'] < 60 and adjustment['after'] == 60 and adjustment['note']
    assert score(healthy(), now=NOW)['adjustments'] == []


@pytest.mark.parametrize('field,value', [('archived', True), ('created_at', ago(100)), ('stars', 199), ('open_issues_count', 31)])
def test_maturity_requires_every_condition(field, value):
    raw = mature_quiet()
    raw['repo'][field] = value
    if field == 'open_issues_count':
        raw['issues'] = []
    assert not score(raw, now=NOW)['mature']


def test_maturity_commit_backlog_and_vulnerability_boundaries():
    raw = mature_quiet()
    raw['last_commit_at'] = ago(366)
    assert not analyze(raw, NOW)['mature']
    raw['last_commit_at'] = ago(365)
    raw['repo']['open_issues_count'] = 100
    raw['issues'] = [{'created_at': ago(20), 'closed_at': ago(19) if i < 3 else None} for i in range(5)]
    assert analyze(raw, NOW)['mature']
    raw['package']['vulns'] = [{'severity': 'HIGH'}]
    assert not analyze(raw, NOW)['mature']


def test_custom_weights_move_score():
    raw = healthy()
    raw.update(readme_size=0, root_files=[], github_dir=[], community={})
    raw['repo']['license'] = None
    analysis = analyze(raw, NOW)
    activity = {k: int(k == 'activity') for k in DEFAULT_WEIGHTS}
    documentation = {k: int(k == 'documentation') for k in DEFAULT_WEIGHTS}
    assert finalize(analysis, activity, NOW)['score'] > finalize(analysis, documentation, NOW)['score']


def test_sensitivity_deterministic_stable_and_crossing():
    def profile(name, values):
        return {'full_name': name, 'category_scores': dict(zip(DEFAULT_WEIGHTS, values))}
    stable = [profile('high', [100] * 5), profile('low', [0] * 5)]
    result = sensitivity(stable, NOW)
    assert result == sensitivity(stable, NOW) and result['trials'] == 300
    assert result['ranking_stable'] and result['repos'][0]['first_pct'] == 100
    crossing = [profile('a', [100, 0, 0, 0, 100]), profile('b', [0, 100, 100, 100, 0])]
    result = sensitivity(crossing, NOW)
    assert not result['ranking_stable']
    assert all(0 < row['first_pct'] < 100 for row in result['repos'])


def test_metric_ramps_and_minimum_samples():
    raw = healthy()
    raw['repo']['stars'] = 0
    raw.update(commits_90d=15, last_commit_at=ago(197.5), releases=[ago(410)], old_issues=4)
    raw['issues'] = raw['issues'][:4]
    raw['pulls']['merged'] = raw['pulls']['merged'][:2]
    result = analyze(raw, NOW)
    assert metric(result, 'activity', 'commits_90d')['score'] == .5
    assert metric(result, 'activity', 'days_since_commit')['score'] == .5
    assert metric(result, 'activity', 'releases_365d')['score'] == 0
    assert metric(result, 'responsiveness', 'unanswered_ratio')['score'] is None
    assert metric(result, 'responsiveness', 'issue_close_ratio')['score'] is None
    assert metric(result, 'responsiveness', 'pr_merge_days')['score'] is None


@pytest.mark.parametrize('count,expected', [(0, 1), (1, .6), (2, .3), (3, 0), (5, 0)])
def test_vulnerability_count_scores(count, expected):
    raw = healthy()
    raw['package']['vulns'] = [{'severity': None}] * count
    assert metric(analyze(raw, NOW), 'security', 'known_vulns')['score'] == expected


def test_files_case_insensitive_and_missing_sources():
    raw = healthy()
    raw.update(community=None, root_files=['LICENSE.txt', 'DOC', 'DEMO', 'CONTRIBUTING.md', 'CODE_OF_CONDUCT.md', 'SECURITY.MD'], github_dir=['ISSUE_TEMPLATE', 'WORKFLOWS', 'RENOVATE.JSON'])
    result = analyze(raw, NOW)
    assert result['category_scores']['documentation'] == 100
    assert result['category_scores']['security'] == 100
    raw.update(root_files=None, github_dir=None, readme_size=None)
    raw['repo']['license'] = None
    result = analyze(raw, NOW)
    assert result['category_scores']['documentation'] is None


def test_bus_factor_override_and_reason_caps():
    raw = healthy()
    raw['contributors'] = [{'login': 'solo', 'contributions': 90}, {'login': 'other', 'contributions': 10}]
    result = score(raw, now=NOW)
    assert result['risk'] == 'Medium' and any('90 percent' in item for item in result['overrides'])
    raw.update(commits_90d=0, last_commit_at=ago(800), releases=[ago(800)], readme_size=0, root_files=[], github_dir=[], community={})
    raw['repo'].update(archived=True, license=None)
    raw['package']['vulns'] = [{'severity': 'HIGH'}] * 3
    result = score(raw, now=NOW)
    assert len(result['concerns']) <= 6 and len(result['strengths']) <= 3
    labels = [text.split(':')[0] for text in result['concerns']]
    assert all(labels.count(label) <= 2 for label in labels)
    assert 'archived' in result['concerns'][0] or 'vulnerabilities' in result['concerns'][0]


def test_rounded_share_does_not_trigger_override():
    raw = healthy()
    raw['contributors'] = [{'login': 'a', 'contributions': 896}, {'login': 'b', 'contributions': 104}]
    result = score(raw, now=NOW)
    assert result['facts']['top_share'] == 90
    assert not any('90 percent' in text for text in result['overrides'])


@pytest.mark.parametrize('category,key,good,bad', [
    ('activity', 'days_since_commit', 30, 365),
    ('activity', 'days_since_release', 90, 730),
    ('responsiveness', 'first_response_hours', 24, 336),
    ('responsiveness', 'issue_close_days', 7, 180),
    ('responsiveness', 'pr_merge_days', 3, 60),
])
def test_inverse_metric_endpoints(category, key, good, bad):
    for value, expected in [(good, 1), (bad, 0)]:
        raw = healthy()
        raw['repo']['stars'] = 0
        if key == 'days_since_commit':
            raw['last_commit_at'] = ago(value)
        elif key == 'days_since_release':
            raw['releases'] = [ago(value)]
        elif key == 'first_response_hours':
            for item in raw['issues']:
                item['first_response_at'] = ago(20 - value / 24)
        elif key == 'issue_close_days':
            for item in raw['issues']:
                item['created_at'], item['closed_at'] = ago(value + 1), ago(1)
        else:
            raw['pulls']['merged'] = [{'created_at': ago(value + 1), 'merged_at': ago(1)}] * 3
        assert metric(analyze(raw, NOW), category, key)['score'] == expected


@pytest.mark.parametrize('days,risk,has_override', [(729, 'Low', False), (730, 'High', True)])
def test_inactivity_override_exact_boundary(days, risk, has_override):
    raw = healthy()
    raw['last_commit_at'] = ago(days)
    result = score(raw, now=NOW)
    assert result['risk'] == risk
    assert any('730 days' in text for text in result['overrides']) is has_override


def test_strengths_have_unique_categories_and_total_cap():
    result = score(healthy(), now=NOW)
    # All five categories have qualifying metrics, so the total cap is exercised.
    assert all(any(m['score'] is not None and m['score'] >= .85 for m in category['metrics'])
               for category in result['categories'].values())
    strengths = result['strengths']
    labels = [text.split(':', 1)[0] for text in strengths]
    assert len(strengths) == 3
    assert len(labels) == len(set(labels))

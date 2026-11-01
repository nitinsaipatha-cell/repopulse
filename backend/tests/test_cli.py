from argparse import Namespace
from io import StringIO
import json

import pytest

from app.cli import main, run
from app.github_client import RateLimited
from tests.test_api import api  # Shared MockTransport/in-memory service fixture.
from tests.test_scoring import healthy


def arguments(path, **options):
    return Namespace(manifest=str(path), max_risk=options.get('max_risk', 'medium'),
        min_score=options.get('min_score', 0), include_dev=options.get('include_dev', False))


@pytest.mark.parametrize('max_risk,expected', [('low', 1), ('medium', 0), ('high', 0)])
async def test_cli_risk_threshold_and_table(api, tmp_path, max_risk, expected):
    _, service, _ = api
    raw = healthy()
    raw['repo']['full_name'] = 'owner/repo'
    raw['fetched_at'] = service.clock().isoformat()
    service.db.put_cache('owner/repo', raw['fetched_at'], raw)
    manifest = tmp_path / 'package.json'
    manifest.write_text(json.dumps({'dependencies': {'vulnerable': '1.2.3'}}))
    out, err = StringIO(), StringIO()
    code = await run(arguments(manifest, max_risk=max_risk), service, out, err)
    assert code == expected  # Declared version's critical vulnerability raises Low to Medium.
    assert 'Package' in out.getvalue() and 'Score' in out.getvalue() and 'Risk' in out.getvalue()
    assert 'vulnerable' in out.getvalue() and 'owner/repo' in out.getvalue()


async def test_cli_minimum_score_and_include_dev(api, tmp_path):
    _, service, _ = api
    manifest = tmp_path / 'package.json'
    manifest.write_text(json.dumps({'dependencies': {'vulnerable': '1'}, 'devDependencies': {'dev-only': '1'}}))
    out = StringIO()
    assert await run(arguments(manifest, min_score=100), service, out, StringIO()) == 1
    assert 'dev-only' not in out.getvalue()
    out = StringIO()
    assert await run(arguments(manifest, include_dev=True, max_risk='high'), service, out, StringIO()) == 0
    assert 'dev-only' in out.getvalue()


async def test_cli_high_risk_gate(api, tmp_path):
    _, service, _ = api
    raw = healthy()
    raw['repo'].update(full_name='owner/repo', archived=True)
    raw['fetched_at'] = service.clock().isoformat()
    service.db.put_cache('owner/repo', raw['fetched_at'], raw)
    manifest = tmp_path / 'package.json'
    manifest.write_text('{"dependencies":{"vulnerable":"1"}}')
    assert await run(arguments(manifest), service, StringIO(), StringIO()) == 1
    assert await run(arguments(manifest, max_risk='high'), service, StringIO(), StringIO()) == 0


async def test_cli_rate_limit_warning_and_unscored(api, tmp_path):
    _, service, _ = api
    async def limited(*args, **kwargs):
        raise RateLimited('GitHub API rate limit reached. Resets in about 10 min.')
    service.analyze = limited
    manifest = tmp_path / 'package.json'
    manifest.write_text('{"dependencies":{"vulnerable":"1"}}')
    out, err = StringIO(), StringIO()
    await run(arguments(manifest), service, out, err)
    assert 'rate limit reached' in err.getvalue()
    assert 'Not scored' in out.getvalue() and 'n/a' in out.getvalue()


async def test_cli_missing_invalid_and_failed_jobs(api, tmp_path):
    _, service, _ = api
    path = tmp_path / 'package.json'
    err = StringIO()
    assert await run(arguments(path), service, StringIO(), err) == 1
    path.write_text('{bad')
    assert await run(arguments(path), service, StringIO(), err) == 1
    path.write_text('{"dependencies":{"vulnerable":"1"}}')
    async def failed(*args):
        raise RuntimeError('example failure')
    service.external.registry = failed
    assert await run(arguments(path), service, StringIO(), err) == 1
    assert 'example failure' in err.getvalue()


def test_cli_argument_defaults_options_and_exit_code(monkeypatch):
    captured = []
    async def fake(args):
        captured.append(args)
        return 1
    monkeypatch.setattr('app.cli._main', fake)
    assert main(['package.json']) == 1
    assert captured[-1].max_risk == 'medium' and captured[-1].min_score == 0 and not captured[-1].include_dev
    assert main(['requirements.txt', '--max-risk', 'low', '--min-score', '75', '--include-dev']) == 1
    assert captured[-1].max_risk == 'low' and captured[-1].min_score == 75 and captured[-1].include_dev
    with pytest.raises(SystemExit) as exc:
        main(['package.json', '--max-risk', 'unknown'])
    assert exc.value.code == 2

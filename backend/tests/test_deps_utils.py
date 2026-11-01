import json

import pytest

from app.deps import base_version, parse_manifest, parse_package_json, parse_requirements


@pytest.mark.parametrize('spec,version', [('^1.2.3', '1.2.3'), ('>=2.0,<3', '2.0'), ('1.0.0-beta.1', '1.0.0-beta.1'), ('*', None), ('latest', None), ('https://a/1.2.3', None), ('git+https://a/1', None), ('file:../1.2', None), ('link:1', None), ('workspace:^1', None), ('npm:other@1.2', None)])
def test_base_versions(spec, version):
    assert base_version(spec) == version


def test_package_json_dev_and_duplicates():
    content = json.dumps({'dependencies': {'a': '^1.2.3'}, 'devDependencies': {'b': '*', 'a': '2'}})
    assert len(parse_package_json(content)) == 1
    rows = parse_package_json(content, True)
    assert len(rows) == 2 and rows[1]['dev'] and rows[0]['declared_version'] == '1.2.3'


@pytest.mark.parametrize('content', ['{bad', '[]', '{"dependencies": []}', '{"dependencies": {"a": 3}}'])
def test_invalid_json(content):
    with pytest.raises(ValueError, match='Invalid package.json'):
        parse_package_json(content)


def test_requirements_edge_cases():
    rows = parse_requirements('''# comment
-r base.txt
--index-url http://example.test
https://example.test/a.whl
git+https://example.test/a
./local
Flask[async]>=2.0,<3 ; python_version > "3" # comment
flask==1
requests
numpy~=1.26.0
pkg @ https://example.test/a
''')
    assert [r['name'] for r in rows] == ['Flask', 'requests', 'numpy']
    assert [r['declared_version'] for r in rows] == ['2.0', None, '1.26.0']
    assert all(r['ecosystem'] == 'PyPI' and not r['dev'] for r in rows)


def test_dispatch_and_empty():
    assert parse_manifest('package.JSON', '{"dependencies": {"a": "1"}}')[0]['ecosystem'] == 'npm'
    assert parse_manifest('requirements.in', 'a==1')[0]['ecosystem'] == 'PyPI'
    assert parse_manifest('other.txt', '') == []
    with pytest.raises(ValueError) as exc:
        parse_manifest('other.yaml', '')
    assert str(exc.value) == 'Unsupported file. Upload a package.json or requirements.txt.'


def test_scan_sort_by_risk_then_score_with_unscored_last():
    from app.deps import sort_rows
    rows = [
        {'name': 'unscored-high', 'risk': 'High', 'score': None},
        {'name': 'low-90', 'risk': 'Low', 'score': 90},
        {'name': 'medium-70', 'risk': 'Medium', 'score': 70},
        {'name': 'high-40', 'risk': 'High', 'score': 40},
        {'name': 'unscored', 'risk': None, 'score': None},
        {'name': 'medium-50', 'risk': 'Medium', 'score': 50},
        {'name': 'high-20', 'risk': 'High', 'score': 20},
        {'name': 'low-80', 'risk': 'Low', 'score': 80},
    ]
    assert [row['name'] for row in sort_rows(rows)] == [
        'high-20', 'high-40', 'medium-50', 'medium-70', 'low-80', 'low-90',
        'unscored-high', 'unscored',
    ]

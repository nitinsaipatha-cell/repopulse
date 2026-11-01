import csv
from io import BytesIO, StringIO
from xml.etree import ElementTree

import pytest
from pypdf import PdfReader

from app.badge import badge_svg, repository_badge
from app.github_client import GitHubError, RateLimited, RepoNotFound
from app.report import report_csv, report_pdf, scan_csv
from app.scoring import score
from tests.test_scoring import NOW, healthy


@pytest.mark.parametrize('risk,color', [('Low', '2f7d4e'), ('Medium', 'be7f0b'), ('High', 'b3372f'), (None, '6b7b82')])
def test_badge_colors_and_svg(risk, color):
    svg = badge_svg(85 if risk else None, risk)
    assert f'#{color}' in svg and 'repo health' in svg
    ElementTree.fromstring(svg)


@pytest.mark.parametrize('error', [GitHubError('failed'), RepoNotFound(), RateLimited('limited')])
async def test_badge_github_errors_return_unknown_and_cache_header(error):
    class Failed:
        async def analyze(self, reference):
            raise error
    svg, headers = await repository_badge(Failed(), 'a/b')
    assert 'unknown' in svg and '#6b7b82' in svg
    assert headers == {'Cache-Control': 'public, max-age=3600'}


async def test_badge_success():
    class Success:
        async def analyze(self, reference):
            return {'score': 91.2, 'risk': 'Low'}
    svg, _ = await repository_badge(Success(), 'a/b')
    assert '91.2 Low' in svg


def test_pdf_and_metric_csv():
    raw = healthy()
    raw['repo']['description'] = 'A library with <markup> & punctuation.'
    result = score(raw, now=NOW)
    pdf = report_pdf(result)
    assert pdf.startswith(b'%PDF-') and pdf.rstrip().endswith(b'%%EOF')
    reader = PdfReader(BytesIO(pdf))
    text = ' '.join(' '.join(page.extract_text() for page in reader.pages).split())
    for expected in (
        'RepoPulse: owner/healthy', 'A library with <markup> & punctuation.',
        f"Score: {result['score']} / 100", f"Risk: {result['risk']}",
        'Needs attention', 'Going well', 'Score by area', 'Category', 'Weight (%)',
        'Documentation', 'Metric breakdown', 'Metric', 'Value', 'Score (0-1)',
        'Finding', 'Activity: Recent commits', '40 commits in the last 90 days.',
    ):
        assert expected in text
    rows = list(csv.DictReader(StringIO(report_csv(result))))
    assert len(rows) == sum(len(c['metrics']) for c in result['categories'].values())
    assert rows[0]['repository'] == 'owner/healthy'
    assert {'metric', 'metric_score', 'detail', 'category_score'} <= rows[0].keys()


def test_scan_csv_quoting_and_unscored_rows():
    content = scan_csv({'rows': [{'name': 'a', 'score': None, 'risk': None, 'note': 'Missing, try another', 'concerns': ['x', 'y'], 'vuln_ids': ['GHSA-a']}]})
    row = next(csv.DictReader(StringIO(content)))
    assert row['score'] == '' and row['note'] == 'Missing, try another' and row['concerns'] == 'x; y'

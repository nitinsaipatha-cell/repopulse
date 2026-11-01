"""SVG badge generation and service adapter for the future HTTP route."""
from html import escape

from app.github_client import GitHubError

COLORS = {'Low': '2f7d4e', 'Medium': 'be7f0b', 'High': 'b3372f', 'unknown': '6b7b82'}
CACHE_HEADERS = {'Cache-Control': 'public, max-age=3600'}


def badge_svg(score=None, risk=None):
    text = f'{score:.1f} {risk}' if score is not None and risk in COLORS else 'unknown'
    color = COLORS.get(risk, COLORS['unknown']) if score is not None else COLORS['unknown']
    label = f'repo health: {text}'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="228" height="24" role="img" aria-label="{escape(label, quote=True)}"><title>{escape(label)}</title><rect width="118" height="24" fill="#55666e"/><rect x="118" width="110" height="24" fill="#{color}"/><g fill="white" font-family="Verdana,sans-serif" font-size="11" text-anchor="middle"><text x="59" y="16">repo health</text><text x="173" y="16">{escape(text)}</text></g></svg>'''


async def repository_badge(service, reference):
    try:
        result = await service.analyze(reference)
        svg = badge_svg(result['score'], result['risk'])
    except GitHubError:
        svg = badge_svg()
    return svg, dict(CACHE_HEADERS)

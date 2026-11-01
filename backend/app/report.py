"""In-memory CSV and PDF reports."""
import csv
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def report_csv(result):
    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['repository', 'score', 'risk', 'category', 'category_score', 'metric', 'label', 'value', 'metric_score', 'detail'])
    for category, area in result['categories'].items():
        for metric in area['metrics']:
            writer.writerow([result['full_name'], result['score'], result['risk'], category, area['score'], metric['key'], metric['label'], metric['value'], metric['score'], metric['detail']])
    return output.getvalue()


def scan_csv(job):
    output = StringIO(newline='')
    fields = ['name', 'ecosystem', 'spec', 'dev', 'declared_version', 'latest', 'status', 'repo', 'score', 'risk', 'categories', 'vuln_count', 'high_vuln_count', 'vuln_ids', 'concerns', 'note']
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in job['rows']:
        writer.writerow({key: '; '.join(map(str, value)) if isinstance(value, list) else str(value) if isinstance(value, dict) else value for key, value in row.items() if key in fields})
    return output.getvalue()


def report_pdf(result):
    output = BytesIO()
    styles = getSampleStyleSheet()
    styles['BodyText'].fontSize = 9
    styles['BodyText'].leading = 12
    def text(value, style='BodyText'):
        return Paragraph(escape('n/a' if value is None else str(value)), styles[style])
    story = [text(f"RepoPulse: {result['full_name']}", 'Title'), text(result['repo'].get('description') or 'Repository health report'), Spacer(1, 12), text(f"Score: {result['score'] if result['score'] is not None else 'n/a'} / 100    Risk: {result['risk']}", 'Heading2')]
    for title, items in [('Needs attention', result['overrides'] + result['concerns']), ('Going well', result['strengths'])]:
        story.append(text(title, 'Heading2'))
        story.extend(text(item) for item in items or ['None identified.'])
    def table(rows, widths):
        value = Table([[text(cell) for cell in row] for row in rows], colWidths=widths, repeatRows=1, hAlign='LEFT')
        value.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef2f3')), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, 0), .7, colors.HexColor('#55666e')), ('LINEBELOW', (0, 1), (-1, -1), .3, colors.HexColor('#d3dcdf')), ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
        return value
    story += [text('Score by area', 'Heading2'), table([['Category', 'Score', 'Weight (%)']] + [[area['label'], area['score'], round(result['weights'][key], 1)] for key, area in result['categories'].items()], [3.5*inch, inch, inch])]
    rows = [['Metric', 'Value', 'Score (0-1)', 'Finding']]
    for area in result['categories'].values():
        for m in area['metrics']:
            rows.append([f"{area['label']}: {m['label']}", m['value'], round(m['score'], 3) if m['score'] is not None else None, m['detail']])
    story += [text('Metric breakdown', 'Heading2'), table(rows, [1.5*inch, .7*inch, .8*inch, 2.5*inch])]
    def footer(canvas, document):
        canvas.setFont('Helvetica', 8)
        canvas.drawString(48, 30, 'RepoPulse - repository health and risk')
        canvas.drawRightString(550, 30, str(document.page))
    SimpleDocTemplate(output, rightMargin=48, leftMargin=48, topMargin=40, bottomMargin=48).build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()

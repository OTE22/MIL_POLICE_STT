import io
import zipfile
from contextlib import closing
import pytest
from PIL import Image
from pydantic import ValidationError
from app.services.report_layout import sample_pages, ReportLayout, LayoutBox, build_layout, read_layout
from app.services.report_renderer import validate_template, render, sample_context, RenderError
from tests.conftest import auth


def image_sample():
    output = io.BytesIO()
    Image.new('RGB', (600, 840), 'white').save(output, format='PNG')
    return output.getvalue()


def layout():
    pages = sample_pages(image_sample())
    pages[0]['boxes'] = [dict(field='subject_name', x=.1, y=.1, width=.7, height=.1, font_size=12)]
    return ReportLayout(name='Annotated template', pages=pages)


def test_box_roundtrip_renders_positioned_field_and_flowing_dialogue():
    template = build_layout(layout())
    assert validate_template(template).ok
    restored = read_layout(template)
    assert restored.pages[0].boxes[0].x == .1
    context = sample_context()
    context['subject_name'] = 'اختبار الاسم'
    output = render(template, context)
    with zipfile.ZipFile(io.BytesIO(output)) as archive:
        xml = archive.read('word/document.xml').decode()
        assert 'اختبار الاسم' in xml
        assert 'ما اسمك الكامل' in xml
        assert '{{' not in xml
        assert 'txbxContent' in xml and 'behindDoc="1"' in xml


def test_rejects_unknown_fields_outside_page_and_long_content():
    with pytest.raises(ValidationError):
        LayoutBox(field='secret', x=0,y=0,width=.5,height=.1)
    with pytest.raises(ValidationError):
        LayoutBox(field='subject_name', x=.9,y=0,width=.5,height=.1)
    context = sample_context(); context['subject_name'] = 'طويل ' * 1000
    with pytest.raises(RenderError, match='report_layout_text_overflow'):
        render(build_layout(layout()), context)


def test_pdf_sample_is_rasterized():
    import pypdfium2 as pdfium
    with closing(pdfium.PdfDocument.new()) as pdf:
        page = pdf.new_page(595,842); page.close()
        output = io.BytesIO(); pdf.save(output)
    pages = sample_pages(output.getvalue())
    assert len(pages) == 1 and pages[0]['width_pt'] == 595
    assert pages[0]['image']


def test_thirty_page_template_preserves_order_dimensions_and_fields():
    import pypdfium2 as pdfium
    from docx import Document
    import base64
    with closing(pdfium.PdfDocument.new()) as pdf:
        for index in range(30):
            pdf.new_page(595 + index, 842).close()
        output = io.BytesIO(); pdf.save(output)
    pages = sample_pages(output.getvalue())
    assert len(pages) == 30
    assert base64.b64decode(pages[0]['image']).startswith(b'\xff\xd8')
    for page in pages:
        page['boxes'] = [dict(field='report_number', x=.1, y=.1, width=.7, height=.1)]
    template = build_layout(ReportLayout(name='Thirty pages', pages=pages))
    restored = read_layout(template)
    assert [page.width_pt for page in restored.pages] == list(range(595, 625))
    assert all(page.boxes[0].field == 'report_number' for page in restored.pages)
    rendered = render(template, sample_context())
    document = Document(io.BytesIO(rendered))
    assert len(document.sections) == 31  # Sample pages plus flowing dialogue.
    assert len(template) < 20 * 1024 * 1024


def test_page_limit_and_combined_image_budget(monkeypatch):
    import pypdfium2 as pdfium
    from app.services import report_layout
    with closing(pdfium.PdfDocument.new()) as pdf:
        for _ in range(31):
            pdf.new_page(595, 842).close()
        output = io.BytesIO(); pdf.save(output)
    with pytest.raises(ValueError, match='thirty'):
        sample_pages(output.getvalue())
    with pytest.raises(ValidationError):
        ReportLayout(name='Too many', pages=[layout().pages[0]] * 31)
    original = layout()
    monkeypatch.setattr(report_layout, 'MAX_IMAGES_BYTES', 1)
    with pytest.raises(ValueError, match='Combined'):
        build_layout(original)


def test_legacy_png_layout_still_builds():
    import base64
    old = layout()
    old.pages[0].image = base64.b64encode(image_sample()).decode()
    assert read_layout(build_layout(old)).pages[0].boxes[0].field == 'subject_name'


def test_annotation_api_saves_inactive_version_and_reopens_boxes(client, admin_token, investigator):
    assert client.post('/api/report-templates/sample', files={'file':('sample.png',image_sample(),'image/png')},
                       headers=auth(investigator['token'])).status_code == 403
    result = client.post('/api/report-templates/layout', json=layout().model_dump(), headers=auth(admin_token))
    assert result.status_code == 201, result.text
    version = result.json()['versions'][0]
    assert version['validation_status'] == 'VALID' and not version['is_active']
    loaded = client.get(f"/api/report-templates/{version['id']}/layout", headers=auth(admin_token))
    assert loaded.status_code == 200
    assert loaded.json()['pages'][0]['boxes'][0]['field'] == 'subject_name'
    preview = client.get(f"/api/report-templates/{version['id']}/preview", headers=auth(admin_token))
    assert preview.status_code == 200 and preview.content.startswith(b'PK')


def test_invalid_sample_is_explained(client, admin_token):
    result = client.post('/api/report-templates/sample', files={'file':('bad.pdf',b'not a pdf','application/pdf')}, headers=auth(admin_token))
    assert result.status_code == 422

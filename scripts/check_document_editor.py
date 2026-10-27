"""Real browser/API checks using only synthetic data on isolated workflow-ui services."""
import json
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://workflow-ui-frontend'
OUT = Path('/artifacts/document-editor')
OUT.mkdir(parents=True, exist_ok=True)
expect.set_options(timeout=30000)
with sync_playwright() as p:
    browser = p.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage'])
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    token = None
    def api(method, path, data=None, bearer=None):
        response = context.request.fetch(BASE + '/api' + path, method=method, data=data,
            headers={'Authorization': 'Bearer ' + (bearer or token)} if bearer or token else {})
        assert response.ok, (path, response.status, response.text()[:400])
        return response.json()
    admin = api('POST', '/auth/login', {'username': 'admin', 'password': 'AdminBootstrap!1'})['access_token']
    username = 'document_' + uuid.uuid4().hex[:10]
    api('POST', '/users', {'username': username, 'password': 'WorkflowTest!1234', 'roles': ['INVESTIGATOR'],
        'must_change_password': False, 'profile': {'full_name': 'محقق تجربة التحرير', 'rank': 'نقيب',
        'military_id': username, 'security_branch': 'ARMY'}}, admin)
    token = api('POST', '/auth/login', {'username': username, 'password': 'WorkflowTest!1234'})['access_token']
    session = api('POST', '/investigations', {'title': 'اختبار تحرير المحضر', 'location': 'مكتب الاختبار',
        'session_date': '2026-10-27', 'start_time': '10:00'})
    base = '/investigations/' + session['id']
    api('POST', base + '/report/html', {})
    state = api('GET', base + '/report/html')
    note_id = str(uuid.uuid4())
    doc = {**state['document'], 'blocks': [{'id': note_id, 'type': 'note', 'values': {
        'note_text': 'نص ملاحظة تجريبية', 'closing_date': '2026-10-27', 'closing_location': 'مكتب الاختبار'}}]}
    api('PUT', base + '/report/html', {'expected_token': state['token'], 'document': doc})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.goto(BASE + '/login')
    page.locator('#username').fill(username)
    page.locator('#password').fill('WorkflowTest!1234')
    page.locator('button[type="submit"]').click()
    expect(page).not_to_have_url(BASE + '/login')
    page.goto(BASE + base + '/report')
    page.get_by_role('button', name='ختام المحضر', exact=True).click()
    page.locator('#report-field-closing-text').fill('نظم وختم هذا التحقيق، للتفضل بالاطلاع.')
    page.get_by_role('button', name='تحرير المحضر قبل الطباعة', exact=True).click()
    frame = page.frame_locator('iframe[title="تحرير نص المحضر مباشرة"]')
    note = frame.get_by_role('textbox', name='نص الملاحظة', exact=True)
    # Catalogue label may be simply الملاحظة; select the canonical edit target.
    note = frame.locator('[data-edit-key="value:note_text"] textarea')
    expect(note).to_be_visible()
    page.get_by_role('button', name='انتقل إلى أول نص قابل للتحرير', exact=True).click()
    expect(note).to_be_focused()
    note.fill('تعديل مباشر من المحضر')
    page.wait_for_timeout(2200)  # cross the autosave/preview boundary while focused
    note.press('End')
    note.press_sequentially(' + retained typing', delay=70)
    expect(note).to_be_focused()
    expected = 'تعديل مباشر من المحضر + retained typing'
    expect(note).to_have_value(expected)
    page.wait_for_timeout(1800)
    assert api('GET', base + '/report/html')['document']['blocks'][0]['values']['note_text'] == expected
    closing = frame.locator('[data-edit-key="closing:text"] textarea')
    closing.fill('نظم وختم هذا التحقيق بصورته الحاضرة، للتفضل بالاطلاع.')
    page.wait_for_timeout(1800)
    assert api('GET', base + '/report/html')['document']['closing']['text'] == closing.input_value()
    page.screenshot(path=str(OUT / 'editing.png'), full_page=True)
    # One failed save must retain typing and support explicit retry.
    page.route('**/api' + base + '/report/html', lambda route: route.abort() if route.request.method == 'PUT' else route.continue_())
    note.fill('نص باق رغم انقطاع الحفظ')
    expect(page.get_by_role('button', name='إعادة محاولة الحفظ', exact=True)).to_be_visible()
    expect(note).to_have_value('نص باق رغم انقطاع الحفظ')
    page.unroute('**/api' + base + '/report/html')
    page.get_by_role('button', name='إعادة محاولة الحفظ', exact=True).click()
    page.wait_for_timeout(1800)
    assert api('GET', base + '/report/html')['document']['blocks'][0]['values']['note_text'] == 'نص باق رغم انقطاع الحفظ'
    page.get_by_role('button', name='معاينة PDF والمراجعة', exact=True).click()
    expect(page.get_by_role('link', name='تنزيل المعاينة PDF', exact=True)).to_be_visible()
    with page.expect_download() as download:
        page.get_by_role('link', name='تنزيل المعاينة PDF', exact=True).click()
    download.value.save_as(str(OUT / 'edited-report.pdf'))
    assert (OUT / 'edited-report.pdf').read_bytes().startswith(b'%PDF')
    page.get_by_role('button', name='المسؤوليات', exact=True).click()
    expect(page.locator('select[id$="-responsibility_mode"]')).to_be_focused()
    page.get_by_role('button', name='الاقتراحات', exact=True).click()
    expect(page.locator('select[id$="-proposal_mode"]')).to_be_focused()
    page.set_viewport_size({'width': 390, 'height': 844})
    page.get_by_role('button', name='تحرير المحضر قبل الطباعة', exact=True).click()
    expect(page.locator('.report-document-frame')).to_be_visible()
    frame = page.frame_locator('iframe[title="تحرير نص المحضر مباشرة"]')
    expect(frame.locator('html')).to_have_class('document-edit-viewport')
    assert frame.locator('html').evaluate('(el) => el.scrollWidth > el.clientWidth && el.scrollHeight > el.clientHeight')
    page.get_by_role('button', name='نهاية المحضر ↓', exact=True).click()
    assert frame.locator('html').evaluate('el => el.scrollTop > 0')
    page.get_by_role('button', name='بداية المحضر ↑', exact=True).click()
    assert frame.locator('html').evaluate('el => el.scrollTop === 0')
    frame.locator('html').evaluate('el => el.scrollLeft = -100')
    assert frame.locator('html').evaluate('el => Math.abs(el.scrollLeft) > 0')
    page.get_by_role('button', name='تحديث المحضر', exact=True).click()
    expect(frame.locator('[data-edit-key="value:note_text"] textarea')).to_have_value('نص باق رغم انقطاع الحفظ')
    page.screenshot(path=str(OUT / 'mobile.png'), full_page=True)
    assert not errors, errors
    proof = {'result': 'PASS', 'checks': ['direct text edits', 'autosave during typing', 'closing persistence',
        'failed save/retry', 'PDF download', 'responsibility/proposal navigation', 'mobile editor', 'vertical and horizontal scrolling',
        'first editable field navigation', 'refresh preserves saved content'], 'page_errors': errors}
    (OUT / 'browser.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    print(json.dumps(proof), flush=True)
    browser.close()

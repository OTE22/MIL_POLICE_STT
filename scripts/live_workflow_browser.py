"""Read-only post-deployment checks using an explicitly authorized two-minute session."""
import hashlib
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

expect.set_options(timeout=30000)

BASE = 'http://host.docker.internal'
SESSION = '04176210-31ec-46e5-9637-c1aff1747d1b'
OUT = Path('/artifacts/live-workflow')
OUT.mkdir(exist_ok=True)
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage'])
    context = browser.new_context(viewport={'width': 1600, 'height': 1000}, ignore_https_errors=True)
    token = os.environ['WORKFLOW_VERIFICATION_TOKEN']
    context.add_init_script('sessionStorage.setItem("mstt.access_token", ' + json.dumps(token) + ')')
    page = context.new_page()
    errors = []
    writes = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def readonly(route):
        request = route.request
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and not request.url.endswith('/report/html/preview'):
            writes.append({'method': request.method, 'path': request.url.split('/api', 1)[-1]})
            route.abort()
        else:
            route.continue_()

    page.route('**/api/**', readonly)
    headers = {'Authorization': 'Bearer ' + token}
    response = context.request.get(BASE + '/api/investigations/' + SESSION, headers=headers)
    assert response.ok, response.status
    session = response.json()
    report = context.request.get(BASE + '/api/investigations/' + SESSION + '/report/html', headers=headers)
    catalogue = context.request.get(BASE + '/api/investigations/participant-requirements', headers=headers)
    assert catalogue.ok and any(field['key'] == 'prior_record_statement' for field in catalogue.json()['fields'])
    statuses = {}
    for suffix, name in [('?tab=details', 'details'), ('?tab=transcript', 'transcript'), ('?tab=speakers', 'speakers')]:
        page.goto(BASE + '/investigations/' + SESSION + suffix)
        expect(page.locator('main')).to_be_visible(timeout=30000)
        expect(page).not_to_have_url(BASE + '/login')
        page.screenshot(path=str(OUT / (name + '.png')), full_page=True)
        statuses[name] = 'PASS'
    # Do not create a draft during read-only verification.
    if report.ok or session['intake_readiness']['ready'] is False:
        page.goto(BASE + '/investigations/' + SESSION + '/report')
        expect(page.get_by_text('تعذر تحميل المحضر. أعد المحاولة.', exact=True)).to_have_count(0)
        if report.ok:
            expect(page.get_by_test_id('html-report-editor')).to_be_visible(timeout=30000)
        else:
            expect(page.get_by_text('استكمال بيانات الأشخاص', exact=False).first).to_be_visible(timeout=30000)
        page.screenshot(path=str(OUT / 'report.png'), full_page=True)
        statuses['report'] = 'PASS'
    assert not writes, writes
    assert not errors, errors
    result = {'result': 'PASS', 'pages': statuses, 'intake_ready': session['intake_readiness']['ready'],
              'report_api_status': report.status, 'browser_errors': errors, 'mutations_attempted': writes}
    (OUT / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    browser.close()
    print('Live browser verification PASS; no investigation records changed', flush=True)

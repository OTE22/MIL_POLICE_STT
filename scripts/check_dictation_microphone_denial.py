"""Browser recovery: native unavailable capture and an explicitly simulated permission denial."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

expect.set_options(timeout=30000)

BASE = 'https://workflow-ui-frontend'
session = os.environ['WORKFLOW_TEST_SESSION']
token = os.environ['WORKFLOW_VERIFICATION_TOKEN']
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage', '--use-fake-device-for-media-stream',
        '--unsafely-treat-insecure-origin-as-secure=' + BASE])
    context = browser.new_context(ignore_https_errors=True, viewport={'width': 1600, 'height': 1000})
    context.grant_permissions([], origin=BASE)
    context.add_init_script('sessionStorage.setItem("mstt.access_token", ' + json.dumps(token) + '); localStorage.setItem("mstt.agent_url", "' + BASE + '/agent");')
    page = context.new_page()
    page.goto(BASE)
    assert page.evaluate("navigator.permissions.query({name:'microphone'}).then(p => p.state)") == 'denied'
    headers = {'Authorization': 'Bearer ' + token}
    endpoint = BASE + '/api/investigations/' + session + '/report'
    before = context.request.get(endpoint + '/html', headers=headers).json()
    jobs = context.request.get(endpoint + '/dictations', headers=headers).json()
    page.goto(BASE + '/investigations/' + session + '/report')
    expect(page.get_by_test_id('html-report-editor')).to_be_visible()
    page.locator('.report-outline-item > button').filter(has_text='ملاحظة بعد خلاصة التحقيق').click()
    page.get_by_role('button', name='إملاء صوتي — الملاحظة', exact=True).click()
    voice = page.get_by_role('region', name='إملاء المحقق')
    voice.get_by_role('button', name='بدء التسجيل', exact=True).click()
    expect(voice.get_by_text('تعذر فتح الميكروفون. تأكد من توصيله ومن إعدادات الصوت ثم أعد المحاولة.', exact=True)).to_be_visible()
    # Headless shell reports NotSupportedError for native denied capture; explicitly inject
    # NotAllowedError to exercise the distinct permission-denial message without claiming hardware proof.
    page.evaluate("() => { navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Test permission denial', 'NotAllowedError')); }")
    voice.get_by_role('button', name='بدء التسجيل', exact=True).click()
    expect(voice.get_by_text('لم يُسمح باستخدام الميكروفون. فعّل الإذن من إعدادات الموقع ثم أعد المحاولة.', exact=True)).to_be_visible()
    expect(voice.get_by_role('button', name='تحويل التسجيل إلى نص', exact=True)).to_be_disabled()
    assert context.request.get(endpoint + '/dictations', headers=headers).json() == jobs
    assert context.request.get(endpoint + '/html', headers=headers).json()['token'] == before['token']
    output = Path('/artifacts/microphone-denial')
    output.mkdir(exist_ok=True)
    page.screenshot(path=str(output / 'permission-denied.png'), full_page=True)
    (output / 'verification.json').write_text(json.dumps({'result': 'PASS', 'browser': browser.version,
        'cases': ['native headless capture unavailable', 'simulated NotAllowedError'], 'dictations_created': 0, 'report_changed': False}, indent=2), encoding='utf-8')
    browser.close()
    print('Microphone recovery PASS; native unavailable capture and simulated permission denial; no dictation or report changes', flush=True)

"""Read-only live browser diagnosis, using the authorized short verification session."""
import json
from datetime import datetime, timezone
from sqlalchemy import select
from app.config import get_settings
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import User
from playwright.sync_api import sync_playwright

settings = get_settings()
with SessionLocal() as db:
    user = db.scalar(select(User).where(User.username == settings.bootstrap_admin_username, User.is_active.is_(True)))
    token, _ = create_access_token(user.id, user.username, {'exp': int(datetime.now(timezone.utc).timestamp()) + 120, 'auth_mode': settings.auth_mode})
BASE = 'http://host.docker.internal'
path = '/investigations/04176210-31ec-46e5-9637-c1aff1747d1b'
with sync_playwright() as p:
    browser = p.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage'])
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    context.add_init_script('sessionStorage.setItem("mstt.access_token", ' + json.dumps(token) + ')')
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda err: errors.append(str(err)))
    page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' else None)
    page.route('**/api/**', lambda route: route.continue_() if route.request.method in ('GET', 'HEAD', 'OPTIONS') or route.request.url.endswith('/report/html/preview') else route.abort())
    headers = {'Authorization': 'Bearer ' + token}
    state = context.request.get(BASE + '/api' + path + '/report/html', headers=headers).json()
    session = context.request.get(BASE + '/api' + path, headers=headers).json()
    page.goto(BASE + path + '/report')
    page.get_by_role('button', name='تحرير المحضر قبل الطباعة', exact=True).click(timeout=30000)
    page.wait_for_timeout(3000)
    frame = page.frame_locator('iframe[title="تحرير نص المحضر مباشرة"]')
    page.get_by_role('button', name='انتقل إلى أول نص قابل للتحرير', exact=True).click()
    assert frame.locator('textarea:focus').count() == 1
    assert frame.locator('html').evaluate('el => getComputedStyle(el).overflowY === "scroll"')
    markers = frame.locator('.qa-row .margin-marker').all_text_contents()
    assert markers and all(marker == 'س/ج' for marker in markers)
    closing_position = 'not present'
    if state['document'].get('closing'):
        layout = frame.locator('.closing-signatures').evaluate('''el => {
            const date = el.querySelector('.closing-dateline').getBoundingClientRect();
            const clerk = el.querySelector('.closing-clerk').getBoundingClientRect();
            const investigator = el.querySelector('.closing-investigator').getBoundingClientRect();
            return {left: date.right <= clerk.x, above: date.bottom <= investigator.y,
                    isolated: el.querySelector('.closing-date').dir === 'ltr'};
        }''')
        assert all(layout.values()), layout
        closing_position = 'PASS'
    result = {'status': state['status'], 'workflow': session['workflow_state'], 'intake_ready': session['intake_readiness']['ready'],
        'inputs': frame.locator('textarea').count(), 'enabled': frame.locator('textarea:enabled').count(),
        'frames': len(page.frames), 'statement_margin_markers': len(markers), 'closing_date_position': closing_position, 'field_navigation': 'PASS', 'scrollbars': 'PASS', 'errors': errors}
    print(json.dumps(result), flush=True)
    assert context.request.get(BASE + '/api' + path + '/report/html', headers=headers).json()['token'] == state['token']
    browser.close()

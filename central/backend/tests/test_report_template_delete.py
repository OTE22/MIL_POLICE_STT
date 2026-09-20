import uuid
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import AuditLog, GeneratedReport, ReportTemplateVersion
from app.services.report_storage import absolute_path
from conftest import auth, create_session
from test_report_templates_api import _admin, _templates, _upload, _valid_template


def test_delete_unused_template_removes_file_and_row_audits_and_never_reuses_version(client):
    token = _admin(client)
    version = _upload(client, token, _valid_template()).json()['versions'][0]
    with SessionLocal() as db:
        path = absolute_path(db.get(ReportTemplateVersion, uuid.UUID(version['id'])).storage_path)
    assert path.is_file()
    response = client.delete(f"/api/report-templates/{version['id']}", headers=auth(token))
    assert response.status_code == 200, response.text
    assert all(v['id'] != version['id'] for v in response.json()['versions'])
    assert not path.exists()
    with SessionLocal() as db:
        assert db.get(ReportTemplateVersion, uuid.UUID(version['id'])) is None
        audit = db.scalar(select(AuditLog).where(AuditLog.action == 'REPORT_TEMPLATE_DELETED'))
        assert audit.entity_id == version['id'] and audit.safe_metadata['version'] == version['version']
    assert _upload(client, token, _valid_template()).json()['versions'][0]['version'] > version['version']
    assert client.delete(f"/api/report-templates/{version['id']}", headers=auth(token)).status_code == 404


def test_delete_permissions_and_active_protection(client, investigator):
    token = _admin(client)
    active = _templates(client, token)['active']
    url = f"/api/report-templates/{active['id']}"
    assert client.delete(url).status_code == 401
    assert client.delete(url, headers=auth(investigator['token'])).status_code == 403
    response = client.delete(url, headers=auth(token))
    assert response.status_code == 409
    assert response.json()['detail'] == 'report_template_delete_active'
    assert client.get(url + '/file', headers=auth(token)).status_code == 200


def test_delete_preserves_template_referenced_by_issued_report(client):
    token = _admin(client)
    version = _upload(client, token, _valid_template()).json()['versions'][0]
    session = create_session(client, token)
    with SessionLocal() as db:
        db.add(GeneratedReport(session_id=uuid.UUID(session['id']), report_version=1,
                               template_version_id=uuid.UUID(version['id']),
                               storage_path='reports/test.docx', docx_sha256='a' * 64))
        db.commit()
    url = f"/api/report-templates/{version['id']}"
    response = client.delete(url, headers=auth(token))
    assert response.status_code == 409
    assert response.json()['detail'] == 'report_template_delete_used'
    assert client.get(url + '/file', headers=auth(token)).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(GeneratedReport.id)) is not None


def test_invalid_unused_template_can_be_deleted(client):
    token = _admin(client)
    version = _upload(client, token, b'invalid docx').json()['versions'][0]
    assert version['validation_status'] == 'INVALID'
    assert client.delete(f"/api/report-templates/{version['id']}", headers=auth(token)).status_code == 200

from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1] / 'central/backend/tests'
def edit(name, fn):
    p = ROOT / name
    p.write_text(fn(p.read_text(encoding='utf-8')), encoding='utf-8')

def civilians(s):
    s = s.replace('from app.services.person_identity import allocate_civilian_reference', 'from app.services.person_identity import create_identity')
    s = s.replace('    from app.services.person_identity import find_identity\n', '')
    s = s.replace('found = find_identity(db, reference)', 'found = db.get(PersonIdentity, uuid.UUID(reference))')
    s = s.replace('reference_number', 'identity_id')
    s = s.replace('subject["identity_id"].startswith("CIV-")', 'uuid.UUID(subject["identity_id"])')
    s = s.replace('all(r.startswith("CIV-") for r in refs.values())', 'all(uuid.UUID(r) for r in refs.values())')
    s = s.replace('PersonIdentity.reference_display == first["identity_id"]', 'PersonIdentity.id == uuid.UUID(first["identity_id"])')
    s = s.replace('PersonIdentity.reference_display == reference', 'PersonIdentity.id == uuid.UUID(reference)')
    start = s.index('def test_references_are_sequential_and_fixed_width')
    end = s.index('def test_concurrent_civilian_creation_never_collides', start)
    s = s[:start] + s[end:]
    s = s.replace('reference = allocate_civilian_reference(db)', 'reference = str(create_identity(db, "شخص").id)')
    return s
edit('test_civilian_identity.py', civilians)

def names(s):
    s = s.replace('PersonNameRequired, get_or_create_identity', 'PersonNameRequired, create_identity, resolve_identity')
    s = re.sub(r'get_or_create_identity\(db, "[^"]*", ', 'create_identity(db, ', s)
    s = s.replace('again = create_identity(db, None)', 'again = resolve_identity(db, db.get(PersonIdentity, created.id))')
    s = s.replace('reference_number', 'identity_id')
    s = s.replace('"(id, reference_normalized, reference_display, person_name) "', '"(id, person_name) "').replace('f"VALUES (gen_random_uuid(), \'X-{bad}\', \'X\', {bad})"', 'f"VALUES (gen_random_uuid(), {bad})"')
    return s
edit('test_person_name_required.py', names)

# The registry tests now exercise UUID lookup, merges, and identifier races directly.
p = ROOT / 'test_person_identity.py'
s = p.read_text(encoding='utf-8')
merges = s[s.index('def test_merge_keeps_the_source_as_an_alias'):]
merges = re.sub(r'get_or_create_identity\(db, (?:f)?"[^"]*", ', 'create_identity(db, ', merges)
merges = merges.replace('resolved = create_identity(db, "علي")', 'resolved = resolve_identity(db, db.get(PersonIdentity, b.id))')
p.write_text('''"""Person UUID creation, identifier normalization and concurrent merge safety."""
import threading
import uuid
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import PersonIdentity
from app.services.person_identity import create_identity, resolve_identity, normalize_identifier, identity_for_person

@pytest.mark.parametrize("value, expected", [(None,None),("  ",None),(" ab-٤٤٧١ ","AB-4471"),("ab  4471","AB 4471")])
def test_external_identifier_normalization(value, expected):
    assert normalize_identifier(value) == expected

def test_same_names_do_not_reuse_identity():
    with SessionLocal() as db:
        a = create_identity(db, "علي")
        b = create_identity(db, "علي")
        assert a.id != b.id

def test_concurrent_military_claims_reuse_one_uuid():
    ids, errors = [], []
    barrier = threading.Barrier(2)
    def create():
        try:
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                person = identity_for_person(db, SimpleNamespace(subject_name="علي", military_id="4471", security_branch="ARMY"))
                db.commit()
                ids.append(person.id)
        except Exception as exc:
            errors.append(str(exc))
    threads = [threading.Thread(target=create) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=20)
    assert not errors
    assert len(ids) == 2 and ids[0] == ids[1]

''' + merges, encoding='utf-8')

# Consolidation still exercises every link, but resolves a service number as evidence.
def consolidation(s):
    s = s.replace('from app.services.person_identity import find_identity', 'from app.services.person_identifiers import find_by_identifier\n\ndef find_identity(db, value):\n    return find_by_identifier(db, identifier_type="MILITARY", issuer="ARMY", value=value.removeprefix("MIL-ARMY-"))')
    s = re.sub(r'^.*(?:reference_number=reference|assert subject.reference_number|assert speaker.reference_number).*\n', '', s, flags=re.M)
    return s
edit('test_identity_consolidation.py', consolidation)

# Batch matcher fixtures need only UUIDs and names.
for file in ['test_batch_voice_matching.py']:
    edit(file, lambda s: re.sub(r'^.*(?:reference_normalized=|reference_display=|person_reference=).*\n', '', s, flags=re.M))

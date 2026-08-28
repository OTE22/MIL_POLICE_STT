"""Deriving الرقم المرجعي from identifiers the operator already entered.

The invariant these tests defend: derivation must reduce duplicate identities **without ever
increasing the risk of merging two different real people**. So every case that cannot be keyed
safely returns None and the operator types the reference by hand — failing to derive is
recoverable, merging two people is not.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.db.session import SessionLocal
from app.models.enums import PersonType, SecurityBranch, SubjectDocumentType
from app.services.lebanon_cazas import CAZAS, caza_code, is_valid_caza
from app.services.person_identity import (
    allocate_temporary_reference,
    derive_reference,
    get_or_create_identity,
)


@dataclass
class FakeDocument:
    document_type: SubjectDocumentType
    document_number: str | None = None


@dataclass
class FakeSubject:
    """Stands in for a Subject row or a SubjectIn - derive_reference reads fields, not types."""

    person_type: PersonType = PersonType.CIVILIAN
    subject_name: str | None = "شخص"
    military_id: str | None = None
    security_branch: SecurityBranch | None = None
    register_number: str | None = None
    caza_code: str | None = None
    is_undocumented: bool = False
    documents: list[FakeDocument] = field(default_factory=list)


# --------------------------------------------------------------------------
# military: the serial is unique PER FORCE
# --------------------------------------------------------------------------

def test_military_reference_includes_the_force():
    subject = FakeSubject(
        person_type=PersonType.MILITARY, military_id="4471", security_branch=SecurityBranch.ARMY
    )
    assert derive_reference(subject) == "MIL-ARMY-4471"


def test_the_same_serial_in_two_forces_is_two_people():
    """The reason the branch is in the key at all."""
    army = FakeSubject(person_type=PersonType.MILITARY, military_id="4471",
                       security_branch=SecurityBranch.ARMY)
    isf = FakeSubject(person_type=PersonType.MILITARY, military_id="4471",
                      security_branch=SecurityBranch.ISF)
    assert derive_reference(army) != derive_reference(isf)


@pytest.mark.parametrize("branch", [None, SecurityBranch.OTHER])
def test_no_usable_force_means_no_derivation(branch):
    """OTHER is a catch-all, not a namespace: two 'other' forces would collide."""
    subject = FakeSubject(person_type=PersonType.MILITARY, military_id="4471", security_branch=branch)
    assert derive_reference(subject) is None


# --------------------------------------------------------------------------
# civilians are ISSUED a reference; رقم السجل identifies a family, not a person
# --------------------------------------------------------------------------

def test_a_civilian_is_issued_a_reference_not_keyed_on_their_civil_record():
    subject = FakeSubject(person_type=PersonType.CIVILIAN, register_number="725", caza_code="BEIRUT")
    assert derive_reference(subject, allocate_civilian=lambda: "CIV-00000001") == "CIV-00000001"


def test_the_civil_register_never_becomes_a_canonical_reference():
    """An إخراج قيد lists a whole family under one رقم سجل, so keying on it merged relatives:
    refused when their names differed, silently joined when they matched."""
    subject = FakeSubject(person_type=PersonType.CIVILIAN, register_number="725", caza_code="BEIRUT")
    assert derive_reference(subject) is None, "no allocator means nothing is issued"

    issued = []
    derive_reference(subject, allocate_civilian=lambda: issued.append(1) or "CIV-00000001")
    assert issued, "the civil record must not short-circuit issuing"


def test_two_relatives_sharing_a_civil_record_get_different_references():
    ali = FakeSubject(person_type=PersonType.CIVILIAN, register_number="123", caza_code="ZAHLE")
    hasan = FakeSubject(person_type=PersonType.CIVILIAN, register_number="123", caza_code="ZAHLE")
    seq = iter(["CIV-00000145", "CIV-00000146"])
    assert derive_reference(ali, allocate_civilian=lambda: next(seq)) == "CIV-00000145"
    assert derive_reference(hasan, allocate_civilian=lambda: next(seq)) == "CIV-00000146"


@pytest.mark.parametrize("caza", [None, "", "بيروت", "Beyrouth", "INVENTED", "BEIRUT"])
def test_the_caza_no_longer_affects_the_canonical_reference(caza):
    """Recognised or not, محل القيد is now metadata: it never changes who the person is."""
    subject = FakeSubject(person_type=PersonType.CIVILIAN, register_number="725", caza_code=caza)
    assert derive_reference(subject, allocate_civilian=lambda: "CIV-00000009") == "CIV-00000009"


def test_backend_owns_the_caza_vocabulary():
    assert is_valid_caza("BEIRUT") and is_valid_caza("beirut")
    assert not is_valid_caza("بيروت")
    assert not is_valid_caza("INVENTED")
    assert caza_code(" tripoli ") == "TRIPOLI"
    assert caza_code("nope") is None


def test_frontend_caza_list_cannot_drift_from_the_backend():
    """The picker is generated from the Python list; this proves they still agree."""
    candidates = [
        Path("/frontend/src/lib/cazas.ts"),                                   # mounted in the test container
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "cazas.ts",  # repo checkout
    ]
    ts = next((c for c in candidates if c.exists()), None)
    if ts is None:
        pytest.skip("frontend tree not mounted; run with -v <repo>/central/frontend:/frontend:ro")
    codes = set(re.findall(r'code:\s*"([A-Z_]+)"', ts.read_text(encoding="utf-8")))
    assert codes == set(CAZAS), f"drifted: only in TS {codes - set(CAZAS)}, only in PY {set(CAZAS) - codes}"


# --------------------------------------------------------------------------
# namespaces that collide across identifier kinds
# --------------------------------------------------------------------------

def test_the_same_number_in_two_identifier_kinds_stays_two_people():
    """A military serial and a civil-registry number that share digits are not one person."""
    soldier = FakeSubject(person_type=PersonType.MILITARY, military_id="4471",
                          security_branch=SecurityBranch.ARMY)
    civilian = FakeSubject(register_number="4471", caza_code="BEIRUT")
    assert derive_reference(soldier) != derive_reference(civilian)


# --------------------------------------------------------------------------
# refugee documents: agency-wide
# --------------------------------------------------------------------------

def test_agency_cards_are_evidence_not_canonical_references():
    """UNHCR / UNRWA numbers help FIND a person; they are no longer the person key itself.

    The canonical reference belongs to the human and must survive a document being reissued,
    corrected or replaced - so it is issued by us, and the card number is attached as an
    external identifier instead.
    """
    for doc_type, number in (
        (SubjectDocumentType.UNHCR_CARD, "556677"),
        (SubjectDocumentType.UNRWA_CARD, "443322"),
    ):
        subject = FakeSubject(
            person_type=PersonType.CIVILIAN, documents=[FakeDocument(doc_type, number)]
        )
        assert derive_reference(subject) is None
        assert derive_reference(subject, allocate_civilian=lambda: "CIV-00000312") == "CIV-00000312"


@pytest.mark.parametrize(
    "doc_type",
    [
        SubjectDocumentType.PASSPORT,
        SubjectDocumentType.RESIDENCY_PERMIT,
        SubjectDocumentType.NATIONAL_ID,
        SubjectDocumentType.CIVIL_EXTRACT,
        SubjectDocumentType.DRIVING_LICENSE,
    ],
)
def test_issuer_keyed_documents_are_not_derived(doc_type):
    """Their namespace is the issuer, and issuing_country is free text today. Do not guess."""
    subject = FakeSubject(documents=[FakeDocument(doc_type, "1234567")])
    assert derive_reference(subject) is None


# --------------------------------------------------------------------------
# nothing to key on
# --------------------------------------------------------------------------

def test_an_incomplete_subject_gets_nothing():
    """A half-filled form must not acquire an identity."""
    assert derive_reference(FakeSubject(), allocate_temporary=lambda: "TMP-X") is None


def test_an_undocumented_civilian_still_gets_a_civilian_reference():
    """Having no papers does not make someone unclassified: they are a civilian we can name."""
    subject = FakeSubject(person_type=PersonType.CIVILIAN, is_undocumented=True)
    assert derive_reference(
        subject, allocate_civilian=lambda: "CIV-00000042", allocate_temporary=lambda: "TMP-X"
    ) == "CIV-00000042"


def test_only_an_unclassified_person_gets_a_temporary_reference():
    """TMP is a placeholder for someone not yet classified - not a badge for missing papers."""
    subject = FakeSubject(person_type=PersonType.UNKNOWN)
    assert derive_reference(subject, allocate_temporary=lambda: "TMP-2026-000123") == "TMP-2026-000123"


def test_no_allocator_means_nothing_is_issued():
    assert derive_reference(FakeSubject(person_type=PersonType.UNKNOWN)) is None
    assert derive_reference(FakeSubject(person_type=PersonType.CIVILIAN)) is None


# --------------------------------------------------------------------------
# TMP allocation
# --------------------------------------------------------------------------

def test_temporary_references_are_sequential_and_shaped():
    with SessionLocal() as db:
        first = allocate_temporary_reference(db)
        second = allocate_temporary_reference(db)
        db.commit()
    assert re.fullmatch(r"TMP-\d{4}-\d{6}", first), first
    assert first != second


def test_concurrent_temporary_allocation_never_collides():
    """Two investigators registering undocumented people at the same moment.

    A sequence is what makes this safe; COUNT(*)+1 or MAX()+1 would hand out the same value.
    """
    issued: list[str] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        try:
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                reference = allocate_temporary_reference(db)
                identity = get_or_create_identity(db, reference, "غير محدد الهوية")
                db.commit()
                issued.append(str(identity.id))
        except Exception as exc:  # noqa: BLE001 - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"unexpected errors: {errors}"
    assert len(issued) == 2
    assert issued[0] != issued[1], "two undocumented people must not collapse into one identity"


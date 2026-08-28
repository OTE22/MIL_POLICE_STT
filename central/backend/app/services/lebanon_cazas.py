"""The Lebanese أقضية, as the authoritative vocabulary for محل القيد.

رقم السجل is unique **within a قضاء**, not nationally: the same number legitimately exists in
Beirut and in Tripoli for two different people. So a civilian canonical reference is only safe
when it carries the قضاء, and only when that قضاء came from a recognised code — free text
("بيروت", "Beirut", "بيروت - الأشرفية") is not a namespace.

This module is the single owner of that list. The frontend picker in
`central/frontend/src/lib/cazas.ts` is generated from it, and a test asserts the two cannot
drift. Bundled offline, like the countries list; nothing is fetched.
"""

from __future__ import annotations

# code -> (Arabic name, governorate). 26 أقضية.
CAZAS: dict[str, tuple[str, str]] = {
    "BEIRUT": ("بيروت", "بيروت"),
    # جبل لبنان
    "JBEIL": ("جبيل", "جبل لبنان"),
    "KESERWAN": ("كسروان", "جبل لبنان"),
    "MATN": ("المتن", "جبل لبنان"),
    "BAABDA": ("بعبدا", "جبل لبنان"),
    "ALEY": ("عاليه", "جبل لبنان"),
    "CHOUF": ("الشوف", "جبل لبنان"),
    # الشمال
    "TRIPOLI": ("طرابلس", "الشمال"),
    "ZGHARTA": ("زغرتا", "الشمال"),
    "BSHARRI": ("بشري", "الشمال"),
    "BATROUN": ("البترون", "الشمال"),
    "KOURA": ("الكورة", "الشمال"),
    "MINIEH_DANNIEH": ("المنية - الضنية", "الشمال"),
    # عكار
    "AKKAR": ("عكار", "عكار"),
    # البقاع
    "ZAHLE": ("زحلة", "البقاع"),
    "WEST_BEQAA": ("البقاع الغربي", "البقاع"),
    "RACHAYA": ("راشيا", "البقاع"),
    # بعلبك - الهرمل
    "BAALBEK": ("بعلبك", "بعلبك - الهرمل"),
    "HERMEL": ("الهرمل", "بعلبك - الهرمل"),
    # الجنوب
    "SIDON": ("صيدا", "الجنوب"),
    "TYRE": ("صور", "الجنوب"),
    "JEZZINE": ("جزين", "الجنوب"),
    # النبطية
    "NABATIEH": ("النبطية", "النبطية"),
    "MARJEYOUN": ("مرجعيون", "النبطية"),
    "HASBAYA": ("حاصبيا", "النبطية"),
    "BINT_JBEIL": ("بنت جبيل", "النبطية"),
}


def is_valid_caza(code: str | None) -> bool:
    """Only a recognised code may act as an identity namespace.

    Frontend validation is a convenience; this is the integrity check.
    """
    return bool(code) and code.strip().upper() in CAZAS


def caza_code(code: str | None) -> str | None:
    """The canonical code, or None when it is not one of ours."""
    if not code:
        return None
    normalized = code.strip().upper()
    return normalized if normalized in CAZAS else None


def caza_name(code: str | None) -> str | None:
    entry = CAZAS.get((code or "").strip().upper())
    return entry[0] if entry else None

"""Role / permission catalogue. Seeded into the database at startup."""

from __future__ import annotations

ROLE_ADMIN = "ADMIN"
ROLE_INVESTIGATOR = "INVESTIGATOR"
ROLE_USER = "USER"

PERMISSIONS: dict[str, str] = {
    "users.manage": "Create, edit, disable users, reset passwords, assign roles",
    "users.read": "View user accounts",
    "investigators.read": "View investigator profiles",
    "investigations.create": "Create investigation sessions",
    "investigations.read_all": "View every investigation session",
    "investigations.read_assigned": "View sessions created by or assigned to the user",
    "investigations.update": "Edit investigation sessions the user can access",
    "investigations.archive": "Archive investigation sessions",
    "recordings.create": "Record or upload audio",
    "subjects.documents.view": "View identity documents (ID/passport scans) of interviewed persons",
    # الرقم المرجعي is normally DERIVED from the structured identifiers, never typed. This is
    # the exceptional path: overriding a derived reference, or assigning one when derivation
    # is not possible. It is its own permission because no existing one expresses it -
    # investigations.update means "may edit this session" and investigations.read_all means
    # "may see every session"; neither means "may hand-assign a canonical business key".
    "subjects.reference.override": "Manually assign or override الرقم المرجعي of a person",
    "processing.request": "Request local AI processing",
    "transcripts.read": "View transcripts",
    "transcripts.edit": "Correct transcript text",
    "speakers.assign": "Map anonymous speakers to names",
    "voice.identify": "See voice-based identity suggestions and confirm or reject them",
    "voice.enroll": "Create and remove voice enrolments (biometric templates)",
    "system.configure": "Change runtime system settings (logging, matching, limits) from the interface",
    "workstations.read": "View workstation status",
    "workstations.register": "Register / refresh the local workstation",
    "audit.read": "View audit logs",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    ROLE_ADMIN: set(PERMISSIONS.keys()),
    ROLE_INVESTIGATOR: {
        "investigators.read",
        "investigations.create",
        "investigations.read_assigned",
        "investigations.update",
        "investigations.archive",
        "recordings.create",
        "subjects.documents.view",
        "processing.request",
        "transcripts.read",
        "transcripts.edit",
        "speakers.assign",
        "voice.identify",
        "voice.enroll",
        "workstations.read",
        "workstations.register",
    },
    ROLE_USER: {
        "investigations.read_assigned",
        "transcripts.read",
    },
}

ROLE_DESCRIPTIONS = {
    ROLE_ADMIN: "System administrator",
    ROLE_INVESTIGATOR: "Investigator / interviewer",
    ROLE_USER: "Read-only user",
}

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
    "processing.request": "Request local AI processing",
    "transcripts.read": "View transcripts",
    "transcripts.edit": "Correct transcript text",
    "speakers.assign": "Map anonymous speakers to names",
    "voice.identify": "See voice-based identity suggestions and confirm or reject them",
    "voice.enroll": "Create and remove voice enrolments (biometric templates)",
    # The محضر تحقيق. Reading a report and ISSUING one are separate authorities: a draft is
    # working material, a finalized report is a document that leaves the building.
    "reports.read": "View investigation report drafts and the archive of issued reports",
    "reports.generate": "Create and edit the investigation report draft (محضر تحقيق)",
    "reports.finalize": "Issue the final official report document",
    "reports.templates.manage": "Upload, validate and activate the official report template",
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
        "reports.read",
        "reports.generate",
        "reports.finalize",
        "workstations.read",
        "workstations.register",
    },
    ROLE_USER: {
        "investigations.read_assigned",
        "transcripts.read",
        "reports.read",
    },
}

ROLE_DESCRIPTIONS = {
    ROLE_ADMIN: "System administrator",
    ROLE_INVESTIGATOR: "Investigator / interviewer",
    ROLE_USER: "Read-only user",
}

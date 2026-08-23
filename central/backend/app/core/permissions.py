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
    "processing.request": "Request local AI processing",
    "transcripts.read": "View transcripts",
    "transcripts.edit": "Correct transcript text",
    "speakers.assign": "Map anonymous speakers to names",
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
        "processing.request",
        "transcripts.read",
        "transcripts.edit",
        "speakers.assign",
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

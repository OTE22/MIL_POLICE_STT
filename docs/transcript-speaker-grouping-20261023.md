# Transcript speaker grouping — 2026-10-23

The transcript viewer now shows one speaker heading for consecutive fragments from
the same label. Every original fragment remains visible beneath it, with its own
text, timestamp, playback position, correction controls and edit attribution.
Timestamps display the stored millisecond precision; this does not imply a new
measurement of model accuracy.

Grouping is a frontend projection only. It retains source IDs and order, requires
consecutive sequences and a pause of at most two seconds, and keeps overlapping
speech separate. Groups are formed before filtering so hiding a different speaker
cannot join two interrupted turns. No source records, report logic, or models change.

Validation:

- Nine Node checks passed, including rendering the actual React viewer: eight
  source fragments remain visible under four speaker headings, with all individual
  times and text in order. Source objects remain unchanged.
- TypeScript validation and the production frontend build passed.
- A database transaction with `SET TRANSACTION READ ONLY` checked the existing
  SPEAKER_34/35 recording through the live report builder: eight fragments became
  four report turns (2, 1, 3, 2 fragments), retaining all source references through
  question/answer construction. No records were changed.
- The deployed JavaScript and CSS byte hashes match the tested build; the local
  application returns HTTP 200 and backend/database health is OK. An interactive
  browser was unavailable, so visual interaction was not checked in a browser.

Frontend image: `military-stt/central-frontend:turn-grouping-20261023`, also tagged
`1.0.0`, image ID `sha256:0853248e21e94cdd9d7f78a0206327a4f6f9091ac4044ff96db49f08becbe027`.
The previous frontend remains at `before-turn-grouping-20261023`.
Only the frontend was recreated; the reverse proxy configuration was reloaded.

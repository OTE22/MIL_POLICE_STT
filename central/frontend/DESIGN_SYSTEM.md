# Military Police interface

`src/styles/platform.css` owns the application design tokens and is imported last
in `main.tsx`. Existing workspace styles provide structure; the platform layer
provides the common shell, typography, surfaces, controls and responsive rules.

- Navy is the workspace background; graphite surfaces separate sections.
- Olive identifies primary actions and the active location. Statuses also have
  explicit text: green for success, amber for attention, red for errors.
- English uses locally hosted Inter. Arabic uses locally hosted IBM Plex Sans
  Arabic, with regular, medium, semibold and bold weights. Font licenses are in
  `public/fonts`. No font CDN is used by the application.
- Base text is 16 px, supporting text at least 14 px, and transcript text 17–18 px.
  Arabic uses generous line spacing; identifiers use tabular numerals and bidi
  isolation. Do not add fixed-height text containers or ellipsis for names.
- Use `Field` for labelled inputs, selects and textareas. It links the label,
  hint and error to the direct child control. Composite controls need their own
  accessible names. Use `Modal` for focus containment and focus restoration.
- Controls normally have a 44 px minimum target. Keyboard focus remains visible.
  Motion respects the operating system's reduced-motion setting.
- Mobile navigation is a dismissible drawer. Wide tables scroll in a named,
  keyboard-focusable region while dates, identifiers and statuses stay intact.
- Report editing uses dark application surfaces. Printable document paper stays
  white. Downloaded HTML embeds Inter and IBM Plex Sans Arabic and their licenses
  for offline viewing and printing.

Build with `npm run build`. From the repository root, run
`.venv-test/Scripts/python.exe scripts/platform_ui_audit.py` for synthetic browser
checks, or append `http://localhost` to check the deployed assets. The audit uses
local axe-core when `storage/test-artifacts/axe.min.js` is available. It writes
screenshots and `audit.json` to `storage/test-artifacts/platform` and never writes
to real application APIs. Run the existing speaker and investigation workspace
checks for recording, transcript and identity interaction regressions.

Automated checks cover the exercised routes and states. They complement manual
keyboard and visual review; they do not constitute a full accessibility certification.

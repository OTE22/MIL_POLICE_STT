# Military operations desk

The interface supports investigators who need to identify the next action, read evidence and distinguish reviewed facts from processing status. The dominant visual direction is industrial/utilitarian: graphite and olive work surfaces, khaki wayfinding, crisp section boundaries and calm typography.

The visual anchor is the khaki edge used consistently for selected navigation, the command overview and important actions. Color remains functional: blue information, green confirmation, amber pending attention and red errors. No classification markings, invented threat levels or decorative tactical data are added.

Design feasibility/impact assessment: impact 4, context fit 5, feasibility 4, performance 4, consistency risk 3; DFII 14 using the skill's formula.

## Shared system

- Fonts remain locally bundled Inter for English and IBM Plex Sans Arabic for Arabic, honoring the user's existing explicit font requirement. Arabic tracking remains neutral for connected glyphs.
- Main reading size: 17px. Secondary text minimum: 15px. Inputs: 16px. Labels: 16px/600. Headings use a clear 28-36px main hierarchy.
- Background `#101612`; surface `#1a241d`; raised surface `#314135`; text `#f5f4eb`; secondary text `#bdc9b8`; khaki `#d1c394`. Shared CSS variables own palette and semantic borders.
- An 8px spacing rhythm, restrained 5-9px corners, and stronger field/table boundaries keep dense operational screens readable.
- Motion stays limited to existing short interaction feedback; reduced-motion preferences remain supported. No new animated effects or network font requests.
- Disabled values retain readable text. Selection, hover, keyboard focus and disabled states remain visually distinct.

The result expresses the application's purpose through typography, restrained surfaces and operational wayfinding. Arabic RTL, English runs, mobile navigation, dialogs, forms and evidence workspaces share the same system. Official archived HTML/PDF documents and backend behavior are unchanged by this presentation update.

Deployed locally on 2026-10-26. Frontend image: `sha256:50d76c18641e1d6127ba2c7fb161fa7f2ab67ac7e41ca694671f0684cdd18ce0`. The live `/assets/index-BZrxE-1o.css` was verified to contain the olive/khaki palette and 15px/17px typography tokens. Frontend/backend health and database connectivity passed after deployment.

## Verification

TypeScript/Vite production build passed. The synthetic platform audit passed all 43 screen/state checks across five viewport widths, with zero visible text below 15px, zero axe WCAG A/AA findings, no page overflow and no runtime errors. Coverage includes application routes, dialogs, speaker states, login, keyboard focus and explicit LTR layout checks. See `storage/test-artifacts/military-frontend-audit.log` and `storage/test-artifacts/platform/audit.json` for the results. These are automated checks using synthetic content, complemented by visual inspection of dashboard and speaker-review screenshots.

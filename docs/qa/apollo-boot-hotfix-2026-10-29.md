# Apollo startup follow-up — 2026-10-29

Production browser QA of release `6fa00768f8a821aa03c049ecf49448ce421da626`
found an intermittent startup stall. The document remained `interactive` and
`apollo-booting` for over 30 seconds while a 16 MB first-party Studio project
PNG was still loading. The boot cover previously cleared only on `window.load`,
so an image delay could hide every app view despite healthy services and APIs.

The follow-up defers Studio artwork until it is needed and adds an idempotent
`DOMContentLoaded` fallback that clears the boot cover after 2.5 seconds even
when a noncritical image prevents `window.load`. The separate security conceal
class remains in force until the privacy state has initialized. No original
artwork, project file, or user record is changed.

An isolated Chrome fixture deliberately held an image request open. Both desktop
and 390 × 844 iPhone-sized runs became usable before `window.load`, opened
Settings, and had no page errors. The full Python suite passed 399 tests with
two optional skips; iOS configuration passed 16/16; production assets built;
JavaScript syntax and whitespace checks passed. This fixture is synthetic;
production browser QA must be repeated on the follow-up release SHA.

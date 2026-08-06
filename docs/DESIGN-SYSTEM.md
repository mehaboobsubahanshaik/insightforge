# Design System

**Feel**: confident instrument panel, light and colorful — closer to Linear
/ Stripe than to legacy BI grey.

* Canvas `#F4F7FB`; surfaces white with `#E4EAF2` borders; ink `#17233B`.
* Brand gradient `#4F46E5 → #7C3AED` (buttons, active states, loader ring).
* Categorical palette (charts, workspace glyphs): indigo `#4F46E5`, cyan
  `#06B6D4`, green `#16A34A`, amber `#F59E0B`, red `#EF4444`, violet
  `#8B5CF6`, pink `#EC4899`, lime `#84CC16`.
* Semantic: quality ≥90 green, 70–89 amber, <70 red; quarantine rows tinted
  `#FEF3F4`.
* Type: Plus Jakarta Sans (display), Inter (body), JetBrains Mono (numbers,
  readouts, code) — numbers are *always* mono so columns align.
* Motion: 120ms hover lifts; staggered card entrance; the magnifier loader
  (rotating gradient ring + drawing trendline) with rotating messages;
  everything behind `prefers-reduced-motion`.
* Accessibility: visible focus rings, aria-live on view container and
  loader, keyboard-activatable tiles/cards, WCAG AA contrast on text.
* Voice: readouts in small-caps mono — `FRESHNESS · QUALITY · GOVERNED`.

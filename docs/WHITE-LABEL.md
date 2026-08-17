# White-Label, Custom Domains, Portals, Localization, Accessibility (MVP4 E3)

## Theme
`PATCH /api/v1/tenants/theme` — brand_name, accent/background/foreground
(#hex), locale (en/es/fr/de/hi), white_label (true hides "Powered by
InsightForge"). Applied automatically to every embed and portal; validated
server-side (bad hex/locale → 422).

## Custom domains — production workflow
1. Owner: `POST /api/v1/tenants/custom-domain {"domain":"analytics.acme.com"}`
   (format-validated; uniqueness enforced → 409 if claimed).
2. Customer DNS: CNAME analytics.acme.com → platform host.
3. TLS: terminate at the platform proxy (e.g. Caddy/nginx + ACME on the
   stored domain list). Embeds/portals then serve under the vendor's domain;
   tokens work unchanged (signature-based, host-independent).

## Customer portals
`/portal.html?tokens=T1,T2&title=Acme%20Analytics&lang=es` — stacks any
number of embeds for one end-customer; each token carries its own filters.

## Localization
Viewer + portal UI strings in en/es/fr/de/hi via `?lang=` or theme.locale;
`<html lang>` set for screen readers. Data values are never translated.

## Accessibility (embed validation checklist)
- iframe titles (SDK sets `title`), h1 with tabindex, role="main",
  aria-label + aria-live on the widget grid, lang attribute set.
- Vendor duty: maintain contrast when overriding theme colors (WCAG AA
  4.5:1); the defaults pass. Validate with axe/Lighthouse on the embed URL.

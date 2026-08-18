# Threat Model (STRIDE summary)

Assets: tenant business data, credentials/keys/tokens, audit trail, AI quota.
Trust boundaries: browser->nginx->API; API->Postgres (RLS); scheduler->
external webhooks; embed tokens in third-party pages; SCIM/SSO from IdPs.

| Threat | Vector | Mitigation (tested) |
|---|---|---|
| Spoofing | forged embed/SCIM/SSO tokens | HMAC signatures, pinned certs, hashed bearer tokens (401 tests) |
| Tampering | filter widening in embeds; SQL injection | filters inside signature; formulas AST-parsed, parameterized (injection tests) |
| Repudiation | disputed actions | append-only audit + exports + SIEM stream |
| Info disclosure | cross-tenant/cross-customer reads | Postgres RLS + scoped sessions + attack-shaped tests (rival key, forged filter, parent->child) |
| DoS | unbounded queries/AI | row/complexity limits, quotas, rate limits, embed view caps |
| Elevation | role bypass | require() scopes per endpoint; owner-only paths; approval gates for actions |

Residuals: XMLDSig chain (documented), CSP for embed pages served by nginx
(frame-ancestors intentionally open for vendor iframes), no WAF in compose.

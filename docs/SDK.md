# InsightForge SDKs (MVP4 E2)

Three integration levels, one security model: your backend mints a signed
embed token per end-customer (`POST /api/v1/embed/tokens` — session or API-key
auth, filters mandatory); the token authorizes everything below. Viewers can
never remove or widen the customer filters — they travel inside the signature.

## 1. Script tag (any stack)
```html
<script src="https://YOUR-INSIGHTFORGE/sdk/insightforge.js"></script>
<script>
  InsightForge.embed({ container: "#dash", token: TOKEN,
                       baseUrl: "https://YOUR-INSIGHTFORGE" });
  InsightForge.query({ token: TOKEN, formula: "sum(amount)",
                       groupBy: "region", baseUrl: "..." })
    .then(d => render(d.results));
</script>
```

## 2. React (copy `sdk/insightforge-react.jsx` into your app)
```jsx
<InsightForgeDashboard token={token} baseUrl="https://YOUR-INSIGHTFORGE" />
const { loading, data, error } = useInsightForgeQuery({
  token, formula: "sum(amount)", groupBy: "region", baseUrl: "..." });
```

## 3. Headless HTTP (no SDK)
```
GET /api/v1/embed/{token}/query?formula=sum(amount)&group_by=region
```
Returns per-dataset results, already filtered to the token's customer.
Errors: 401 bad/expired/tampered token · 404 dashboard unpublished ·
422 formula not computable. All access audited (embed.view / embed.query
with customer label).

Token minting (your backend, e.g.):
```bash
curl -X POST .../api/v1/embed/tokens -H "Authorization: Bearer <session>" \
 -d '{"dashboard_id":"...","customer_label":"Acme",
      "filters":[{"column":"customer","op":"eq","value":"c1"}],
      "expires_minutes":60}'
```
Working sample: `/sdk/example.html?token=...` on your InsightForge host.

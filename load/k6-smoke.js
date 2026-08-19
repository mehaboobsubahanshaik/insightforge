// R17: k6 load-test scripts — run: k6 run -e BASE=http://localhost:8000 \
//   -e TOKEN=<access-token> -e DS=<dataset-id> k6-smoke.js
// Stages assert the NFR-TARGETS.md numbers; failures = evidence gap.
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 20 },   // ramp
    { duration: '1m', target: 50 },    // NFR: 50 concurrent light users
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],          // reads p95 < 500ms
    'http_req_duration{kind:ask}': ['p(95)<2000'],  // queries p95 < 2s
    http_req_failed: ['rate<0.01'],
  },
};

const BASE = __ENV.BASE || 'http://localhost:8000';
const H = { headers: { Authorization: `Bearer ${__ENV.TOKEN}` } };

export default function () {
  check(http.get(`${BASE}/api/v1/workspaces`, H),
        { 'workspaces 200': r => r.status === 200 });
  check(http.get(`${BASE}/api/v1/dashboards`, H),
        { 'dashboards 200': r => r.status === 200 });
  if (__ENV.DS) {
    const ask = http.post(`${BASE}/api/v1/datasets/${__ENV.DS}/ask`,
      JSON.stringify({ question: 'total amount' }),
      { headers: { ...H.headers, 'Content-Type': 'application/json' },
        tags: { kind: 'ask' } });
    check(ask, { 'ask 200': r => r.status === 200 });
  }
  sleep(1);
}

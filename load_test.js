import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '10s', target: parseInt(__ENV.VU_TARGET || '10') },
    { duration: '20s', target: parseInt(__ENV.VU_TARGET || '10') },
  ],
  thresholds: {
    'http_req_duration': ['p(95)<200'], // SLO: p95 <= 200ms
    'http_req_failed': ['rate<0.01'],    // SLO: Error Rate < 1%
  },
};

export default function () {
  const res = http.get('http://localhost:5000/api/v1/specifications');
  check(res, {
    'status is 200': (r) => r.status === 200,
  });
  sleep(0.1);
}
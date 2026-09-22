import assert from 'node:assert/strict';
import { publicCapabilityStatus } from '../lib/bars-capabilities.js';
const byId = Object.fromEntries(publicCapabilityStatus({
  BARS_JEV_RUNNER_URL: 'http://jev-runner:8643', GROQ_API_TOKEN: 'x', RIME_API_KEY: 'x'
}).map(x => [x.id, x]));
assert.equal(byId['jev-hands'].status, 'contract-only');
assert.equal(byId['screen-vision'].status, 'available');
assert.equal(byId['speech-hearing'].status, 'configured');
assert.equal(byId['rime-mouth'].status, 'configured');
assert.equal(publicCapabilityStatus({}).find(x=>x.id==='speech-hearing').status,'available');
console.log('PASS: BARS capability status is pinned and Jev is not claimed live before runtime wiring');

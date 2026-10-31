// Tests für governance-client.mjs (node:test, ohne DOM und ohne Netz).

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  EXPECTED_DIST_COMMIT,
  EXPECTED_DIST_VERSION,
  EXPECTED_REGISTRY_COMMIT_PREFIX,
  EXPECTED_REGISTRY_VERSION,
  getCapabilities,
  getEffectivePolicy,
  getPolicyRegistry,
  requestJson
} from './governance-client.mjs';

const response = (data, status = 200) => ({
  ok: status < 400,
  status,
  json: async () => data
});

const unreadableResponse = (status = 200) => ({
  ok: status < 400,
  status,
  json: async () => {
    throw new SyntaxError('Unexpected token < in JSON');
  }
});

test('getPolicyRegistry kodiert Query-Parameter und übergibt die Antwort', async () => {
  const calls = [];
  const saved = { scope: 'release', entries: [{ kind: 'policy' }] };
  const fetcher = async (url, options = {}) => {
    calls.push({ url, options });
    return response(saved);
  };
  const data = await getPolicyRegistry(
    { scope: 'release: team & tools', consumer: 'gui', query: 'sign', kind: 'policy' },
    fetcher
  );
  assert.equal(calls.length, 1);
  assert.equal(
    calls[0].url,
    '/api/governance/policy-registry?scope=release%3A%20team%20%26%20tools&consumer=gui&query=sign&kind=policy'
  );
  assert.equal(data, saved);
  const plain = await getPolicyRegistry({}, fetcher);
  assert.equal(calls.length, 2);
  assert.equal(calls[1].url, '/api/governance/policy-registry');
  assert.deepEqual(plain, saved);
});

test('getPolicyRegistry prüft Länge und Art vor der Anfrage', async () => {
  const calls = [];
  const fetcher = async (url, options = {}) => {
    calls.push({ url, options });
    return response({});
  };
  await assert.rejects(
    getPolicyRegistry({ kind: 'sonstwas' }, fetcher),
    /Die Art muss policy, rule, decision, evidence oder decision-candidate sein/
  );
  await assert.rejects(getPolicyRegistry({ scope: 'x'.repeat(257) }, fetcher), /zu lang/);
  await assert.rejects(getPolicyRegistry({ consumer: 'x'.repeat(257) }, fetcher), /zu lang/);
  await assert.rejects(getPolicyRegistry({ query: 'x'.repeat(513) }, fetcher), /zu lang/);
  assert.equal(calls.length, 0);
});

test('getEffectivePolicy verlangt einen Geltungsbereich', async () => {
  const calls = [];
  const fetcher = async (url, options = {}) => {
    calls.push({ url, options });
    return response({});
  };
  await assert.rejects(getEffectivePolicy({}, fetcher), /Für die wirksame Richtlinie ist ein Geltungsbereich erforderlich/);
  await assert.rejects(getEffectivePolicy({ scope: '' }, fetcher), /Geltungsbereich erforderlich/);
  assert.equal(calls.length, 0);
});

test('getEffectivePolicy fragt die wirksame Richtlinie ab', async () => {
  const calls = [];
  const saved = { scope: 'release', policy: { rule: 'sign' } };
  const fetcher = async (url, options = {}) => {
    calls.push({ url, options });
    return response(saved);
  };
  const data = await getEffectivePolicy({ scope: 'release', consumer: 'gui' }, fetcher);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/governance/effective-policy?scope=release&consumer=gui');
  assert.equal(data, saved);
});

test('getCapabilities wertet Kit-Status und Registry offen aus', async () => {
  const payload = {
    kit_status: {
      revision: EXPECTED_DIST_COMMIT,
      version: EXPECTED_DIST_VERSION,
      archive_sha256: '0123456789abcdef',
      verified: true,
      installed: true,
      installed_files_verified: true,
      served: true,
      reason_code: null,
      dist_page_count: 12
    },
    modules: {
      'policy-registry': {
        adapter_registered: true,
        runtime_verified: false,
        available: null,
        reason_code: null,
        observed_at: '2026-01-02T03:04:05Z'
      }
    },
    module_sources: [
      { version: EXPECTED_REGISTRY_VERSION, source_commit: '2c4896b70cb3abcdef0123456789abcdef01234' }
    ]
  };
  const fetcher = async (url, options = {}) => {
    assert.equal(url, '/api/gui/capabilities');
    return response(payload);
  };
  const result = await getCapabilities(fetcher);
  assert.equal(result.data, payload);
  assert.equal(result.kit_status.version, '0.2.29');
  assert.equal(result.policyRegistry.adapter_registered, true);
  assert.equal(result.registrySource.version, '0.2.4');
  assert.ok(result.registrySource.source_commit.startsWith(EXPECTED_REGISTRY_COMMIT_PREFIX));
  assert.equal(result.matches.dist_commit_ok, true);
  assert.equal(result.matches.dist_version_ok, true);
  assert.equal(result.matches.registry_registered, true);
  assert.equal(result.matches.registry_available, false);
  assert.equal(result.summary.available_state, null);
  assert.equal(result.summary.runtime_verified, false);
  assert.equal(result.matches.registry_version_ok, true);
  assert.equal(result.matches.registry_commit_ok, true);
  assert.equal(result.summary.ok, true);
  assert.equal(result.summary.passed, 5);
  assert.equal(result.summary.total, 6);
});

test('getCapabilities meldet Abweichungen statt zu raten', async () => {
  const payload = {
    kit_status: { revision: 'deadbeefdeadbeef', version: '9.9.9' },
    modules: { 'policy-registry': { adapter_registered: false, available: false } },
    module_sources: [{ version: '0.1.0', source_commit: '111111111111' }]
  };
  const fetcher = async () => response(payload);
  const result = await getCapabilities(fetcher);
  assert.equal(result.matches.dist_commit_ok, false);
  assert.equal(result.matches.dist_version_ok, false);
  assert.equal(result.matches.registry_registered, false);
  assert.equal(result.matches.registry_available, false);
  assert.equal(result.matches.registry_version_ok, false);
  assert.equal(result.matches.registry_commit_ok, false);
  assert.equal(result.summary.ok, false);
  assert.equal(result.summary.passed, 0);
});

test('getCapabilities bleibt bei unvollständiger Antwort stabil', async () => {
  const fetcher = async () => response(null);
  const result = await getCapabilities(fetcher);
  assert.equal(result.data, null);
  assert.equal(result.kit_status, null);
  assert.equal(result.policyRegistry, null);
  assert.equal(result.registrySource, null);
  assert.equal(result.summary.ok, false);
  assert.equal(result.summary.total, 6);
});

test('requestJson meldet 409 als Änderungskonflikt', async () => {
  const fetcher = async () => response({}, 409);
  await assert.rejects(requestJson('/api/governance/policy-registry', {}, fetcher), /inzwischen geändert/);
});

test('requestJson hängt bei 503 den öffentlichen Grund an', async () => {
  const withDetail = async () => response({ detail: 'Policy Provider antwortet nicht' }, 503);
  await assert.rejects(requestJson('/api/governance/policy-registry', {}, withDetail), /nicht erreichbar\./);
  await assert.rejects(requestJson('/api/governance/policy-registry', {}, withDetail), /Policy Provider antwortet nicht/);
  const withReason = async () => response({ public_unavailable_reason: 'Zeitüberschreitung beim Anbieter' }, 503);
  await assert.rejects(requestJson('/api/governance/policy-registry', {}, withReason), /Zeitüberschreitung beim Anbieter/);
});

test('requestJson meldet unlesbare Antworten', async () => {
  const fetcher = async () => unreadableResponse(200);
  await assert.rejects(requestJson('/api/gui/capabilities', {}, fetcher), /lesbare Antwort/);
});

test('requestJson nutzt detail und setzt error.status', async () => {
  const fetcher = async () => response({ detail: 'Eintrag nicht gefunden' }, 404);
  await assert.rejects(
    requestJson('/api/governance/policy-registry', {}, fetcher),
    (error) => {
      assert.equal(error.message, 'Eintrag nicht gefunden');
      assert.equal(error.status, 404);
      return true;
    }
  );
});

test('requestJson fällt auf den Standardtext zurück', async () => {
  await assert.rejects(
    requestJson('/api/governance/effective-policy', {}, async () => response({}, 400)),
    /nicht bestätigt/
  );
  await assert.rejects(
    requestJson('/api/governance/effective-policy', {}, async () => response({ detail: 42 }, 400)),
    /nicht bestätigt/
  );
});
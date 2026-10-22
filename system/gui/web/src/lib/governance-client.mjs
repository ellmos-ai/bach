export const POLICY_KINDS = /^(policy|rule|decision|evidence|decision-candidate)$/;
export const GOVERNANCE_PATHS = {
  policyRegistry: '/api/governance/policy-registry',
  effectivePolicy: '/api/governance/effective-policy',
};

function governanceError(name, message, status) {
  const error = new Error(message);
  error.name = name;
  if (status !== undefined && status !== null) error.status = status;
  return error;
}

function providerMessage(data) {
  const reason = typeof data?.detail === 'string' && data.detail.trim()
    ? data.detail.trim() : 'Der Richtlinien-Anbieter ist zurzeit nicht erreichbar.';
  return 'PolicyProviderUnavailable: ' + reason + ' – Es werden keine Ersatzdaten (Fallback) verwendet.';
}

function snapshotMessage(data) {
  const reason = typeof data?.detail === 'string' && data.detail.trim() ? data.detail.trim() + ' – ' : '';
  return 'PolicySnapshotChanged: ' + reason
    + 'Die Richtlinien-Sicht hat sich inzwischen geändert. Lade die aktuelle Fassung neu (Neuladen), bevor du erneut liest.';
}

export function validatePolicyKind(kind) {
  if (kind === undefined || kind === null || kind === '') return undefined;
  if (typeof kind !== 'string' || !POLICY_KINDS.test(kind))
    throw governanceError('PolicyKindInvalid',
      'Unbekannter Eintragstyp (kind): nur policy, rule, decision, evidence oder decision-candidate.');
  return kind;
}

export function buildGovernanceQuery(params) {
  const pairs = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    pairs.push(encodeURIComponent(key) + '=' + encodeURIComponent(value));
  }
  return pairs.length ? '?' + pairs.join('&') : '';
}

function validateRegistryView(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data) || !Array.isArray(data.entries))
    throw governanceError('PolicyRegistryUnreadable',
      'Die Richtlinien-Sicht konnte nicht bestätigt werden: die erwarteten Einträge fehlen.');
  if (data.count !== undefined && typeof data.count !== 'number')
    throw governanceError('PolicyRegistryUnreadable', 'Die Anzahl der Richtlinien-Einträge ist unlesbar.');
  if (data.provider !== undefined && typeof data.provider !== 'string')
    throw governanceError('PolicyRegistryUnreadable', 'Der Richtlinien-Anbieter ist in der Antwort unlesbar.');
  if (data.registry_version !== undefined && typeof data.registry_version !== 'string')
    throw governanceError('PolicyRegistryUnreadable', 'Die Version der Richtlinien-Sicht ist unlesbar.');
  return data;
}

async function readGovernanceView(url, fetcher) {
  const response = await fetcher(url);
  let data;
  try { data = await response.json(); }
  catch { throw governanceError('PolicyResponseUnreadable', 'Die Richtlinien-Quelle liefert keine lesbare Antwort.', response.status); }
  if (!response.ok) {
    if (response.status === 503) throw governanceError('PolicyProviderUnavailable', providerMessage(data), 503);
    if (response.status === 409) throw governanceError('PolicySnapshotChanged', snapshotMessage(data), 409);
    throw governanceError('GovernanceRequestFailed',
      typeof data?.detail === 'string' && data.detail.trim()
        ? data.detail : 'Die Richtlinien-Anfrage konnte nicht bestätigt werden.',
      response.status);
  }
  return validateRegistryView(data);
}

export async function getPolicyRegistry(options = {}, fetcher = globalThis.fetch) {
  const kind = validatePolicyKind(options.kind);
  const url = GOVERNANCE_PATHS.policyRegistry + buildGovernanceQuery({
    scope: options.scope, consumer: options.consumer, query: options.query, kind});
  return readGovernanceView(url, fetcher);
}

export async function getEffectivePolicy(scope, options = {}, fetcher = globalThis.fetch) {
  if (typeof scope !== 'string' || !scope.trim())
    throw governanceError('PolicyScopeRequired',
      'Für die wirksame Richtlinie ist ein Geltungsbereich (scope) erforderlich.');
  const url = GOVERNANCE_PATHS.effectivePolicy + buildGovernanceQuery({
    scope, consumer: options.consumer, query: options.query});
  return readGovernanceView(url, fetcher);
}

export function describePolicyRegistryModule(module) {
  if (!module || typeof module !== 'object')
    return {adapter_registered: false, runtime_verified: false, available: null,
      reason_code: 'policy_registry_status_unreadable', observed_at: null, ok: false,
      text: 'Der Status der Richtlinien-Quelle (policy-registry) konnte nicht gelesen werden.'};
  const reasonCode = typeof module.reason_code === 'string' && module.reason_code.trim()
    ? module.reason_code : 'reason_unknown';
  const state = module.available === true ? 'verfügbar'
    : module.available === false ? 'nicht verfügbar' : 'Zustand ungeprüft';
  return {...module, reason_code: reasonCode, ok: module.available === true,
    text: 'Policy-Registry: ' + state + ' (Grund: ' + reasonCode + ').'};
}
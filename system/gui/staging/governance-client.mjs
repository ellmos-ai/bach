// Governance-API-Client für ellmos-system-gui (Staging im BACH-Worktree).
//
// Zweck: Zugriff der GUI auf die Governance-Endpunkte des BACH-Hubs:
//   - GET /api/governance/policy-registry   (getPolicyRegistry)
//   - GET /api/governance/effective-policy   (getEffectivePolicy)
//   - GET /api/gui/capabilities              (getCapabilities)
//
// Grundsätze:
//   - Defensive Auswertung: Antworten werden nicht whitelistet; unbekannte oder
//     fehlende Struktur ergibt null/false statt Absturz.
//   - Der Fetcher ist injectierbar (Standard globalThis.fetch), damit Tests ohne
//     Netz laufen.
//   - typeof-Checks für window/localStorage, damit node --test ohne DOM läuft.

export const EXPECTED_DIST_COMMIT = 'ff13cccde77a997ab4d0a0173db43ff88ee3c2be';
export const EXPECTED_DIST_VERSION = '0.2.24';
export const EXPECTED_REGISTRY_VERSION = '0.2.4';
export const EXPECTED_REGISTRY_COMMIT_PREFIX = '2c4896b70cb3';

const KIND_PATTERN = /^(policy|rule|decision|evidence|decision-candidate)$/;

function _objectOrNull(value) {
  if (value == null || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value;
}

export function baseUrl() {
  if (typeof window !== 'undefined' && window.BOARD_CONFIG && window.BOARD_CONFIG.apiBase != null) {
    return window.BOARD_CONFIG.apiBase;
  }
  return '';
}

export function deviceHeaders() {
  if (typeof localStorage === 'undefined') {
    return {};
  }
  const token = localStorage.getItem('bach_device_token');
  if (!token) {
    return {};
  }
  return { Authorization: 'Bearer ' + token };
}

function _headers() {
  if (typeof window !== 'undefined' && window.BOARD_CONFIG) {
    if (window.BOARD_CONFIG.token) {
      return { Authorization: 'Bearer ' + window.BOARD_CONFIG.token };
    }
    const storageKey = window.BOARD_CONFIG.tokenStorageKey;
    if (storageKey && typeof localStorage !== 'undefined') {
      const token = localStorage.getItem(storageKey);
      if (token) {
        return { Authorization: 'Bearer ' + token };
      }
    }
  }
  return deviceHeaders();
}

export async function requestJson(url, options = {}, fetcher = globalThis.fetch) {
  const response = await fetcher(baseUrl() + url, options);
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error('Die Quelle liefert keine lesbare Antwort.');
  }
  if (!response.ok) {
    const status = response.status;
    const body = _objectOrNull(data);
    let message = null;
    if (status === 409) {
      message = 'Die Quelle wurde inzwischen geändert. Lade die aktuelle Fassung vor dem Speichern.';
    } else if (status === 503) {
      message = 'Richtlinien-Anbieter ist gerade nicht erreichbar.';
      let extra = null;
      if (body && typeof body.detail === 'string') {
        extra = body.detail;
      } else if (body && typeof body.public_unavailable_reason === 'string') {
        extra = body.public_unavailable_reason;
      }
      if (extra) {
        message = message + ' ' + extra;
      }
    } else if (body && typeof body.detail === 'string') {
      message = body.detail;
    }
    if (message === null) {
      message = 'Die Anfrage konnte nicht bestätigt werden.';
    }
    const failure = new Error(message);
    failure.status = status;
    throw failure;
  }
  return data;
}

function _assertLength(value, limit) {
  if (value != null && String(value).length > limit) {
    throw new Error('Der Abfrageparameter ist zu lang.');
  }
}

function _query(path, params) {
  const parts = [];
  for (const key of Object.keys(params)) {
    const value = params[key];
    if (value == null || value === '') {
      continue;
    }
    parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(String(value)));
  }
  if (parts.length === 0) {
    return path;
  }
  return path + '?' + parts.join('&');
}

export async function getPolicyRegistry({ scope, consumer, query, kind } = {}, fetcher = globalThis.fetch) {
  _assertLength(scope, 256);
  _assertLength(consumer, 256);
  _assertLength(query, 512);
  if (kind != null && kind !== '' && !KIND_PATTERN.test(String(kind))) {
    throw new Error('Die Art muss policy, rule, decision, evidence oder decision-candidate sein.');
  }
  const url = _query('/api/governance/policy-registry', { scope, consumer, query, kind });
  return requestJson(url, { headers: _headers() }, fetcher);
}

export async function getEffectivePolicy({ scope, consumer, query } = {}, fetcher = globalThis.fetch) {
  if (scope == null || String(scope) === '') {
    throw new Error('Für die wirksame Richtlinie ist ein Geltungsbereich erforderlich.');
  }
  _assertLength(scope, 256);
  _assertLength(consumer, 256);
  _assertLength(query, 512);
  const url = _query('/api/governance/effective-policy', { scope, consumer, query });
  return requestJson(url, { headers: _headers() }, fetcher);
}

function _registrySource(moduleSources) {
  if (!Array.isArray(moduleSources)) {
    return null;
  }
  for (const entry of moduleSources) {
    const source = _objectOrNull(entry);
    if (!source) {
      continue;
    }
    if (typeof source.source_commit === 'string' && source.source_commit.startsWith(EXPECTED_REGISTRY_COMMIT_PREFIX)) {
      return source;
    }
    if (source.version === EXPECTED_REGISTRY_VERSION) {
      return source;
    }
  }
  return null;
}

export async function getCapabilities(fetcher = globalThis.fetch) {
  const data = await requestJson('/api/gui/capabilities', { headers: _headers() }, fetcher);
  const body = _objectOrNull(data);
  const kitStatus = body ? _objectOrNull(body.kit_status) : null;
  const modules = body ? _objectOrNull(body.modules) : null;
  const policyRegistry = modules ? _objectOrNull(modules['policy-registry']) : null;
  const registrySource = body ? _registrySource(body.module_sources) : null;
  const matches = {
    dist_commit_ok: kitStatus != null && kitStatus.revision === EXPECTED_DIST_COMMIT,
    dist_version_ok: kitStatus != null && kitStatus.version === EXPECTED_DIST_VERSION,
    registry_registered: policyRegistry != null && policyRegistry.adapter_registered === true,
    registry_available: policyRegistry != null && policyRegistry.available === true,
    registry_version_ok: registrySource != null && registrySource.version === EXPECTED_REGISTRY_VERSION,
    registry_commit_ok: registrySource != null && typeof registrySource.source_commit === 'string' && registrySource.source_commit.startsWith(EXPECTED_REGISTRY_COMMIT_PREFIX)
  };
  const keys = Object.keys(matches);
  const summary = {
    ok: keys.every((key) => matches[key] === true),
    passed: keys.filter((key) => matches[key] === true).length,
    total: keys.length
  };
  return { data, kit_status: kitStatus, policyRegistry, registrySource, matches, summary };
}
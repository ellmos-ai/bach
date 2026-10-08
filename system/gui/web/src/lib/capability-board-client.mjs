export const SKILL_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;
const REVISION = /^[a-f0-9]{64}$/;
export const INVENTORIES = {
  skills: '/api/capabilities/skills/library',
  plugins: '/api/capabilities/plugins/inventory',
  mcp: '/api/capabilities/mcp/connections',
  software: '/api/capabilities/software',
};

export async function requestJson(url, options = {}, fetcher = globalThis.fetch) {
  const response = await fetcher(url, options);
  let data;
  try { data = await response.json(); }
  catch { throw new Error('Die Quelle liefert keine lesbare Antwort.'); }
  if (!response.ok) {
    const error = new Error(response.status === 409
      ? 'Die Quelle wurde inzwischen geändert. Lade die aktuelle Fassung vor dem Speichern.'
      : typeof data.detail === 'string' ? data.detail : 'Die Anfrage konnte nicht bestätigt werden.');
    error.status = response.status;
    throw error;
  }
  return data;
}

export async function loadSkill(id, fetcher = globalThis.fetch) {
  if (!SKILL_ID.test(id)) throw new Error('Ungültige Skill-Kennung.');
  const source = await requestJson('/api/capabilities/skills/' + encodeURIComponent(id) + '/source', {}, fetcher);
  if (source.id !== id || typeof source.content !== 'string' || !REVISION.test(source.source_version))
    throw new Error('Die aktuelle Skill-Fassung konnte nicht bestätigt werden.');
  return source;
}

export async function saveSkill(source, content, fetcher = globalThis.fetch) {
  if (!source || !SKILL_ID.test(source.id)
      || !(source.source_version === '0' || REVISION.test(source.source_version))
      || typeof content !== 'string' || !content.trim())
    throw new Error('Skill-Kennung, Inhalt und geladene Quellenversion sind erforderlich.');
  const saved = await requestJson('/api/capabilities/skills/' + encodeURIComponent(source.id) + '/source', {
    method: 'PUT', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({content, source_version: source.source_version}),
  }, fetcher);
  if (saved.id !== source.id || saved.content !== content || saved.receipt?.source_saved !== true)
    throw new Error('Der Speicherbeleg stimmt nicht mit der Änderung überein.');
  const observed = await loadSkill(source.id, fetcher);
  if (observed.source_version !== saved.source_version || observed.content !== content)
    throw new Error('Die Quelle wurde nach dem Speichern erneut geändert. Prüfe die aktuelle Fassung.');
  return observed;
}

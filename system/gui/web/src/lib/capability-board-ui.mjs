import {INVENTORIES, SKILL_ID, loadSkill, saveSkill, requestJson, confirmSkillReplacement} from './capability-board-client.mjs';

const board = document.getElementById('capability-board');
if (board) {
  const kind = board.dataset.board;
  const byId = id => document.getElementById(id);
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  };
  const button = (title, action, className = 'btn') => {
    const element = node('button', title, className);
    element.type = 'button'; element.addEventListener('click', action);
    return element;
  };
  const badge = text => node('span', text, 'badge');
  const flag = value => value === true ? 'Aktivierung eingestellt' : value === false ? 'Deaktivierung eingestellt' : 'Aktivierung nicht erfasst';
  let items = [], inventoryGeneration = 0;

  function renderItems() {
    const query = byId('board-search').value.trim().toLocaleLowerCase('de');
    const category = byId('board-category')?.value || '';
    const visible = items.filter(item => (!category || item.category === category)
      && [item.name, item.id, item.description, item.consumer].some(value => typeof value === 'string' && value.toLocaleLowerCase('de').includes(query)));
    byId('board-items').replaceChildren();
    byId('board-count').textContent = visible.length + ' / ' + items.length + ' Einträge';
    for (const item of visible) {
      const card = node('article', null, 'capability-card');
      card.dataset.id = item.id;
      card.append(node('h3', item.name || item.id), node('p', item.description || 'Keine Beschreibung in der Quelle.'));
      const meta = node('div', null, 'card-meta');
      if (kind !== 'mcp') meta.append(badge(item.version || 'Ohne Versionsnummer'));
      if (kind === 'skills') {
        meta.append(badge(item.category || 'Allgemein'));
        card.append(meta, node('p', item.id, 'card-caption'), button('Anleitung bearbeiten', () => openSkill(item.id), 'btn card-action'));
      } else {
        if (item.consumer) meta.append(badge(item.consumer));
        card.append(meta);
        if (kind === 'plugins') {
          card.append(node('p', item.code_present ? 'Plugin-Dateien vorhanden' : 'Installationsverweis ohne erreichbare Dateien'));
          card.append(node('p', flag(item.enabled_in_client), 'card-caption'));
        } else if (kind === 'mcp') {
          card.append(node('p', 'Im Client konfiguriert · ' + item.transport));
          if (item.command_name || item.hostname) card.append(node('p', item.command_name || item.hostname, 'card-caption'));
          card.append(node('p', flag(item.enabled_in_client), 'card-caption'));
        } else card.append(node('p', 'Programmquellen vorhanden'));
        const detail = node('details'), summary = node('summary', 'Quelle');
        detail.append(summary, node('p', item.path || item.source || 'Quelle nicht angegeben'));
        card.append(detail);
      }
      byId('board-items').append(card);
    }
    if (!visible.length) byId('board-items').append(node('p', query || category ? 'Keine passenden Einträge.' : 'In den erreichbaren Quellen sind keine Einträge vorhanden.'));
  }

  async function refresh() {
    const generation = ++inventoryGeneration;
    byId('board-status').textContent = 'Host-Quellen werden gelesen …';
    byId('board-refresh').disabled = true;
    try {
      const data = await requestJson(INVENTORIES[kind]);
      if (generation !== inventoryGeneration) return;
      const rows = kind === 'skills' ? data.skills : data.items;
      if (!Array.isArray(rows)) throw new Error('Die Quelle liefert keinen Eintragskatalog.');
      items = rows;
      if (kind === 'skills') {
        const select = byId('board-category'), previous = select.value;
        select.replaceChildren(new Option('Alle Kategorien', ''));
        for (const category of [...new Set(items.map(item => item.category).filter(Boolean))].sort()) select.add(new Option(category, category));
        if ([...select.options].some(option => option.value === previous)) select.value = previous;
      }
      const notes = [];
      if (kind === 'plugins') notes.push('Die Einstellungen stammen aus den Client-Dateien. Der Laufzeitstatus der Clients ist nicht erfasst.');
      if (kind === 'mcp') notes.push('Die Verbindungen werden von den jeweiligen Clients verwaltet. Eine laufende MCP-Sitzung ist hier nicht nachgewiesen.');
      if (kind === 'software') notes.push('Die Liste zeigt Programmquellen auf diesem Host. Eine Installation oder ein laufender Dienst ist damit nicht nachgewiesen.');
      if (data.truncated) notes.push('Die Lesegrenze wurde erreicht; die Liste ist unvollständig.');
      if (data.errors?.length) notes.push(data.errors.length + ' Quelle(n) konnten nicht gelesen werden.');
      if (data.sources?.length && data.sources.every(source => !source.available)) notes.push('Keine konfigurierte Quelle ist erreichbar.');
      byId('board-status').textContent = notes.join(' ') || 'Aktuelle SKILL.md-Dateien geladen.';
      const sources = byId('board-sources');
      if (sources) {
        sources.replaceChildren();
        for (const source of data.sources || []) sources.append(node('p', (source.available ? 'Erreichbar: ' : 'Nicht erreichbar: ') + source.path));
        for (const error of data.errors || []) sources.append(node('p', 'Nicht lesbar: ' + error.source + ' (' + error.reason + ')'));
      }
      renderItems();
    } catch (error) {
      if (generation !== inventoryGeneration) return;
      items = []; renderItems();
      byId('board-status').textContent = 'Quelle nicht geladen: ' + error.message;
    } finally { if (generation === inventoryGeneration) byId('board-refresh').disabled = false; }
  }

  const editor = byId('skill-editor');
  let currentSource = null, editorBusy = false, editorGeneration = 0, originalContent = '', selectedHistory = '';
  function busy(value) {
    editorBusy = value;
    for (const id of ['skill-content', 'skill-id', 'skill-history', 'skill-reload', 'skill-close']) byId(id).disabled = value;
    byId('skill-id').readOnly = currentSource?.source_version !== '0';
    byId('skill-history').disabled = value || !currentSource || currentSource.source_version === '0';
    byId('skill-reload').disabled = value || !currentSource || currentSource.source_version === '0';
    byId('skill-save').disabled = value || !currentSource;
  }
  function describeSource() {
    byId('skill-source-info').textContent = currentSource?.source_version === '0' ? 'Neue lokale Anleitung. Eine bestehende Kennung wird nicht überschrieben.'
      : currentSource ? (currentSource.version || 'Ohne Versionsnummer') + ' · Quelle ' + currentSource.source_version.slice(0, 12) : 'Aktuelle Quelle wird geladen …';
  }
  async function loadHistory() {
    const select = byId('skill-history');
    selectedHistory = '';
    select.replaceChildren(new Option('Aktuelle Fassung', ''));
    if (!currentSource || currentSource.source_version === '0') return;
    const history = await requestJson('/api/capabilities/skills/' + encodeURIComponent(currentSource.id) + '/history');
    if (!Array.isArray(history.versions)) throw new Error('Die Historie liefert keine Fassungen.');
    for (const entry of history.versions) select.add(new Option((entry.version || 'Ohne Versionsnummer') + ' · ' + entry.source_version.slice(0, 12), entry.source_version));
    if (history.truncated) byId('skill-editor-status').textContent = 'Die Historie ist wegen der Lesegrenze unvollständig.';
  }
  async function openSkill(id) {
    const generation = ++editorGeneration;
    currentSource = null; originalContent = '';
    byId('skill-editor-title').textContent = 'Skill bearbeiten'; byId('skill-id').value = id;
    byId('skill-content').value = ''; byId('skill-history').replaceChildren(new Option('Aktuelle Fassung', ''));
    byId('skill-editor-status').textContent = ''; describeSource(); busy(true); editor.showModal();
    try {
      const source = await loadSkill(id);
      if (generation !== editorGeneration) return;
      currentSource = source; originalContent = source.content; byId('skill-content').value = source.content; describeSource();
      try { await loadHistory(); }
      catch (error) { byId('skill-editor-status').textContent = 'Aktuelle Fassung geladen. Historie nicht lesbar: ' + error.message; }
    } catch (error) { byId('skill-editor-status').textContent = 'Bearbeitung nicht freigegeben: ' + error.message; }
    finally { if (generation === editorGeneration) busy(false); }
  }
  function closeEditor() {
    if (editorBusy) return;
    if (byId('skill-content').value !== originalContent && !window.confirm('Ungespeicherte Änderungen verwerfen?')) return;
    ++editorGeneration; editor.close();
  }
  byId('skill-close').addEventListener('click', closeEditor);
  editor.addEventListener('cancel', event => { event.preventDefault(); closeEditor(); });
  byId('skill-create')?.addEventListener('click', () => {
    ++editorGeneration; currentSource = {id:'',source_version:'0'};
    selectedHistory = '';
    originalContent = '---\nname: neuer-skill\ndescription: Aufgabe und Einsatz der Anleitung\nversion: 1.0.0\n---\n\n# Neuer Skill\n\n## Vorgehen\n\n1. Beschreibe die Arbeitsschritte.\n';
    byId('skill-editor-title').textContent = 'Neuer Skill'; byId('skill-id').value = '';
    byId('skill-content').value = originalContent; byId('skill-editor-status').textContent = '';
    byId('skill-history').replaceChildren(new Option('Aktuelle Fassung', ''));
    describeSource(); busy(false); editor.showModal(); byId('skill-id').focus();
  });
  byId('skill-reload').addEventListener('click', async () => {
    if (!currentSource || editorBusy) return;
    if (byId('skill-content').value !== originalContent && !window.confirm('Aktuelle Fassung laden und ungespeicherte Änderungen verwerfen?')) return;
    busy(true);
    try {
      currentSource = await loadSkill(currentSource.id); originalContent = currentSource.content;
      byId('skill-content').value = originalContent; describeSource(); await loadHistory();
      byId('skill-editor-status').textContent = 'Aktuelle Fassung geladen.';
    } catch (error) { byId('skill-editor-status').textContent = error.message; }
    finally { busy(false); }
  });
  byId('skill-history').addEventListener('change', async () => {
    if (!currentSource || editorBusy) return;
    const revision = byId('skill-history').value;
    if (!confirmSkillReplacement(byId('skill-content').value, originalContent, message => window.confirm(message))) {
      byId('skill-history').value = selectedHistory;
      return;
    }
    busy(true);
    try {
      const source = revision ? await requestJson('/api/capabilities/skills/' + encodeURIComponent(currentSource.id) + '/history/' + encodeURIComponent(revision)) : currentSource;
      if (typeof source.content !== 'string' || (revision && source.source_version !== revision)) throw new Error('Historische Quelle konnte nicht bestätigt werden.');
      byId('skill-content').value = source.content;
      selectedHistory = revision;
      byId('skill-editor-status').textContent = revision ? 'Frühere Fassung als Vorlage geladen. Speichern erzeugt die neue aktuelle Fassung.' : 'Geladene aktuelle Fassung wieder eingesetzt.';
    } catch (error) { byId('skill-history').value = selectedHistory; byId('skill-editor-status').textContent = error.message; }
    finally { busy(false); }
  });
  byId('skill-save').addEventListener('click', async () => {
    if (!currentSource || editorBusy) return;
    const id = byId('skill-id').value.trim();
    if (!SKILL_ID.test(id)) { byId('skill-editor-status').textContent = 'Eine gültige Kennung ist erforderlich.'; return; }
    busy(true); byId('skill-editor-status').textContent = 'Quelle wird gespeichert und erneut gelesen …';
    try {
      currentSource = await saveSkill({...currentSource,id}, byId('skill-content').value);
      originalContent = currentSource.content; describeSource();
      byId('skill-editor-title').textContent = 'Skill bearbeiten';
      byId('skill-editor-status').textContent = 'Gespeicherte aktuelle Fassung bestätigt.';
      try { await loadHistory(); } catch (error) { byId('skill-editor-status').textContent += ' Historie nicht geladen: ' + error.message; }
      await refresh();
    } catch (error) { byId('skill-editor-status').textContent = error.message; }
    finally { busy(false); }
  });

  const recipeDialog = byId('recipe-editor');
  byId('recipe-close').addEventListener('click', () => recipeDialog.close());
  function showRecipe(book) {
    byId('recipe-title').textContent = book.title || book.id;
    byId('recipe-description').textContent = 'Anleitungsvorlage · ' + (book.description || '') + ' Der Laufzeitstatus ist nicht geprüft.';
    const content = byId('recipe-content'); content.replaceChildren();
    const tools = book.pages?.page_2_tools?.tools || [];
    const toolSection = node('section'); toolSection.append(node('h3', 'Werkzeuge'));
    for (const tool of tools) toolSection.append(node('p', tool.name + (tool.description ? ': ' + tool.description : '')));
    content.append(toolSection, node('h3', 'Rezepte'));
    for (const recipe of book.recipes || book.pages?.page_3_recipes?.recipes || []) {
      const article = node('article'), status = node('p', '', 'copy-status');
      article.append(node('h4', recipe.title), node('pre', recipe.prompt || ''));
      article.append(button('Rezept kopieren', async () => {
        try { await navigator.clipboard.writeText(recipe.prompt || ''); status.textContent = 'Kopiert.'; }
        catch { status.textContent = 'Zwischenablage nicht erreichbar. Text bitte auswählen und kopieren.'; }
      }), status); content.append(article);
    }
    const governance = book.pages?.page_4_governance || {};
    content.append(node('h3', 'Einsatzhinweise'));
    content.append(node('p', governance.mode_note || governance.mode_restrictions || governance.safety_note || 'Die tatsächlichen Werkzeuge und Rechte werden vom jeweiligen Client bestimmt.'));
    recipeDialog.showModal();
  }
  async function loadRecipes() {
    try {
      const data = await requestJson('/api/capabilities/mcp/cookbooks');
      if (!Array.isArray(data.cookbooks)) throw new Error('Keine Rezeptbibliothek in der Antwort.');
      byId('recipe-books').replaceChildren();
      for (const book of data.cookbooks) {
        const entry = button('', () => showRecipe(book), 'recipe-book');
        entry.append(node('small', 'MCP · Anleitungsvorlage'), node('strong', book.title || book.id), node('small', book.description || ''), node('span', 'Rezepte ansehen →'));
        byId('recipe-books').append(entry);
      }
      byId('recipe-status').textContent = data.cookbooks.length + ' Rezeptbücher. Die Anleitungen führen keine Werkzeuge aus.';
    } catch (error) { byId('recipe-status').textContent = 'Rezeptbibliothek nicht geladen: ' + error.message; }
  }
  byId('board-search').addEventListener('input', renderItems);
  byId('board-category')?.addEventListener('change', renderItems);
  byId('board-refresh').addEventListener('click', refresh);
  refresh(); if (kind === 'mcp') loadRecipes();
}

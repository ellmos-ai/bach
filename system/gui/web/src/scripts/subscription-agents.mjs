/* Subscription-Prompt-Agents – Verwaltung lokaler Prompt-Agenten mit Abo-Prompt. */

const API_BASE = '/api/agent-studio/subscription-agents';
const MAX_AVATAR_CHARS = 240000;
const AVATAR_DATA_PATTERN = /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/;

function escapeHtml(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[ch]));
}

function initialize() {
  const $ = id => document.getElementById(id);
  const state = {
    agents: [],
    prompts: [],
    blueprints: [],
    edit: null,
    editPrompt: null,
    avatar: '',
    busy: false
  };

  function notify(id, text, error) {
    const el = $(id);
    if (!el) return;
    el.textContent = text || '';
    if (error) el.dataset.error = 'true';
    else delete el.dataset.error;
  }

  async function api(path, options = {}) {
    const config = Object.assign({}, options, {
      headers: Object.assign({ 'Content-Type': 'application/json' }, options.headers || {})
    });
    const response = await fetch(API_BASE + path, config);
    const raw = await response.text();
    let data = null;
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch (error) {
        data = { detail: raw };
      }
    }
    if (!response.ok) {
      const detail = data && (data.detail || data.error);
      throw new Error(detail || ('HTTP ' + response.status));
    }
    return data || {};
  }

  const button = (label, action) => {
    const el = document.createElement('button');
    el.type = 'button';
    el.textContent = label;
    el.addEventListener('click', action);
    return el;
  };

  const option = (value, label) => {
    const el = document.createElement('option');
    el.value = value;
    el.textContent = label;
    return el;
  };

  function parseSkills(agent) {
    const raw = agent ? agent.skills_json : null;
    if (Array.isArray(raw)) return raw.filter(item => typeof item === 'string');
    if (typeof raw !== 'string' || !raw.trim()) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter(item => typeof item === 'string') : [];
    } catch (error) {
      return [];
    }
  }

  function promptTextOf(agent) {
    if (!agent) return '';
    if (typeof agent.prompt_text === 'string' && agent.prompt_text) return agent.prompt_text;
    const linked = state.prompts.find(item => item.prompt_id === agent.prompt_id || item.id === agent.prompt_id);
    if (linked && typeof linked.prompt_text === 'string') return linked.prompt_text;
    return '';
  }

  function statusLabel(status) {
    const labels = {
      idle: 'bereit',
      running: 'läuft',
      stopped: 'gestoppt',
      expired: 'abgelaufen (ausgeloggt)'
    };
    return labels[status] || status || 'unbekannt';
  }

  function expiryText(agent) {
    if (!agent || !agent.expires_at) return '';
    return ' · Heartbeat bis ' + escapeHtml(String(agent.expires_at));
  }

  function preview(text, limit) {
    const value = String(text == null ? '' : text).trim();
    if (!value) return 'Kein Prompt-Text hinterlegt.';
    return value.length > limit ? value.slice(0, limit) + ' …' : value;
  }

  // ---- Prompts -------------------------------------------------------------

  function renderPrompts() {
    const container = $('sa-prompts');
    if (!container) return;
    container.replaceChildren();
    if (!state.prompts.length) {
      const empty = document.createElement('p');
      empty.className = 'chain-empty';
      empty.textContent = 'Keine Abo-Prompts vorhanden.';
      container.append(empty);
      return;
    }
    for (const prompt of state.prompts) {
      const card = document.createElement('article');
      card.className = 'chain-card';
      card.dataset.promptId = prompt.prompt_id || prompt.id || '';

      const head = document.createElement('div');
      head.className = 'chain-actions';
      const title = document.createElement('h3');
      title.textContent = prompt.name || prompt.prompt_id || 'Prompt';
      head.append(title, button('Bearbeiten', () => openPromptEditor(prompt)));
      card.append(head);

      const meta = document.createElement('p');
      meta.className = 'chain-meta';
      const owner = state.agents.find(agent => agent.prompt_id === (prompt.prompt_id || prompt.id));
      meta.textContent = owner ? 'verknüpft mit ' + (owner.title || owner.name) : 'frei – keinem Agenten zugeordnet';
      card.append(meta);

      const text = document.createElement('p');
      text.className = 'chain-prompt-text';
      text.textContent = preview(prompt.prompt_text, 240);
      text.title = 'Klicken zum Kopieren';
      text.addEventListener('click', () => copyText(prompt.prompt_text, 'sa-status'));
      card.append(text);

      const actions = document.createElement('div');
      actions.className = 'chain-actions';
      actions.append(button('Kopieren', () => copyText(prompt.prompt_text, 'sa-status')));
      if (owner) actions.append(button('Duplizieren', () => duplicate(owner)));
      actions.append(button('Löschen', () => deletePrompt(prompt)));
      card.append(actions);
      container.append(card);
    }
  }

  async function deletePrompt(prompt) {
    const id = prompt.prompt_id || prompt.id;
    if (!id) return;
    if (!window.confirm('Abo-Prompt „' + (prompt.name || id) + '“ löschen? Ein verknüpfter Agent wird mit entfernt.')) return;
    try {
      const data = await api('/prompts/' + encodeURIComponent(id), { method: 'DELETE' });
      await load();
      notify('sa-status', data && data.agent_deleted
        ? 'Prompt und verknüpfter Agent gelöscht.'
        : 'Prompt gelöscht.');
    } catch (error) {
      notify('sa-status', error.message, true);
    }
  }

  function openPromptEditor(prompt) {
    state.editPrompt = prompt || null;
    $('sa-prompt-title').textContent = prompt ? 'Abo-Prompt bearbeiten' : 'Neuer Abo-Prompt';
    $('sa-prompt-name').value = prompt ? (prompt.name || '') : '';
    $('sa-prompt-text').value = prompt ? (prompt.prompt_text || '') : '';
    notify('sa-prompt-status', '');
    toggleEditor('sa-prompt-editor', true);
  }

  // ---- Agents --------------------------------------------------------------

  function renderAgents() {
    const grid = $('sa-grid');
    if (!grid) return;
    grid.replaceChildren();
    if (!state.agents.length) {
      const empty = document.createElement('p');
      empty.className = 'chain-empty';
      empty.textContent = 'Keine Prompt-Agenten vorhanden.';
      grid.append(empty);
      return;
    }
    for (const agent of state.agents) {
      const card = document.createElement('article');
      card.className = 'chain-card';
      card.dataset.agentId = String(agent.id);

      const head = document.createElement('div');
      head.className = 'chain-actions';
      const title = document.createElement('h3');
      title.textContent = agent.title || agent.name || ('Agent ' + agent.id);
      const badge = document.createElement('span');
      badge.className = 'chain-badge chain-badge--' + (agent.status || 'idle');
      badge.textContent = statusLabel(agent.status);
      head.append(title, badge);
      card.append(head);

      const meta = document.createElement('p');
      meta.className = 'chain-meta';
      meta.innerHTML = escapeHtml(agent.name || '') + ' · Modell: ' + escapeHtml(agent.model || 'Standard (lokal)') + expiryText(agent);
      card.append(meta);

      if (agent.description) {
        const description = document.createElement('p');
        description.textContent = agent.description;
        card.append(description);
      }

      const skills = parseSkills(agent);
      if (skills.length) {
        const skillsLine = document.createElement('p');
        skillsLine.className = 'chain-meta';
        skillsLine.textContent = 'Skills: ' + skills.join(', ');
        card.append(skillsLine);
      }

      const promptLine = document.createElement('p');
      promptLine.textContent = preview(promptTextOf(agent), 240);
      card.append(promptLine);

      const actions = document.createElement('div');
      actions.className = 'chain-actions';
      actions.append(
        button('Bearbeiten', () => openEditor(agent)),
        button('Duplizieren', () => duplicate(agent)),
        button('Kopieren', () => copyText(promptTextOf(agent), 'sa-status')),
        button('Start', () => heartbeat(agent)),
        button('Stop', () => stopAgent(agent)),
        button('Löschen', () => deleteAgent(agent))
      );
      card.append(actions);

      grid.append(card);
    }
  }

  function render() {
    renderPrompts();
    renderAgents();
    const counter = $('sa-count');
    if (counter) counter.textContent = state.agents.length + ' Agent(en), ' + state.prompts.length + ' Prompt(s)';
  }

  function toggleEditor(id, open) {
    const el = $(id);
    if (!el) return;
    if (open) {
      el.hidden = false;
      el.setAttribute('aria-expanded', 'true');
      const first = el.querySelector('input,textarea,select');
      if (first) first.focus();
    } else {
      el.hidden = true;
      el.setAttribute('aria-expanded', 'false');
    }
  }

  async function copyText(text, statusId) {
    const value = String(text == null ? '' : text);
    if (!value) {
      notify(statusId, 'Kein Prompt-Text zum Kopieren.', true);
      return;
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        throw new Error('Zwischenablage nicht verfügbar');
      }
      notify(statusId, 'Prompt-Text kopiert.');
    } catch (error) {
      notify(statusId, 'Kopieren fehlgeschlagen: ' + error.message, true);
    }
  }

  async function heartbeat(agent) {
    try {
      await api('/' + agent.id + '/heartbeat', { method: 'POST', body: '{}' });
      await load();
      notify('sa-status', 'Agent „' + (agent.title || agent.name) + '“ gestartet.');
    } catch (error) {
      notify('sa-status', error.message, true);
    }
  }

  async function stopAgent(agent) {
    try {
      await api('/' + agent.id + '/stop', { method: 'POST', body: '{}' });
      await load();
      notify('sa-status', 'Agent gestoppt.');
    } catch (error) {
      notify('sa-status', error.message, true);
    }
  }

  async function duplicate(agent) {
    try {
      await api('/' + agent.id + '/duplicate', { method: 'POST', body: '{}' });
      await load();
      notify('sa-status', 'Agent dupliziert.');
    } catch (error) {
      notify('sa-status', error.message, true);
    }
  }

  async function deleteAgent(agent) {
    if (!window.confirm('Agent „' + (agent.title || agent.name) + '“ mit Prompt löschen?')) return;
    try {
      const data = await api('/' + agent.id, { method: 'DELETE' });
      await load();
      notify('sa-status', data && data.prompt_deleted
        ? 'Agent und Prompt gelöscht.'
        : 'Agent gelöscht.');
    } catch (error) {
      notify('sa-status', error.message, true);
    }
  }

  // ---- Editor --------------------------------------------------------------

  function validAvatar(value) {
    if (!value) return true;
    if (value.startsWith('data:')) {
      return value.length <= MAX_AVATAR_CHARS && AVATAR_DATA_PATTERN.test(value);
    }
    return true;
  }

  function mountAvatar(container, value) {
    if (!container) return;
    state.avatar = value || '';
    container.replaceChildren();
    const lib = window.BachAvatars;
    if (lib && typeof lib.mountAvatarPicker === 'function') {
      lib.mountAvatarPicker(container, state.avatar, '', '', selected => {
        state.avatar = selected || '';
      });
      return;
    }
    const input = document.createElement('input');
    input.type = 'text';
    input.value = state.avatar;
    input.placeholder = 'preset:companion oder data:image/png;base64,…';
    input.addEventListener('input', () => {
      state.avatar = input.value.trim();
    });
    container.append(input);
  }

  function fillBlueprints(selected) {
    const select = $('sa-blueprint');
    if (!select) return;
    select.replaceChildren(option('', 'Keine Vorlage (kein Blueprint)'));
    for (const blueprint of state.blueprints) {
      select.append(option(String(blueprint.id), blueprint.title || blueprint.name || ('Vorlage ' + blueprint.id)));
    }
    select.value = selected == null ? '' : String(selected);
  }

  function openEditor(agent) {
    state.edit = agent || null;
    $('sa-editor-title').textContent = agent ? 'Prompt-Agent bearbeiten' : 'Neuer Prompt-Agent';
    $('sa-name').value = agent ? (agent.name || '') : '';
    $('sa-title').value = agent ? (agent.title || '') : '';
    $('sa-description').value = agent ? (agent.description || '') : '';
    $('sa-model').value = agent ? (agent.model || '') : '';
    $('sa-skills').value = parseSkills(agent).join(', ');
    $('sa-prompt').value = agent ? promptTextOf(agent) : '';
    fillBlueprints(agent ? agent.blueprint_id : '');
    mountAvatar($('sa-avatar'), agent ? (agent.avatar || '') : '');
    notify('sa-editor-status', '');
    toggleEditor('sa-editor', true);
  }

  function splitSkills(value) {
    return String(value || '')
      .split(',')
      .map(item => item.trim())
      .filter((item, index, list) => item && list.indexOf(item) === index);
  }

  // ---- Laden ---------------------------------------------------------------

  async function loadBlueprints() {
    try {
      const response = await fetch('/api/agent-studio/blueprints', { headers: { 'Accept': 'application/json' } });
      const data = response.ok ? await response.json() : [];
      const items = Array.isArray(data) ? data : (data && (data.blueprints || data.items)) || [];
      state.blueprints = items.filter(item => item && item.id != null);
    } catch (error) {
      state.blueprints = [];
    }
  }

  async function load() {
    notify('sa-status', 'Lade Prompt-Agenten …');
    try {
      const list = await api('/list');
      state.agents = Array.isArray(list.agents) ? list.agents : [];
      const prompts = await api('/prompts');
      state.prompts = Array.isArray(prompts.prompts) ? prompts.prompts : [];
      render();
      notify('sa-status', 'Daten geladen.');
    } catch (error) {
      notify('sa-status', error.message, true);
    }
  }

  // ---- Verdrahtung ---------------------------------------------------------

  const refresh = $('sa-refresh');
  if (refresh) refresh.addEventListener('click', () => load());
  const create = $('sa-new');
  if (create) create.addEventListener('click', () => openEditor(null));
  const newPrompt = $('sa-new-prompt');
  if (newPrompt) newPrompt.addEventListener('click', () => openPromptEditor(null));

  const form = $('sa-form');
  if (form) {
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (state.busy || !form.reportValidity()) return;
      const payload = {
        name: $('sa-name').value.trim(),
        title: $('sa-title').value.trim(),
        description: $('sa-description').value.trim(),
        model: $('sa-model').value.trim(),
        avatar: state.avatar || '',
        skills: splitSkills($('sa-skills').value),
        prompt_text: $('sa-prompt').value,
        blueprint_id: $('sa-blueprint').value || null
      };
      if (!validAvatar(payload.avatar)) {
        notify('sa-editor-status', 'Avatar ungültig: erlaubt sind preset:… oder PNG/JPEG/WebP bis 240 000 Zeichen.', true);
        return;
      }
      state.busy = true;
      $('sa-save').disabled = true;
      try {
        if (state.edit) {
          await api('/' + state.edit.id, { method: 'PUT', body: JSON.stringify(payload) });
        } else {
          await api('/create', { method: 'POST', body: JSON.stringify(payload) });
        }
        toggleEditor('sa-editor', false);
        await load();
        notify('sa-status', 'Prompt-Agent gespeichert.');
      } catch (error) {
        notify('sa-editor-status', error.message, true);
      } finally {
        state.busy = false;
        $('sa-save').disabled = false;
      }
    });
  }

  document.addEventListener('click', event => {
    const closer = event.target.closest('[data-close]');
    if (closer && closer.dataset.close) toggleEditor(closer.dataset.close, false);
  });

  const promptForm = $('sa-prompt-form');
  if (promptForm) {
    promptForm.addEventListener('submit', async event => {
      event.preventDefault();
      if (state.busy || !promptForm.reportValidity()) return;
      const payload = {
        name: $('sa-prompt-name').value.trim(),
        prompt_text: $('sa-prompt-text').value
      };
      state.busy = true;
      $('sa-prompt-save').disabled = true;
      try {
        if (state.editPrompt) {
          const id = state.editPrompt.prompt_id || state.editPrompt.id;
          await api('/prompts/' + encodeURIComponent(id), { method: 'PUT', body: JSON.stringify(payload) });
        } else {
          await api('/prompts', { method: 'POST', body: JSON.stringify(payload) });
        }
        toggleEditor('sa-prompt-editor', false);
        await load();
        notify('sa-status', 'Prompt gespeichert.');
      } catch (error) {
        notify('sa-prompt-status', error.message, true);
      } finally {
        state.busy = false;
        $('sa-prompt-save').disabled = false;
      }
    });
  }

  const upload = $('sa-avatar-upload');
  if (upload) {
    upload.addEventListener('change', () => {
      const file = upload.files && upload.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.addEventListener('load', () => {
        const dataUrl = String(reader.result || '');
        if (!validAvatar(dataUrl)) {
          notify('sa-editor-status', 'Avatar-Bild ungültig oder zu groß (max. 240 000 Zeichen, PNG/JPEG/WebP).', true);
          return;
        }
        mountAvatar($('sa-avatar'), dataUrl);
        notify('sa-editor-status', 'Avatar übernommen.');
      });
      reader.readAsDataURL(file);
    });
  }

  loadBlueprints();
  load();
}

if (typeof document !== 'undefined') initialize();

/**
 * BACH Skills Board - Hierarchie-Verwaltung
 * Drag & Drop Zuordnung von Skills, Experts, Services, Workflows zu Agenten
 */

// ═══════════════════════════════════════════════════════════════
// CONFIGURATION
// ═══════════════════════════════════════════════════════════════

const HIERARCHY_TYPES = {
    agent: { color: '#e74c3c', label: 'Agent', icon: '🤖', order: 1 },
    expert: { color: '#27ae60', label: 'Expert', icon: '🧠', order: 2 },
    skill: { color: '#3498db', label: 'Skill', icon: '⚡', order: 3 },
    service: { color: '#2980b9', label: 'Service', icon: '🔧', order: 4 },
    workflow: { color: '#9b59b6', label: 'Workflow', icon: '📋', order: 5 }
};

// State
let hierarchyData = null;
let selectedItem = null;
let draggedItem = null;
let currentSourceFile = null;

// ═══════════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════════

// Team Flow State (BOARD_005)
let teamFlow = [];

document.addEventListener('DOMContentLoaded', async () => {
    console.log('[Skills Board] Initialisiert');
    await loadHierarchyData();
    renderTree();
    setupSearch();
    setupFilters();
});

async function loadHierarchyData() {
    try {
        const response = await fetch('/api/skills-board/hierarchy');
        if (response.ok) {
            hierarchyData = await response.json();
        } else {
            // Fallback: Lade statische Daten
            console.warn('[Skills Board] API nicht verfuegbar, lade Fallback');
            hierarchyData = await loadFallbackData();
        }
    } catch (error) {
        console.error('[Skills Board] Fehler:', error);
        hierarchyData = await loadFallbackData();
    }
}

async function loadFallbackData() {
    // Minimale Fallback-Daten
    return {
        items: {
            agents: [],
            experts: [],
            skills: [],
            services: [],
            workflows: []
        },
        assignments: {}
    };
}

// ═══════════════════════════════════════════════════════════════
// TREE RENDERING
// ═══════════════════════════════════════════════════════════════

function renderTree() {
    const container = document.getElementById('tree-content');
    if (!hierarchyData || !hierarchyData.items) {
        container.innerHTML = '<p style="padding: 1rem; color: var(--text-muted);">Keine Daten geladen</p>';
        return;
    }

    const sections = [
        { type: 'agent', key: 'agents', label: 'Agenten' },
        { type: 'expert', key: 'experts', label: 'Experts' },
        { type: 'skill', key: 'skills', label: 'Skills' },
        { type: 'service', key: 'services', label: 'Services' },
        { type: 'workflow', key: 'workflows', label: 'Workflows' }
    ];

    // Lade gespeicherte expanded-State
    const expandedSections = JSON.parse(localStorage.getItem('skills-expanded-sections') || '[]');

    container.innerHTML = sections.map(section => {
        const items = hierarchyData.items[section.key] || [];
        const typeConfig = HIERARCHY_TYPES[section.type];
        // Default: collapsed, außer explizit expanded
        const isCollapsed = !expandedSections.includes(section.type);

        return `
            <div class="tree-section ${isCollapsed ? 'collapsed' : ''}" data-type="${section.type}">
                <div class="tree-section-header bg-${section.type}" onclick="toggleSection(this)">
                    <span class="icon">${typeConfig.icon}</span>
                    <span class="type-${section.type}">${section.label}</span>
                    <span class="count">${items.length}</span>
                    <span class="chevron">▼</span>
                </div>
                <div class="tree-items">
                    ${items.map(item => renderTreeItem(item, section.type)).join('')}
                </div>
            </div>
        `;
    }).join('');

    // Setup Drag & Drop
    setupDragAndDrop();
}

function renderTreeItem(item, type) {
    const typeConfig = HIERARCHY_TYPES[type];
    const isAgent = type === 'agent';
    const assignments = isAgent && hierarchyData.assignments[item.id];

    // Fix für leere Namen: ID als Fallback verwenden
    const displayName = item.name && item.name.trim() ? item.name : item.id;
    const hasAssignments = assignments && (
        (assignments.experts && assignments.experts.length > 0) ||
        (assignments.skills && assignments.skills.length > 0) ||
        (assignments.services && assignments.services.length > 0) ||
        (assignments.workflows && assignments.workflows.length > 0)
    );

    let nestedHtml = '';
    if (hasAssignments) {
        // Lade gespeicherten expanded-State für diesen Agent
        const expandedAgents = JSON.parse(localStorage.getItem('skills-expanded-agents') || '[]');
        const isExpanded = expandedAgents.includes(item.id);

        nestedHtml = `
            <div class="tree-children ${isExpanded ? '' : 'hidden'}" id="agent-children-${item.id}">
                ${renderNestedAssignments(assignments)}
            </div>
        `;
    }

    // Expand-Button nur für Agenten mit Zuweisungen
    const expandBtn = hasAssignments
        ? `<span class="expand-btn" onclick="toggleAgentChildren('${item.id}'); event.stopPropagation();">▶</span>`
        : '<span class="expand-btn" style="visibility: hidden;">▶</span>';

    return `
        <div class="tree-item ${isAgent ? 'is-agent has-children' : ''}"
             data-id="${item.id}"
             data-type="${type}"
             data-name="${item.name}"
             draggable="${!isAgent}"
             onclick="selectItem('${item.id}', '${type}')">
            ${isAgent ? expandBtn : ''}
            <span class="item-icon">${typeConfig.icon}</span>
            <span class="item-name">${displayName}</span>
            ${hasAssignments ? `<span class="item-badge">${countAssignments(assignments)}</span>` : ''}
        </div>
        ${nestedHtml}
    `;
}

function countAssignments(assignments) {
    if (!assignments) return 0;
    return (assignments.experts?.length || 0) +
        (assignments.skills?.length || 0) +
        (assignments.services?.length || 0) +
        (assignments.workflows?.length || 0);
}

function toggleAgentChildren(agentId) {
    const children = document.getElementById('agent-children-' + agentId);
    if (!children) return;

    const wasHidden = children.classList.contains('hidden');
    children.classList.toggle('hidden');

    // Update expand button
    const agentItem = document.querySelector(`.tree-item[data-id="${agentId}"][data-type="agent"]`);
    if (agentItem) {
        const expandBtn = agentItem.querySelector('.expand-btn');
        if (expandBtn) {
            expandBtn.textContent = wasHidden ? '▼' : '▶';
        }
    }

    // Zustand speichern
    const expandedAgents = JSON.parse(localStorage.getItem('skills-expanded-agents') || '[]');
    if (wasHidden) {
        if (!expandedAgents.includes(agentId)) expandedAgents.push(agentId);
    } else {
        const idx = expandedAgents.indexOf(agentId);
        if (idx > -1) expandedAgents.splice(idx, 1);
    }
    localStorage.setItem('skills-expanded-agents', JSON.stringify(expandedAgents));
}

function renderNestedAssignments(assignments) {
    let html = '';

    ['experts', 'skills', 'services', 'workflows'].forEach(key => {
        const ids = assignments[key] || [];
        const type = key.slice(0, -1); // Remove 's'
        const typeConfig = HIERARCHY_TYPES[type];
        const items = hierarchyData.items[key] || [];

        ids.forEach(id => {
            const item = items.find(i => i.id === id);
            if (item) {
                html += `
                    <div class="tree-item tree-item-nested"
                         data-id="${id}"
                         data-type="${type}"
                         data-name="${item.name}"
                         onclick="selectItem('${id}', '${type}'); event.stopPropagation();">
                        <span class="item-icon" style="opacity: 0.7">${typeConfig.icon}</span>
                        <span class="item-name">${item.name}</span>
                    </div>
                `;
            }
        });
    });

    return html;
}

function toggleSection(header) {
    const section = header.parentElement;
    const sectionType = section.dataset.type;
    const wasCollapsed = section.classList.contains('collapsed');

    section.classList.toggle('collapsed');

    // Zustand speichern
    const expandedSections = JSON.parse(localStorage.getItem('skills-expanded-sections') || '[]');
    if (wasCollapsed) {
        // War collapsed, jetzt expanded
        if (!expandedSections.includes(sectionType)) expandedSections.push(sectionType);
    } else {
        // War expanded, jetzt collapsed
        const idx = expandedSections.indexOf(sectionType);
        if (idx > -1) expandedSections.splice(idx, 1);
    }
    localStorage.setItem('skills-expanded-sections', JSON.stringify(expandedSections));
}

// ═══════════════════════════════════════════════════════════════
// ITEM SELECTION & DETAIL VIEW
// ═══════════════════════════════════════════════════════════════

function selectItem(id, type) {
    // Update selection state
    document.querySelectorAll('.tree-item.selected').forEach(el => el.classList.remove('selected'));
    const itemEl = document.querySelector(`.tree-item[data-id="${id}"][data-type="${type}"]`);
    if (itemEl) itemEl.classList.add('selected');

    // Find item data
    const pluralType = type + 's';
    const items = hierarchyData.items[pluralType] || [];
    const item = items.find(i => i.id === id);

    if (!item) return;

    selectedItem = { ...item, type };
    renderDetailView(item, type);
}

function renderDetailView(item, type) {
    const panel = document.getElementById('detail-panel');
    const typeConfig = HIERARCHY_TYPES[type];
    const isAgent = type === 'agent';
    const assignments = isAgent ? (hierarchyData.assignments[item.id] || {}) : null;

    // Fix für leere Namen
    const displayName = item.name && item.name.trim() ? item.name : item.id;

    panel.innerHTML = `
        <div class="detail-header">
            <span class="detail-icon">${typeConfig.icon}</span>
            <div class="detail-title">
                <h1>${displayName}</h1>
                <span class="detail-type type-${type}">${typeConfig.label}</span>
            </div>
            <div class="detail-actions">
                <button class="btn btn-secondary" onclick="editItem('${item.id}', '${type}')">Bearbeiten</button>
                ${isAgent ? `<button class="btn btn-primary" onclick="createTaskForAgent('${item.id}')">+ Task erstellen</button>` : ''}
            </div>
        </div>
        
        <div class="detail-tabs">
            <button class="tab-btn active" onclick="switchTab('info')">Info & Zuweisungen</button>
            <button class="tab-btn" id="source-tab-btn" onclick="switchTab('source')">Quellcode / MD</button>
        </div>

        <div class="detail-content" style="padding: 0; position: relative; flex: 1; display: flex; flex-direction: column;">
            <!-- INFO TAB -->
            <div id="info-pane" class="tab-pane active" style="padding: 1.5rem; overflow-y: auto; flex: 1;">
                <div class="detail-section">
                    <h3>Beschreibung</h3>
                    <p class="detail-description">${item.description || 'Keine Beschreibung vorhanden.'}</p>
                </div>

                ${isAgent ? renderAgentAssignments(item.id, assignments) : renderItemUsage(item.id, type)}
                ${isAgent ? renderTeamFlowPanel(item.id) : ''}
                ${isAgent ? renderTaskForm(item.id) : ''}
            </div>

            <!-- SOURCE TAB -->
            <div id="source-pane" class="tab-pane" style="display:none; flex: 1; min-height: 0;">
                <div id="source-container" class="source-editor-container" style="height: 100%; display: flex; flex-direction: column; padding: 1.5rem;">
                    <div class="path-bar" id="path-bar" style="display:none; margin-bottom: 1rem;">
                        <span class="path-text" id="source-path" style="font-family: monospace; font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis;"></span>
                        <button class="copy-btn" onclick="copySourcePath()">Pfad kopieren</button>
                        <button class="copy-btn" onclick="toggleFullscreen()" title="Vollbild" style="margin-left: 0.5rem;">⤢</button>
                    </div>
                    <textarea id="source-editor" 
                              style="flex: 1; width: 100%; padding: 1rem; background: #1e1e1e; color: #d4d4d4; border: 1px solid var(--border); border-radius: 8px; font-family: monospace; font-size: 0.9rem; resize: none; margin-bottom: 1rem;"
                              placeholder="Lade Quellcode..."></textarea>
                    <div style="display: flex; justify-content: flex-end; gap: 0.5rem;">
                        <button class="btn btn-primary" onclick="saveItemSource()">Quellcode speichern</button>
                    </div>
                </div>
                <div id="source-empty" class="empty-state" style="display:none; padding-top: 5rem;">
                    <span class="icon">🔍</span>
                    <h3>Keine Quelldatei gefunden</h3>
                    <p>Für dieses Element (.md/.txt) wurde keine Entsprechung im skills/ Ordner gefunden.</p>
                </div>
            </div>
        </div>
    `;

    // Reset tab state
    currentSourceFile = null;

    // Setup Drop Zones
    if (isAgent) {
        setupDropZones(item.id);
    }
}

function switchTab(tabId) {
    // Buttons
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    const activeBtn = document.querySelector(`.tab-btn[onclick="switchTab('${tabId}')"]`);
    if (activeBtn) activeBtn.classList.add('active');

    // Panes
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.style.display = 'none';
        pane.classList.remove('active');
    });
    const activePane = document.getElementById(`${tabId}-pane`);
    if (activePane) {
        activePane.style.display = (tabId === 'info' ? 'block' : 'flex');
        activePane.classList.add('active');
    }

    if (tabId === 'source' && selectedItem) {
        loadItemSource();
    }
}

async function loadItemSource() {
    if (!selectedItem) return;

    const editor = document.getElementById('source-editor');
    const container = document.getElementById('source-container');
    const emptyState = document.getElementById('source-empty');
    const pathBar = document.getElementById('path-bar');
    const pathText = document.getElementById('source-path');

    if (currentSourceFile) return; // Bereits geladen

    try {
        editor.value = "Lade...";
        const params = new URLSearchParams({
            type: selectedItem.type,
            id: selectedItem.id,
            description: selectedItem.description || ''
        });
        if (selectedItem.path_hint) {
            params.set('path_hint', selectedItem.path_hint);
        }
        const url = `/api/skills-board/item-file?${params.toString()}`;
        const response = await fetch(url);
        const data = await response.json();

        if (data.success) {
            currentSourceFile = data;
            editor.value = data.content;
            pathText.textContent = data.path;
            pathBar.style.display = 'flex';
            container.style.display = 'flex';
            emptyState.style.display = 'none';
        } else {
            console.warn('[Skills Board] Keine Quelldatei:', data.error);
            container.style.display = 'none';
            emptyState.style.display = 'flex';
        }
    } catch (e) {
        console.error('[Skills Board] Loader Fehler:', e);
        showToast('Fehler beim Laden der Quelldatei', 'error');
    }
}

async function saveItemSource() {
    if (!currentSourceFile) return;

    const content = document.getElementById('source-editor').value;

    try {
        const response = await fetch('/api/skills-board/item-file', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                path: currentSourceFile.absolute_path,
                content: content
            })
        });

        const data = await response.json();
        if (data.success) {
            showToast('Quellcode gespeichert', 'success');
        } else {
            showToast('Fehler: ' + data.error, 'error');
        }
    } catch (e) {
        console.error('[Skills Board] Save Fehler:', e);
        showToast('Fehler beim Speichern', 'error');
    }
}

function copySourcePath() {
    if (!currentSourceFile) return;
    const path = currentSourceFile.path;
    navigator.clipboard.writeText(path).then(() => {
        showToast('Pfad kopiert: ' + path, 'info');
    }).catch(err => {
        // Fallback fuer unsichere Kontexte
        const el = document.createElement('textarea');
        el.value = path;
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
        showToast('Pfad kopiert (FB)', 'info');
    });
}

function renderAgentAssignments(agentId, assignments) {
    const sections = [
        { key: 'experts', type: 'expert', label: 'Zugewiesene Experts' },
        { key: 'skills', type: 'skill', label: 'Zugewiesene Skills' },
        { key: 'services', type: 'service', label: 'Zugewiesene Services' },
        { key: 'workflows', type: 'workflow', label: 'Zugewiesene Workflows' }
    ];

    return sections.map(section => {
        const ids = assignments[section.key] || [];
        const items = hierarchyData.items[section.key] || [];
        const typeConfig = HIERARCHY_TYPES[section.type];

        const assignedItems = ids.map(id => items.find(i => i.id === id)).filter(Boolean);

        return `
            <div class="detail-section">
                <h3>${typeConfig.icon} ${section.label}</h3>
                <div class="assigned-grid" data-drop-zone="${section.type}" data-agent="${agentId}">
                    ${assignedItems.map(item => `
                        <div class="assigned-item bg-${section.type}"
                             data-id="${item.id}"
                             data-type="${section.type}">
                            ${item.name}
                            <span class="remove-btn" onclick="removeAssignment('${agentId}', '${section.key}', '${item.id}'); event.stopPropagation();">✕</span>
                        </div>
                    `).join('') || '<span style="color: var(--text-muted); font-size: 0.9rem;">Keine zugewiesen</span>'}
                </div>
                <div class="drop-zone" data-drop-zone="${section.type}" data-agent="${agentId}">
                    ${typeConfig.icon} ${typeConfig.label} hierher ziehen
                </div>
            </div>
        `;
    }).join('');
}

function renderItemUsage(itemId, type) {
    // Find which agents use this item
    const usedBy = [];
    const pluralType = type + 's';

    Object.entries(hierarchyData.assignments || {}).forEach(([agentId, assignments]) => {
        if (assignments[pluralType] && assignments[pluralType].includes(itemId)) {
            const agent = (hierarchyData.items.agents || []).find(a => a.id === agentId);
            if (agent) usedBy.push(agent);
        }
    });

    return `
        <div class="detail-section">
            <h3>Verwendet von</h3>
            <div class="assigned-grid">
                ${usedBy.map(agent => `
                    <div class="assigned-item bg-agent"
                         onclick="selectItem('${agent.id}', 'agent')">
                        🤖 ${agent.name}
                    </div>
                `).join('') || '<span style="color: var(--text-muted); font-size: 0.9rem;">Noch keinem Agenten zugewiesen</span>'}
            </div>
        </div>
    `;
}

function renderTaskForm(agentId) {
    return `
        <div class="detail-section">
            <h3>📝 Auftrag an Agent</h3>
            <div class="task-form">
                <textarea id="task-description" placeholder="Beschreibe den Auftrag fuer diesen Agenten..."></textarea>
                <div class="form-row">
                    <select id="task-priority">
                        <option value="P1">P1 - Kritisch</option>
                        <option value="P2">P2 - Hoch</option>
                        <option value="P3" selected>P3 - Normal</option>
                        <option value="P4">P4 - Niedrig</option>
                    </select>
                    <button class="btn btn-primary" onclick="submitAgentTask('${agentId}')">
                        Task erstellen
                    </button>
                </div>
            </div>
        </div>
    `;
}

// ═══════════════════════════════════════════════════════════════
// DRAG & DROP
// ═══════════════════════════════════════════════════════════════

function setupDragAndDrop() {
    document.querySelectorAll('.tree-item[draggable="true"]').forEach(el => {
        el.addEventListener('dragstart', handleDragStart);
        el.addEventListener('dragend', handleDragEnd);
    });
}

function setupDropZones(agentId) {
    document.querySelectorAll('.drop-zone, .assigned-grid').forEach(zone => {
        zone.addEventListener('dragover', handleDragOver);
        zone.addEventListener('dragleave', handleDragLeave);
        zone.addEventListener('drop', handleDrop);
    });
}

function handleDragStart(e) {
    draggedItem = {
        id: e.target.dataset.id,
        type: e.target.dataset.type,
        name: e.target.dataset.name
    };
    e.target.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'copy';
}

function handleDragEnd(e) {
    e.target.classList.remove('dragging');
    draggedItem = null;
    document.querySelectorAll('.drop-zone.drag-over').forEach(z => z.classList.remove('drag-over'));
}

function handleDragOver(e) {
    e.preventDefault();
    const zone = e.currentTarget;
    const zoneType = zone.dataset.dropZone;

    // Only allow dropping matching types
    if (draggedItem && draggedItem.type === zoneType) {
        e.dataTransfer.dropEffect = 'copy';
        zone.classList.add('drag-over');
    }
}

function handleDragLeave(e) {
    e.currentTarget.classList.remove('drag-over');
}

function handleDrop(e) {
    e.preventDefault();
    const zone = e.currentTarget;
    zone.classList.remove('drag-over');

    if (!draggedItem) return;

    const agentId = zone.dataset.agent;
    const itemType = draggedItem.type;
    const itemId = draggedItem.id;

    if (agentId && itemType === zone.dataset.dropZone) {
        addAssignment(agentId, itemType + 's', itemId);
    }
}

// ═══════════════════════════════════════════════════════════════
// ASSIGNMENTS
// ═══════════════════════════════════════════════════════════════

async function addAssignment(agentId, key, itemId) {
    // Update local state
    if (!hierarchyData.assignments[agentId]) {
        hierarchyData.assignments[agentId] = { experts: [], skills: [], services: [], workflows: [] };
    }
    if (!hierarchyData.assignments[agentId][key]) {
        hierarchyData.assignments[agentId][key] = [];
    }

    // Check if already assigned
    if (hierarchyData.assignments[agentId][key].includes(itemId)) {
        showToast('Bereits zugewiesen', 'warning');
        return;
    }

    hierarchyData.assignments[agentId][key].push(itemId);

    // Save to API
    try {
        await saveHierarchy();
        showToast('Zugewiesen', 'success');
        // Re-render
        selectItem(agentId, 'agent');
        renderTree();
    } catch (error) {
        showToast('Fehler beim Speichern', 'error');
    }
}

async function removeAssignment(agentId, key, itemId) {
    if (!hierarchyData.assignments[agentId] || !hierarchyData.assignments[agentId][key]) return;

    const index = hierarchyData.assignments[agentId][key].indexOf(itemId);
    if (index > -1) {
        hierarchyData.assignments[agentId][key].splice(index, 1);
    }

    try {
        await saveHierarchy();
        showToast('Entfernt', 'success');
        selectItem(agentId, 'agent');
        renderTree();
    } catch (error) {
        showToast('Fehler beim Speichern', 'error');
    }
}

async function saveHierarchy() {
    const response = await fetch('/api/skills-board/hierarchy', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(hierarchyData)
    });

    if (!response.ok) {
        throw new Error('Save failed');
    }
}

// ═══════════════════════════════════════════════════════════════
// TASK CREATION
// ═══════════════════════════════════════════════════════════════

async function submitAgentTask(agentId) {
    const description = document.getElementById('task-description').value.trim();
    const priority = document.getElementById('task-priority').value;

    if (!description) {
        showToast('Bitte Beschreibung eingeben', 'warning');
        return;
    }

    const agent = (hierarchyData.items.agents || []).find(a => a.id === agentId);
    const agentName = agent ? agent.name : agentId;

    try {
        await API.tasks.create({
            title: `[${agentName}] ${description.substring(0, 50)}${description.length > 50 ? '...' : ''}`,
            description: description,
            priority: priority,
            project: 'agent-task',
            delegated_to: agentId
        });

        showToast('Task erstellt', 'success');
        document.getElementById('task-description').value = '';
    } catch (error) {
        showToast('Fehler: ' + error.message, 'error');
    }
}

function createTaskForAgent(agentId) {
    const textarea = document.getElementById('task-description');
    if (textarea) {
        textarea.focus();
        textarea.scrollIntoView({ behavior: 'smooth' });
    }
}

// ═══════════════════════════════════════════════════════════════
// SEARCH
// ═══════════════════════════════════════════════════════════════

function setupSearch() {
    const searchInput = document.getElementById('tree-search');
    if (!searchInput) return;

    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        document.querySelectorAll('.tree-item').forEach(item => {
            const name = item.dataset.name?.toLowerCase() || '';
            item.style.display = name.includes(query) ? '' : 'none';
        });

        // Show all sections when searching
        if (query) {
            document.querySelectorAll('.tree-section').forEach(s => s.classList.remove('collapsed'));
        }
    });
}

// ═══════════════════════════════════════════════════════════════
// FILTER (BOARD_003)
// ═══════════════════════════════════════════════════════════════

function setupFilters() {
    const toolbar = document.getElementById('filter-toolbar');
    if (!toolbar) return;

    toolbar.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            // Update active state
            toolbar.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const filter = btn.dataset.filter;
            applyFilter(filter);
        });
    });
}

function applyFilter(filter) {
    document.querySelectorAll('.tree-section').forEach(section => {
        const sectionType = section.dataset.type;
        if (filter === 'all' || sectionType === filter) {
            section.style.display = '';
            section.classList.remove('collapsed');
        } else {
            section.style.display = 'none';
        }
    });
}

// ═══════════════════════════════════════════════════════════════
// EDIT MODAL (BOARD_002)
// ═══════════════════════════════════════════════════════════════

function editItem(id, type) {
    const pluralType = type + 's';
    const items = hierarchyData.items[pluralType] || [];
    const item = items.find(i => i.id === id);

    if (!item) {
        showToast('Element nicht gefunden', 'error');
        return;
    }

    const typeConfig = HIERARCHY_TYPES[type];

    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'edit-modal';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <h2>${typeConfig.icon} ${typeConfig.label} bearbeiten</h2>
                <button class="modal-close" onclick="closeEditModal()">&times;</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>Name</label>
                    <input type="text" id="edit-name" value="${escapeHtml(item.name)}" />
                </div>
                <div class="form-group">
                    <label>Beschreibung</label>
                    <textarea id="edit-description">${escapeHtml(item.description || '')}</textarea>
                </div>
                ${type === 'expert' ? `
                <div class="form-group">
                    <label>Zugewiesene Skills (BOARD_004)</label>
                    <div id="expert-skills" style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem;">
                        ${renderExpertSkillsSelector(id)}
                    </div>
                </div>
                ` : ''}
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeEditModal()">Abbrechen</button>
                <button class="btn btn-primary" onclick="saveItemEdit('${id}', '${type}')">Speichern</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeEditModal();
    });
}

function renderExpertSkillsSelector(expertId) {
    const skills = hierarchyData.items.skills || [];
    const expertSkills = hierarchyData.expertSkills?.[expertId] || [];

    return skills.map(skill => {
        const isAssigned = expertSkills.includes(skill.id);
        return `
            <label style="display: flex; align-items: center; gap: 0.25rem; cursor: pointer;">
                <input type="checkbox" value="${skill.id}" ${isAssigned ? 'checked' : ''}
                       onchange="toggleExpertSkill('${expertId}', '${skill.id}', this.checked)" />
                <span>${escapeHtml(skill.name)}</span>
            </label>
        `;
    }).join('');
}

function toggleExpertSkill(expertId, skillId, checked) {
    if (!hierarchyData.expertSkills) {
        hierarchyData.expertSkills = {};
    }
    if (!hierarchyData.expertSkills[expertId]) {
        hierarchyData.expertSkills[expertId] = [];
    }

    const skills = hierarchyData.expertSkills[expertId];
    if (checked && !skills.includes(skillId)) {
        skills.push(skillId);
    } else if (!checked) {
        const idx = skills.indexOf(skillId);
        if (idx > -1) skills.splice(idx, 1);
    }
}

function closeEditModal() {
    const modal = document.getElementById('edit-modal');
    if (modal) modal.remove();
}

async function saveItemEdit(id, type) {
    const name = document.getElementById('edit-name').value.trim();
    const description = document.getElementById('edit-description').value.trim();

    if (!name) {
        showToast('Name ist erforderlich', 'warning');
        return;
    }

    const pluralType = type + 's';
    const items = hierarchyData.items[pluralType] || [];
    const item = items.find(i => i.id === id);

    if (item) {
        item.name = name;
        item.description = description;
    }

    try {
        await saveHierarchy();
        showToast('Gespeichert', 'success');
        closeEditModal();
        renderTree();
        if (selectedItem && selectedItem.id === id) {
            selectItem(id, type);
        }
    } catch (error) {
        showToast('Fehler beim Speichern', 'error');
    }
}

// ═══════════════════════════════════════════════════════════════
// TEAM FLOW BUILDER (BOARD_005)
// ═══════════════════════════════════════════════════════════════

function renderTeamFlowPanel(agentId) {
    return `
        <div class="detail-section">
            <h3>🔄 Team-Flow Builder</h3>
            <button class="btn btn-secondary flow-toggle" onclick="toggleFlowPanel()">
                Flow anzeigen
            </button>
            <div class="flow-panel" id="flow-panel">
                <div class="flow-header">
                    <h3>Workflow-Kette</h3>
                    <button class="btn btn-secondary" onclick="clearTeamFlow()">Leeren</button>
                </div>
                <div class="flow-canvas" id="flow-canvas"
                     ondragover="handleFlowDragOver(event)"
                     ondrop="handleFlowDrop(event)">
                    ${renderFlowNodes()}
                </div>
                <div style="margin-top: 1rem; display: flex; gap: 0.5rem;">
                    <button class="btn btn-primary" onclick="saveTeamFlow('${agentId}')">Als Workflow speichern</button>
                    <button class="btn btn-secondary" onclick="executeTeamFlow()">Ausfuehren</button>
                </div>
            </div>
        </div>
    `;
}

function renderFlowNodes() {
    if (teamFlow.length === 0) {
        return '<span class="flow-empty">Ziehe Agenten, Experts oder Skills hierher um einen Workflow zu erstellen</span>';
    }

    return teamFlow.map((node, idx) => {
        const typeConfig = HIERARCHY_TYPES[node.type];
        const arrow = idx < teamFlow.length - 1 ? '<span class="flow-arrow">→</span>' : '';
        return `
            <div class="flow-node bg-${node.type}" data-index="${idx}">
                <span class="node-icon">${typeConfig.icon}</span>
                <span>${escapeHtml(node.name)}</span>
                <span class="remove-flow-node" onclick="removeFromFlow(${idx})">✕</span>
            </div>
            ${arrow}
        `;
    }).join('');
}

function toggleFlowPanel() {
    const panel = document.getElementById('flow-panel');
    if (panel) {
        panel.classList.toggle('active');
    }
}

function handleFlowDragOver(e) {
    e.preventDefault();
    if (draggedItem) {
        e.currentTarget.classList.add('drag-over');
        e.dataTransfer.dropEffect = 'copy';
    }
}

function handleFlowDrop(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('drag-over');

    if (!draggedItem) return;

    // Add to team flow
    teamFlow.push({
        id: draggedItem.id,
        type: draggedItem.type,
        name: draggedItem.name
    });

    // Re-render flow
    const canvas = document.getElementById('flow-canvas');
    if (canvas) {
        canvas.innerHTML = renderFlowNodes();
    }
    showToast('Zum Flow hinzugefuegt', 'success');
}

function removeFromFlow(index) {
    teamFlow.splice(index, 1);
    const canvas = document.getElementById('flow-canvas');
    if (canvas) {
        canvas.innerHTML = renderFlowNodes();
    }
}

function clearTeamFlow() {
    teamFlow = [];
    const canvas = document.getElementById('flow-canvas');
    if (canvas) {
        canvas.innerHTML = renderFlowNodes();
    }
    showToast('Flow geleert', 'success');
}

async function saveTeamFlow(agentId) {
    if (teamFlow.length === 0) {
        showToast('Flow ist leer', 'warning');
        return;
    }

    const workflowName = prompt('Name fuer den Workflow:');
    if (!workflowName) return;

    // Add as new workflow
    const newWorkflow = {
        id: 'workflow_' + Date.now(),
        name: workflowName,
        description: `Team-Flow: ${teamFlow.map(n => n.name).join(' → ')}`,
        steps: teamFlow.map(n => ({ id: n.id, type: n.type }))
    };

    if (!hierarchyData.items.workflows) {
        hierarchyData.items.workflows = [];
    }
    hierarchyData.items.workflows.push(newWorkflow);

    try {
        await saveHierarchy();
        showToast('Workflow gespeichert', 'success');
        renderTree();
        teamFlow = [];
        const canvas = document.getElementById('flow-canvas');
        if (canvas) canvas.innerHTML = renderFlowNodes();
    } catch (error) {
        showToast('Fehler beim Speichern', 'error');
    }
}

function executeTeamFlow() {
    if (teamFlow.length === 0) {
        showToast('Flow ist leer', 'warning');
        return;
    }
    showToast(`Flow mit ${teamFlow.length} Schritten wuerde ausgefuehrt (Demo)`, 'success');
}

// ═══════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showToast(message, type = 'success') {
    document.querySelectorAll('.toast').forEach(t => t.remove());

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    setTimeout(() => toast.remove(), 3000);
}

// Export
window.selectItem = selectItem;
window.toggleSection = toggleSection;
window.toggleAgentChildren = toggleAgentChildren;
window.removeAssignment = removeAssignment;
window.submitAgentTask = submitAgentTask;
window.createTaskForAgent = createTaskForAgent;
window.editItem = editItem;
window.closeEditModal = closeEditModal;
window.saveItemEdit = saveItemEdit;
window.toggleExpertSkill = toggleExpertSkill;
window.toggleFlowPanel = toggleFlowPanel;
window.handleFlowDragOver = handleFlowDragOver;
window.handleFlowDrop = handleFlowDrop;
window.removeFromFlow = removeFromFlow;
window.clearTeamFlow = clearTeamFlow;
window.saveTeamFlow = saveTeamFlow;
window.executeTeamFlow = executeTeamFlow;
window.switchTab = switchTab;
window.loadItemSource = loadItemSource;
window.saveItemSource = saveItemSource;
window.copySourcePath = copySourcePath;

function toggleFullscreen() {
    document.querySelector('.skills-board').classList.toggle('fullscreen-mode');
}
window.toggleFullscreen = toggleFullscreen;

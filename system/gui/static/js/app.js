/**
 * BACH Dashboard - Main Application
 */

// ═══════════════════════════════════════════════════════════════
// INITIALIZATION
// ═══════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    console.log('[BACH] Dashboard initialisiert');
    loadFavorites();
    loadDashboard();

    // Auto-Refresh alle 30 Sekunden
    setInterval(loadDashboard, 30000);
});

// ═══════════════════════════════════════════════════════════════
// DASHBOARD
// ═══════════════════════════════════════════════════════════════

async function loadDashboard() {
    try {
        await Promise.all([
            loadStatus(),
            loadRecentTasks(),
            loadSystemInfo()
        ]);

        updateLastRefresh();
    } catch (error) {
        console.error('[BACH] Dashboard-Fehler:', error);
        showToast('Fehler beim Laden', 'error');
    }
}

async function loadStatus() {
    try {
        const data = await API.status();

        document.getElementById('stat-tasks').textContent = data.stats.tasks_open || 0;
        document.getElementById('stat-scanned').textContent = data.stats.scanned_tasks || 0;
        document.getElementById('stat-messages').textContent = data.stats.messages_unread || 0;
        document.getElementById('stat-daemon').textContent = data.stats.scheduler_jobs_active || 0;

        // Status-Indikator
        const statusDot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');

        if (statusDot && data.status === 'online') {
            statusDot.classList.add('online');
            statusDot.classList.remove('offline');
        }
        if (statusText) {
            statusText.textContent = 'Online';
        }
    } catch (error) {
        console.error('[BACH] Status-Fehler:', error);
        const statusDot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');
        if (statusDot) {
            statusDot.classList.add('offline');
            statusDot.classList.remove('online');
        }
        if (statusText) {
            statusText.textContent = 'Offline';
        }
    }
}

async function loadRecentTasks() {
    const container = document.getElementById('tasks-list');

    try {
        // BACH Tasks laden (pending und open)
        const [pRes, oRes] = await Promise.all([API.tasks.list('pending'), API.tasks.list('open')]);
        const tasks = [...(pRes.tasks || []), ...(oRes.tasks || [])];

        if (tasks.length > 0) {
            container.innerHTML = tasks.slice(0, 5).map(task => {
                const priorityClass = getPriorityFromP(task.priority);
                const shortText = task.title.length > 50
                    ? task.title.substring(0, 50) + '...'
                    : task.title;

                return `
                    <div class="list-item ${priorityClass}">
                        <div>
                            <span class="list-item-title">${escapeHtml(shortText)}</span>
                            <span class="list-item-meta">${escapeHtml(task.category || 'Allgemein')}</span>
                        </div>
                        <span class="badge ${priorityClass}">${task.priority}</span>
                    </div>
                `;
            }).join('');
        } else {
            container.innerHTML = '<p class="loading">Keine offenen Tasks</p>';
        }
    } catch (error) {
        console.error('[BACH] Tasks-Fehler:', error);
        container.innerHTML = '<p class="loading">Fehler beim Laden</p>';
    }
}

async function loadSystemInfo() {
    const container = document.getElementById('scanner-status');

    try {
        // Lade Task-Statistiken (alle Status-Typen)
        const pending = await API.tasks.list('pending');
        const open = await API.tasks.list('open');
        const inProgress = await API.tasks.list('in_progress');
        const done = await API.tasks.list('done');

        const pendingCount = pending.tasks ? pending.tasks.length : 0;
        const openCount = open.tasks ? open.tasks.length : 0;
        const inProgressCount = inProgress.tasks ? inProgress.tasks.length : 0;
        const doneCount = done.tasks ? done.tasks.length : 0;

        // Gesamt offen = pending + open + in_progress (konsistent mit /api/status)
        const totalOpen = pendingCount + openCount + inProgressCount;

        container.innerHTML = `
            <div class="scanner-info">
                <div class="scanner-stat">
                    <span>Offen gesamt</span>
                    <span>${totalOpen}</span>
                </div>
                <div class="scanner-stat">
                    <span>Pending</span>
                    <span>${pendingCount}</span>
                </div>
                <div class="scanner-stat">
                    <span>Open</span>
                    <span>${openCount}</span>
                </div>
                <div class="scanner-stat">
                    <span>In Arbeit</span>
                    <span>${inProgressCount}</span>
                </div>
                <div class="scanner-stat">
                    <span>Erledigt</span>
                    <span>${doneCount}</span>
                </div>
            </div>
        `;
    } catch (error) {
        console.error('[BACH] System-Info Fehler:', error);
        container.innerHTML = '<p class="loading">Fehler beim Laden</p>';
    }
}

// ═══════════════════════════════════════════════════════════════
// ACTIONS
// ═══════════════════════════════════════════════════════════════

async function runScan() {
    try {
        showToast('Scanner gestartet...', 'success');
        await API.scanner.run();

        // Nach 2 Sekunden Status aktualisieren
        setTimeout(loadDashboard, 2000);
    } catch (error) {
        showToast('Scanner-Fehler: ' + error.message, 'error');
    }
}

async function loadTasks() {
    try {
        const data = await API.scannedTasks.list();
        console.log('[BACH] Tasks geladen:', data);
        await loadRecentTasks();
        showToast(`${data.count} Tasks geladen`, 'success');
    } catch (error) {
        showToast('Fehler: ' + error.message, 'error');
    }
}

async function sendHeadlessPrompt() {
    const promptEl = document.getElementById('headless-prompt');
    const partnerEl = document.getElementById('headless-partner');
    const infoEl = document.getElementById('headless-info');

    const prompt = promptEl.value.trim();
    if (!prompt) {
        showToast('Bitte einen Prompt eingeben', 'error');
        return;
    }

    infoEl.style.display = 'block';
    infoEl.textContent = 'Session wird gestartet...';
    infoEl.style.color = 'var(--text-muted)';

    try {
        const res = await API.post('/api/ai/headless/run', {
            prompt: prompt,
            partner: partnerEl.value
        });

        if (res.success) {
            showToast('KI Session erfolgreich gestartet', 'success');
            infoEl.textContent = 'Gestartet! Antwort erscheint in der Inbox/Messages.';
            infoEl.style.color = 'var(--accent)';
            promptEl.value = '';
        } else {
            showToast('Fehler: ' + res.error, 'error');
            infoEl.textContent = 'Fehler beim Starten.';
            infoEl.style.color = 'var(--error)';
        }
    } catch (error) {
        showToast('Verbindungsfehler', 'error');
        infoEl.textContent = 'Verbindungsfehler.';
    }
}

// ═══════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════

function getPriorityClass(aufwand) {
    switch (aufwand) {
        case 'hoch': return 'priority-high';
        case 'mittel': return 'priority-medium';
        case 'niedrig': return 'priority-low';
        default: return '';
    }
}

function getPriorityFromP(priority) {
    switch (priority) {
        case 'P1': return 'priority-high';
        case 'P2': return 'priority-medium';
        case 'P3':
        case 'P4': return 'priority-low';
        default: return '';
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function updateLastRefresh() {
    const el = document.getElementById('last-update');
    if (el) {
        el.textContent = 'Aktualisiert: ' + new Date().toLocaleTimeString('de-DE');
    }
}

function showToast(message, type = 'success') {
    // Bestehende Toasts entfernen
    document.querySelectorAll('.toast').forEach(t => t.remove());

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);

    // Nach 3 Sekunden entfernen
    setTimeout(() => toast.remove(), 3000);
}

// ═══════════════════════════════════════════════════════════════
// FAVORITES
// ═══════════════════════════════════════════════════════════════

const ALL_PAGES = [
    { href: '/tasks', label: 'Alle Tasks', primary: true },
    { href: '/agents', label: 'Agenten' },
    { href: '/agents/ati', label: 'ATI — Entwicklung' },
    { href: '/agents/steuer', label: 'Steuer — Steuerberatung' },
    { href: '/agents/gesundheit', label: 'Gesundheit — Medizin' },
    { href: '/agents/persoenlich', label: 'Persoenlich — Alltag' },
    { href: '/agents/foerderplaner', label: 'Foerderplaner — Foerderung' },
    { href: '/partners', label: 'Partner' },
    { href: '/skills-board', label: 'Skills Board' },
    { href: '/financial', label: 'Financial' },
    { href: '/memory', label: 'Memory' },
    { href: '/tools', label: 'Tools' },
    { href: '/prompt-generator', label: 'Prompt-Gen', hidden: true },
    { href: '/messages', label: 'Messages' },
    { href: '/daemon', label: 'Daemon' },
    { href: '/inbox', label: 'Inbox' },
    { href: '/scanner', label: 'Scanner' },
    { href: '/help', label: 'Help' },
    { href: '/docs', label: 'API Docs' }
];

const DEFAULT_FAVORITES = ['/tasks', '/agents', '/skills-board', '/agents/ati', '/financial', '/docs'];

let favoritesEditMode = false;

function loadFavorites() {
    const stored = localStorage.getItem('bach-favorites');
    const favorites = stored ? JSON.parse(stored) : DEFAULT_FAVORITES;
    renderFavorites(favorites);
}

function renderFavorites(favorites) {
    const container = document.getElementById('favorites-container');
    if (!container) return;

    container.innerHTML = favorites.map(href => {
        const page = ALL_PAGES.find(p => p.href === href);
        if (!page) return '';

        const btnClass = page.primary ? 'btn btn-primary' : 'btn btn-secondary';
        return `
            <button class="${btnClass}" onclick="window.location.href='${page.href}'">
                ${escapeHtml(page.label)}
            </button>
        `;
    }).join('');
}

function toggleFavoritesEdit() {
    favoritesEditMode = !favoritesEditMode;
    const editPanel = document.getElementById('favorites-edit');
    const editBtn = document.getElementById('edit-favs-btn');

    if (favoritesEditMode) {
        editPanel.style.display = 'block';
        editBtn.textContent = 'Fertig';
        renderAvailablePages();
    } else {
        editPanel.style.display = 'none';
        editBtn.textContent = 'Bearbeiten';
    }
}

function renderAvailablePages() {
    const container = document.getElementById('available-pages');
    if (!container) return;

    const stored = localStorage.getItem('bach-favorites');
    const favorites = stored ? JSON.parse(stored) : DEFAULT_FAVORITES;

    container.innerHTML = ALL_PAGES.filter(p => !p.hidden).map(page => {
        const isFav = favorites.includes(page.href);
        const btnStyle = isFav
            ? 'background: var(--accent); color: white;'
            : 'background: var(--bg-card);';

        return `
            <button class="btn btn-secondary" style="${btnStyle}; padding: 0.4rem 0.8rem; font-size: 0.8rem;"
                    onclick="toggleFavorite('${page.href}')">
                ${isFav ? '★' : '☆'} ${escapeHtml(page.label)}
            </button>
        `;
    }).join('');
}

function toggleFavorite(href) {
    const stored = localStorage.getItem('bach-favorites');
    let favorites = stored ? JSON.parse(stored) : DEFAULT_FAVORITES;

    if (favorites.includes(href)) {
        favorites = favorites.filter(f => f !== href);
    } else {
        favorites.push(href);
    }

    localStorage.setItem('bach-favorites', JSON.stringify(favorites));
    renderFavorites(favorites);
    renderAvailablePages();
}

// ═══════════════════════════════════════════════════════════════
// EXPORT
// ═══════════════════════════════════════════════════════════════

window.runScan = runScan;
window.loadTasks = loadTasks;
window.loadDashboard = loadDashboard;
window.toggleFavoritesEdit = toggleFavoritesEdit;
window.sendHeadlessPrompt = sendHeadlessPrompt;
window.toggleFavorite = toggleFavorite;

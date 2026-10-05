/**
 * BACH Navigation v2.1
 * Zentrale Navigation mit Dropdown-Submenüs + Theme-System
 */

const THEME_KEY = 'bach-theme';
const CUSTOM_THEME_KEY = 'bach-theme-custom';
const AVAILABLE_THEMES = ['dark', 'light', 'warm', 'custom'];
const CUSTOM_THEME_PROPERTIES = [
    'bg_dark', 'bg_panel', 'bg_card', 'bg_elevated', 'accent',
    'accent_light', 'accent_blue', 'text', 'text_muted', 'border',
    'success', 'warning', 'error'
];

function normalizeTheme(theme) {
    const normalized = theme === 'colorful' ? 'custom' : theme;
    return AVAILABLE_THEMES.includes(normalized) ? normalized : 'dark';
}

function loadCustomTheme() {
    try {
        const custom = JSON.parse(localStorage.getItem(CUSTOM_THEME_KEY) || '{}');
        return custom && typeof custom === 'object' ? custom : {};
    } catch (_) {
        return {};
    }
}

function applyTheme(theme, custom = null) {
    const normalized = normalizeTheme(theme);
    const root = document.documentElement;
    if (normalized === 'dark') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', normalized);

    const palette = custom || loadCustomTheme();
    CUSTOM_THEME_PROPERTIES.forEach(key => {
        root.style.removeProperty(`--${key.replace(/_/g, '-')}`);
    });
    if (normalized !== 'custom') return normalized;
    Object.keys(palette).forEach(key => {
        if (/^[a-z_]+$/.test(key) && /^#[0-9a-fA-F]{6}$/.test(palette[key])) {
            root.style.setProperty(`--${key.replace(/_/g, '-')}`, palette[key]);
        }
    });
    return normalized;
}

(function() {
    applyTheme(localStorage.getItem(THEME_KEY) || 'dark');
})();

const BACH_VERSION = "3.13.0";

if (typeof escapeHtml === 'undefined') {
    window.escapeHtml = function(text) {
        if (text == null) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#x27;');
    };
}

const NAV_ITEMS = [
    { id: "dashboard", href: "/", label: "Dashboard", icon: "🎵" },
    { id: "tasks", label: "Aufgaben", icon: "📋", children: [
        { href: "/tasks", label: "Aufgaben & Taskboard", icon: "📝", description: "Zentrales Aufgabenboard mit Status & Filtern" },
        { href: "/routinen?tab=bach", label: "Bachroutinen", icon: "🎼", description: "Automatisierte System- & Wartungsroutinen" },
        { href: "/routinen?tab=ocean", label: "Oceanroutinen", icon: "🌊", description: "Verteilte Schwarm- & Hintergrundzyklen" },
    ]},
    { id: "assistant", label: "Persönlicher Assistent", shortLabel: "Assistent", icon: "🧘", children: [
        { href: "/persoenlich", label: "Assistenten-Dashboard", icon: "📊", description: "Status, Haltung und Fokus von Buddha" },
        { href: "/chat", label: "Buddha Chat (Compare-Race)", icon: "💬", description: "Multi-Modell Dialog & Race-Evaluation" },
        { href: "/prompt-library", label: "Profil & Prompts", icon: "📚", description: "Systemprompts & Persönlichkeitsprofile" },
        { href: "/denkarium", label: "Denkarium", icon: "🔮", description: "Externes Gedankenlabor (neuer Tab)", external: true },
        { href: "/kontakte", label: "Kontakte", icon: "👥", description: "Adressbuch & Netzwerk" },
        { href: "/wiki", label: "Wiki", icon: "📖", description: "Persönliche Wissensbasis" },
    ]},
    { id: "life", label: "Life", icon: "🌱", children: [
        { href: "/life", label: "Life-Zentrale", icon: "🌿", description: "Ganzheitliche Lebensübersicht" },
        { href: "/life?tab=kalender", label: "Kalender (3 Ansichten)", icon: "📅", description: "Termine, Routinen und Fälligkeiten" },
        { href: "/life?tab=routinen", label: "Lebens-Routinen", icon: "⏰", description: "Tägliche und wöchentliche Gewohnheiten" },
        { href: "/tasks?assigned_to=user", label: "Meine Aufgaben", icon: "👤", description: "Gefiltert auf persönliche Aufgaben" },
        { href: "/life?tab=selbstmanagement", label: "Selbstmanagement & ADHS", icon: "🎯", description: "Fokusstrategien und Entlastungsmethoden" },
        { href: "/financial", label: "Finanzen & Budget", icon: "💰", description: "Einnahmen, Ausgaben und Prognosen" },
        { href: "/life?tab=balance", label: "Lebenskreise & Reflexion", icon: "☯️", description: "Work-Life-Balance & Selbsteinschätzung" },
        { href: "/gesundheit", label: "Gesundheit & Vitalität", icon: "🩺", description: "Tracking, Wohlbefinden und Pläne" },
    ]},
    { id: "agenten", label: "Agenten", icon: "🤖", children: [
        { href: "/agenten/fabrika", label: "Agenten-Fabrik", icon: "🏭", description: "Baukasten: Einzelagenten, Swarm & Ketten" },
        { href: "/agenten/running", label: "Living & Running", icon: "⚡", description: "Aktive Instanzen, Beseelungen & Health" },
        { href: "/agenten/sessions", label: "Sessions & Protokolle", icon: "📜", description: "Rohberichte und Zusammenfassungen" },
        { href: "/messages", label: "Messages (User Inbox)", icon: "✉️", description: "Direktnachrichten von Agenten an dich" },
        { href: "/agents-board", label: "Agents-Board (Skill-Katalog)", icon: "📊", description: "Aufgabenzuweisung & 388+ Skills" },
        { href: "/skills", label: "Skill- & Tool-Center", icon: "🔌", description: "Steckdosenleiste, MCP Cookbooks & Rollback" },
        { href: "/memory", label: "Memory", icon: "🧠", description: "Kognitiver Schaltplan, Arbeitsgedächtnis & Fakten" },
    ]},
    { id: "domains", label: "Meine Domänen", shortLabel: "Domänen", icon: "🌐", children: [
        { href: "/domains", label: "Domänen & Fachmodule", icon: "🧩", description: "Slot-Dashboard: AI-Media, PC-Tools" },
        { href: "/financial", label: "Finanzen", icon: "💰", description: "Budget & Finanzplanung" },
        { href: "/ati", label: "ATI Entwickler", icon: "🛠️", description: "Code-Entwicklung & Entwickler-Tasks" },
        { href: "/steuer", label: "Theodor Steuer", icon: "⚖️", description: "Steuer-Assistent, Belege & Abschreibungen" },
        { href: "/gesundheit", label: "Förderplaner & Diagnostik", icon: "🩺", description: "Pädagogische & therapeutische Pläne" },
    ]},
    { id: "files", label: "Dateien", icon: "📁", children: [
        { href: "/inbox", label: "Inbox & Dateiverwaltung", icon: "📥", description: "Upload, Sync & Cloud-Speicher" },
        { href: "/artefakte", label: "Artefakte & Exporte", icon: "🎨", description: "Generierte Berichte, Diagramme & Mockups" },
    ]},
    { id: "governance", label: "Governance & Control", shortLabel: "Governance", icon: "🛡️", children: [
        { href: "/governance", label: "Governance CONTROL Room", icon: "🏛️", description: "Zentrale Sicherheitsregeln & Audit" },
        { href: "/governance?tab=locks", label: "Lock-Master & Decision-Clicker", icon: "🔒", description: "Fail-Closed Sperren & P-001 Prüfungen" },
        { href: "/governance/funk", label: "Agentenfunk", icon: "📻", description: "Inter-Agenten-Signale & Handshakes" },
        { href: "/governance/usecases", label: "Use Cases & Workflows", icon: "🎯", description: "Definierte Einsatzszenarien & Pfade" },
        { href: "/governance/logs", label: "Logs & Audit", icon: "📜", description: "Echtzeit-Streams aller System-Events" },
        { href: "/help", label: "Hilfe & Dokumentation", icon: "❓", description: "Handbücher, Architektur-Guides & Shortcuts" },
    ]},
    { id: "system", label: "System", icon: "⚙️", children: [
        { href: "/settings", label: "Einstellungen & Setup", icon: "🔧", description: "Installer, Modulschaltplan, Trithon, Salt" },
        { href: "/tools", label: "Tools & CLI-Werkzeuge", icon: "🔨", description: "Ausführbare Helfer & Diagnose-Tools" },
        { href: "/daemon", label: "Daemon & Chains", icon: "⛓️", description: "Hintergrund-Dienste & Trigger" },
        { href: "/system?tab=ocean", label: "Ocean-Ausbaustufen", icon: "🌊", description: "Stufenplan & Cluster-Status" },
        { href: "/maintenance", label: "Wartung & Integrität", icon: "🩺", description: "Datenbank-Bereinigung & Healthchecks" },
    ]},
];

function initNavigation() {
    const header = document.getElementById('main-header');
    if (!header) return;

    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('embedded') === '1') {
        header.style.display = 'none';
        return;
    }

    const currentPath = window.location.pathname;

    function isActive(href) {
        if (!href || href === '#') return false;
        const currentUrl = window.location.pathname + window.location.search;
        if (href.includes('?')) {
            return currentUrl === href || currentUrl.startsWith(href + '&');
        }
        return currentPath === href || currentPath === href + '/' ||
            (href !== '/' && currentPath.startsWith(href)) ||
            (href === '/reports' && currentPath.startsWith('/messages'));
    }

    function hasActiveChild(item) {
        return item.children && item.children.some(c => isActive(c.href));
    }

    const navHtml = NAV_ITEMS.map(item => {
        const iconHtml = item.icon ? `<span class="nav-icon">${item.icon}</span>` : '';
        const fullLabel = item.label;
        const shortLabel = item.shortLabel || item.label;
        const labelHtml = item.shortLabel
            ? `<span class="nav-label"><span class="nav-label-full">${escapeHtml(fullLabel)}</span><span class="nav-label-short">${escapeHtml(shortLabel)}</span></span>`
            : `<span class="nav-label">${escapeHtml(fullLabel)}</span>`;

        if (item.children) {
            const parentActive = hasActiveChild(item) ? ' active' : '';
            const childHtml = item.children.map(child => {
                const childActive = isActive(child.href) ? ' active' : '';
                const target = child.external || child.target === '_blank' ? ' target="_blank" rel="noopener noreferrer"' : '';
                let href = child.href;
                if (child.portRel) {
                    const host = window.location.hostname || 'localhost';
                    href = `http://${host}:${child.portRel}${child.path || ''}`;
                }
                const childIcon = child.icon ? `<span class="dropdown-item-icon">${child.icon}</span>` : '';
                const descHtml = child.description ? `<div class="dropdown-item-desc">${escapeHtml(child.description)}</div>` : '';
                return `<a href="${href}"${target} class="dropdown-item${childActive}">
                    ${childIcon}
                    <div class="dropdown-item-text">
                        <div class="dropdown-item-title">${escapeHtml(child.label)}</div>
                        ${descHtml}
                    </div>
                </a>`;
            }).join('');
            return `<div class="nav-dropdown${parentActive}">
                <button class="nav-item nav-dropdown-toggle${parentActive}" type="button">
                    ${iconHtml}${labelHtml} <span class="dropdown-arrow">▾</span>
                </button>
                <div class="dropdown-menu">${childHtml}</div>
            </div>`;
        }
        const active = isActive(item.href) ? ' active' : '';
        const target = item.external || item.target === '_blank' ? ' target="_blank" rel="noopener noreferrer"' : '';
        let itemHref = item.href;
        if (item.portRel) {
            const host = window.location.hostname || 'localhost';
            itemHref = `http://${host}:${item.portRel}${item.path || ''}`;
        }
        return `<a href="${itemHref}"${target} class="nav-item${active}">${iconHtml}${labelHtml}</a>`;
    }).join('\n            ');

    const currentTheme = normalizeTheme(localStorage.getItem(THEME_KEY) || 'dark');

    header.innerHTML = `
        <div class="header-left">
            <a href="/" class="logo" style="text-decoration:none;">
                <span class="logo-icon">🎵</span>
                <span class="logo-text">BACH <span style="font-size:0.75rem;opacity:0.6;font-weight:normal;">v${BACH_VERSION}</span></span>
            </a>
            <nav class="main-nav" aria-label="Hauptnavigation">
                ${navHtml}
            </nav>
        </div>
        <div class="header-right" style="display:flex;align-items:center;gap:0.75rem;">
            <div class="quick-nav-actions" style="display:flex;align-items:center;gap:0.35rem;">
                <a href="/life?tab=kalender" class="quick-action-btn" title="Kalender (Termine, Routinen & Aufgaben)" aria-label="Kalender">📅</a>
                <a href="/kontakte" class="quick-action-btn" title="Kontakte & Netzwerk" aria-label="Kontakte">👥</a>
            </div>
            <div class="theme-switcher" id="theme-switcher">
                <button class="theme-btn${currentTheme === 'dark' ? ' active' : ''}" data-theme="dark" title="Dark">🌙</button>
                <button class="theme-btn${currentTheme === 'light' ? ' active' : ''}" data-theme="light" title="Light">☀️</button>
                <button class="theme-btn${currentTheme === 'warm' ? ' active' : ''}" data-theme="warm" title="Warm">🕯️</button>
                <button class="theme-btn${currentTheme === 'custom' ? ' active' : ''}" data-theme="custom" title="Custom">🎨</button>
            </div>
            <div class="header-status">
                <span class="status-dot" id="status-dot"></span>
                <span id="status-text">-</span>
            </div>
        </div>
    `;

    document.querySelectorAll('.nav-dropdown').forEach(dd => {
        let closeTimer = null;
        dd.addEventListener('mouseenter', () => {
            if (closeTimer) {
                clearTimeout(closeTimer);
                closeTimer = null;
            }
            dd.classList.add('open');
        });
        dd.addEventListener('mouseleave', () => {
            closeTimer = setTimeout(() => {
                dd.classList.remove('open');
            }, 250);
        });
        dd.querySelector('.nav-dropdown-toggle').addEventListener('click', (e) => {
            e.preventDefault();
            if (closeTimer) {
                clearTimeout(closeTimer);
                closeTimer = null;
            }
            dd.classList.toggle('open');
        });
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.nav-dropdown')) {
            document.querySelectorAll('.nav-dropdown.open').forEach(d => d.classList.remove('open'));
        }
    });

    document.getElementById('theme-switcher').addEventListener('click', async (e) => {
        const btn = e.target.closest('.theme-btn');
        if (!btn) return;
        const theme = btn.dataset.theme;
        btn.disabled = true;
        await persistThemePreference(theme);
        btn.disabled = false;
    });
}

async function saveThemePreference(theme, custom) {
    try {
        const response = await fetch('/api/settings/theme', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme, custom: custom || undefined })
        });
        return response.ok;
    } catch (_) {
        return false;
    }
}

function updateThemeButtons(theme) {
    document.querySelectorAll('.theme-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.theme === theme);
    });
}

function previewTheme(theme, custom = null) {
    const normalized = applyTheme(theme, custom);
    updateThemeButtons(normalized);
    return normalized;
}

function commitTheme(theme, custom = null) {
    const normalized = previewTheme(theme, custom);
    localStorage.setItem(THEME_KEY, normalized);
    if (custom && typeof custom === 'object') {
        localStorage.setItem(CUSTOM_THEME_KEY, JSON.stringify(custom));
    }
    return normalized;
}

async function persistThemePreference(theme, custom = null) {
    const previousTheme = normalizeTheme(localStorage.getItem(THEME_KEY) || 'dark');
    const previousCustom = loadCustomTheme();
    const normalized = normalizeTheme(theme);
    const nextCustom = custom || loadCustomTheme();
    previewTheme(normalized, nextCustom);
    if (await saveThemePreference(normalized, nextCustom)) {
        commitTheme(normalized, nextCustom);
        return true;
    }
    previewTheme(previousTheme, previousCustom);
    return false;
}

// Backward-compatible local commit for pages importing the previous helper.
function setTheme(theme, custom = null) {
    return commitTheme(theme, custom);
}

async function loadThemePreference() {
    try {
        const response = await fetch('/api/settings/theme');
        if (!response.ok) return null;
        const data = await response.json();
        if (!data.success) return null;
        if (!data.configured) return data;
        commitTheme(data.theme, data.custom);
        return data;
    } catch (_) {
        return null;
    }
}

function updateNavStatus(online, text) {
    const dot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    if (dot) {
        dot.classList.remove('online', 'offline');
        dot.classList.add(online ? 'online' : 'offline');
    }
    if (statusText) {
        statusText.textContent = text;
    }
}

async function loadNavStatus() {
    try {
        const response = await fetch('/api/status');
        if (!response.ok) throw new Error('Server nicht erreichbar');
        const data = await response.json();
        updateNavStatus(true, 'Online');
        return data;
    } catch (e) {
        updateNavStatus(false, 'Offline');
        return null;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    loadThemePreference();
    loadNavStatus();
});

if (typeof module !== 'undefined') {
    module.exports = {
        initNavigation, updateNavStatus, loadNavStatus, setTheme, previewTheme,
        commitTheme, persistThemePreference,
        loadThemePreference, normalizeTheme, NAV_ITEMS, BACH_VERSION
    };
}

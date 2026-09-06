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
    { href: "/", label: "Dashboard" },
    { label: "Aufgaben", children: [
        { href: "/tasks-board", label: "Tasks" },
        { href: "/routinen", label: "Routinen" },
    ]},
    { label: "Agenten", children: [
        { href: "/agents", label: "Agenten" },
        { href: "/partners", label: "Partner" },
        { href: "/skills-board", label: "Skills" },
    ]},
    { label: "Wissen", children: [
        { href: "/memory", label: "Memory" },
        { href: "/prompt-library", label: "Prompts" },
        { href: "/denkarium", label: "Denkarium" },
        { href: "/wiki", label: "Wiki" },
        { href: "/usecases", label: "Use Cases" },
    ]},
    { label: "Kommunikation", children: [
        { href: "/messages", label: "Nachrichten" },
        { href: "/inbox", label: "Inbox" },
        { href: "/kontakte", label: "Kontakte" },
    ]},
    { label: "Finanzen", children: [
        { href: "/financial", label: "Finanzen" },
        { href: "/tokens", label: "Tokens" },
    ]},
    { href: "/tools", label: "Tools" },
    { label: "System", children: [
        { href: "/settings", label: "Einstellungen" },
        { href: "/daemon", label: "Automation" },
        { href: "/control/", label: "Unified GUI" },
        { href: "/maintenance", label: "Wartung" },
        { href: "/logs", label: "Logs" },
        { href: "/help", label: "Help" },
    ]},
    { href: "/chat", label: "Buddha Chat" },
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
        return currentPath === href || currentPath === href + '/' ||
            (href !== '/' && currentPath.startsWith(href));
    }

    function hasActiveChild(item) {
        return item.children && item.children.some(c => isActive(c.href));
    }

    const navHtml = NAV_ITEMS.map(item => {
        if (item.children) {
            const parentActive = hasActiveChild(item) ? ' active' : '';
            const childHtml = item.children.map(child => {
                const childActive = isActive(child.href) ? ' active' : '';
                return `<a href="${child.href}" class="dropdown-item${childActive}">${child.label}</a>`;
            }).join('');
            return `<div class="nav-dropdown${parentActive}">
                <button class="nav-item nav-dropdown-toggle${parentActive}">${item.label} <span class="dropdown-arrow">▾</span></button>
                <div class="dropdown-menu">${childHtml}</div>
            </div>`;
        }
        const active = isActive(item.href) ? ' active' : '';
        const target = item.external ? ' target="_blank"' : '';
        return `<a href="${item.href}"${target} class="nav-item${active}">${item.label}</a>`;
    }).join('\n            ');

    const currentTheme = normalizeTheme(localStorage.getItem(THEME_KEY) || 'dark');

    header.innerHTML = `
        <div class="logo">
            <span class="logo-icon">🎵</span>
            <span class="logo-text">BACH v${BACH_VERSION}</span>
        </div>
        <nav class="main-nav">
            ${navHtml}
        </nav>
        <div style="display:flex;align-items:center;">
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
        dd.addEventListener('mouseenter', () => dd.classList.add('open'));
        dd.addEventListener('mouseleave', () => dd.classList.remove('open'));
        dd.querySelector('.nav-dropdown-toggle').addEventListener('click', (e) => {
            e.preventDefault();
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

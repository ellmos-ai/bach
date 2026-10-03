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

let NAV_ITEMS = [{ id: 'dashboard', href: '/', label: 'Dashboard', icon: '🎵' }];
let navigationState = 'loading';
let navClickBound = false;

function safeNavHref(href) {
    return typeof href === 'string' && href.startsWith('/') && !href.startsWith('//') ? href : '/';
}

async function loadNavigationConfig() {
    try {
        const response = await fetch('/api/nav/config');
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const items = await response.json();
        if (!Array.isArray(items) || items.length === 0 ||
            items.some(item => !item || typeof item.label !== 'string' ||
                !(typeof item.href === 'string' || Array.isArray(item.children)))) {
            throw new Error('Ungültige Navigation');
        }
        NAV_ITEMS = items;
        navigationState = 'ready';
    } catch (error) {
        NAV_ITEMS = [{ id: 'dashboard', href: '/', label: 'Dashboard', icon: '🎵' }];
        navigationState = 'error';
    }
    initNavigation();
}

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
        const iconHtml = item.icon ? `<span class="nav-icon">${escapeHtml(item.icon)}</span>` : '';
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
                let href = safeNavHref(child.href);
                if (child.portRel) {
                    const host = window.location.hostname || 'localhost';
                    if (Number.isInteger(child.portRel) && child.portRel > 0 && child.portRel < 65536) {
                        href = `http://${host}:${child.portRel}${safeNavHref(child.path || '/')}`;
                    }
                }
                const childIcon = child.icon ? `<span class="dropdown-item-icon">${escapeHtml(child.icon)}</span>` : '';
                const descHtml = child.description ? `<div class="dropdown-item-desc">${escapeHtml(child.description)}</div>` : '';
                return `<a href="${escapeHtml(href)}"${target} class="dropdown-item${childActive}">
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
        let itemHref = safeNavHref(item.href);
        if (item.portRel) {
            const host = window.location.hostname || 'localhost';
            if (Number.isInteger(item.portRel) && item.portRel > 0 && item.portRel < 65536) {
                itemHref = `http://${host}:${item.portRel}${safeNavHref(item.path || '/')}`;
            }
        }
        return `<a href="${escapeHtml(itemHref)}"${target} class="nav-item${active}">${iconHtml}${labelHtml}</a>`;
    }).join('\n            ');
    const navNotice = navigationState === 'ready' ? '' :
        `<span class="nav-item" role="status" style="cursor:default;">${navigationState === 'loading' ? 'Navigation lädt…' : 'Menü derzeit nicht verfügbar'}</span>`;

    const currentTheme = normalizeTheme(localStorage.getItem(THEME_KEY) || 'dark');

    header.innerHTML = `
        <div class="header-left">
            <a href="/" class="logo" style="text-decoration:none;">
                <span class="logo-icon">🎵</span>
                <span class="logo-text">BACH <span style="font-size:0.75rem;opacity:0.6;font-weight:normal;">v${BACH_VERSION}</span></span>
            </a>
            <nav class="main-nav" aria-label="Hauptnavigation">
                ${navNotice}
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

    if (!navClickBound) {
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.nav-dropdown')) {
                document.querySelectorAll('.nav-dropdown.open').forEach(d => d.classList.remove('open'));
            }
        });
        navClickBound = true;
    }

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
    loadNavigationConfig();
    loadThemePreference();
    loadNavStatus();
});

if (typeof module !== 'undefined') {
    module.exports = {
        initNavigation, updateNavStatus, loadNavStatus, setTheme, previewTheme,
        commitTheme, persistThemePreference,
        loadThemePreference, normalizeTheme, loadNavigationConfig, BACH_VERSION
    };
}

/**
 * BACH Navigation v1.0
 * Zentrale Navigation fuer alle GUI-Seiten
 *
 * Verwendung: Im Template einfach header mit id="main-header" einbinden
 * und dieses Script am Ende laden
 */

const BACH_VERSION = "3.9.1";

if (typeof escapeHtml === 'undefined') {
    window.escapeHtml = function(text) {
        if (text == null) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    };
}

const CHAT_HOST = (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
    ? "macstudvonlukas" : window.location.hostname;

const NAV_ITEMS = [
    { href: "/", label: "Dashboard", icon: null },
    { href: "/tasks-board", label: "Tasks", icon: null },
    { href: "/agents", label: "Agenten", icon: null },
    { href: "/skills-board", label: "Skills", icon: null },
    { href: "/memory", label: "Memory", icon: null },
    { href: "/denkarium", label: "Denkarium", icon: null },
    { href: "/tools", label: "Tools", icon: null },
    { href: "/kontakte", label: "Kontakte", icon: null },
    { href: "/financial", label: "Finanzen", icon: null },
    { href: "/routinen", label: "Routinen", icon: null },
    { href: "/messages", label: "Nachrichten", icon: null },
    { href: "/inbox", label: "Inbox", icon: null },
    { href: "/wiki", label: "Wiki", icon: null },
    { href: "/partners", label: "Partner", icon: null },
    { href: "/usecases", label: "Use Cases", icon: null },
    { href: "/tokens", label: "Tokens", icon: null },
    { href: `http://${CHAT_HOST}:8081`, label: "Buddha Chat", icon: null, external: true },
    { href: "/maintenance", label: "Wartung", icon: null },
    { href: "/logs", label: "Logs", icon: null },
    { href: "/help", label: "Help", icon: null },
];

/**
 * Initialisiert die Navigation
 */
function initNavigation() {
    const header = document.getElementById('main-header');
    if (!header) return;

    // Check for embedded mode (Task #616)
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('embedded') === '1') {
        header.style.display = 'none';
        return;
    }

    const currentPath = window.location.pathname;

    // Navigation HTML erstellen
    const navHtml = NAV_ITEMS.map(item => {
        const isActive = (currentPath === item.href) ||
            (currentPath === item.href + '/') ||
            (item.href !== '/' && currentPath.startsWith(item.href));
        const activeClass = isActive ? 'active' : '';
        const icon = item.icon ? `<span class="nav-icon">${item.icon}</span>` : '';
        const target = item.external ? ' target="_blank"' : '';
        return `<a href="${item.href}"${target} class="nav-item ${activeClass}">${icon}${item.label}</a>`;
    }).join('\n            ');

    header.innerHTML = `
        <div class="logo">
            <span class="logo-icon">🎵</span>
            <span class="logo-text">BACH v${BACH_VERSION}</span>
        </div>
        <nav class="main-nav">
            ${navHtml}
        </nav>
        <div class="header-status">
            <span class="status-dot" id="status-dot"></span>
            <span id="status-text">-</span>
        </div>
    `;

}

/**
 * Aktualisiert den Status in der Navigation
 */
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

/**
 * Laedt den Status vom Server und aktualisiert die Anzeige
 */
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

// Automatisch initialisieren wenn DOM geladen
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    loadNavStatus();
});

// Export fuer Module
if (typeof module !== 'undefined') {
    module.exports = { initNavigation, updateNavStatus, loadNavStatus, NAV_ITEMS, BACH_VERSION };
}

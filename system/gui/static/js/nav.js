/**
 * BACH Navigation v1.0
 * Zentrale Navigation fuer alle GUI-Seiten
 *
 * Verwendung: Im Template einfach header mit id="main-header" einbinden
 * und dieses Script am Ende laden
 */

const BACH_VERSION = "1.1.8";

const NAV_ITEMS = [
    { href: "/", label: "Dashboard", icon: null },
    { href: "/tasks-board", label: "Tasks-Board", icon: "📋" },
    { href: "/agents", label: "Agenten", icon: null },
    { href: "/partners", label: "Partner", icon: null },
    { href: "/skills-board", label: "Skills", icon: null },
    // Financial entfernt - jetzt ueber Agenten-Dashboard erreichbar (Task #511)
    // Tokens+Dateien entfernt - jetzt als Tabs auf Dashboard (Task #554)
    { href: "/memory", label: "Memory", icon: null },
    { href: "/tools", label: "Tools", icon: null },
    { href: "/messages", label: "Messages", icon: null },
    { href: "/maintenance", label: "Wartung", icon: "🛠️" },
    { href: "/help", label: "Help", icon: null },

    { href: "/wiki", label: "Wiki", icon: null }
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
        return `<a href="${item.href}" class="nav-item ${activeClass}">${icon}${item.label}</a>`;
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
 * Oeffnet den Prompt-Manager direkt (ohne Navigation)
 */
function openPromptManager() {
    fetch('/api/prompt-generator/start-desktop', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                console.log('Prompt-Manager gestartet');
            } else {
                alert('Fehler: ' + (data.error || 'Unbekannt'));
            }
        })
        .catch(err => {
            console.error('Fehler beim Starten des Prompt-Managers:', err);
            alert('Prompt-Manager konnte nicht gestartet werden');
        });
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

/**
 * BACH API Client
 * Wrapper fuer API-Aufrufe
 */

const API = {
    baseUrl: (typeof window !== 'undefined' && window.BOARD_CONFIG && window.BOARD_CONFIG.apiBase != null) ? window.BOARD_CONFIG.apiBase : '',

    _headers(extra = {}) {
        const headers = { ...extra };
        if (typeof window !== 'undefined' && window.BOARD_CONFIG) {
            const token = window.BOARD_CONFIG.token ||
                (window.BOARD_CONFIG.tokenStorageKey && localStorage.getItem(window.BOARD_CONFIG.tokenStorageKey));
            if (token) {
                headers['Authorization'] = 'Bearer ' + token;
            }
        }
        if (!headers['Authorization']) {
            Object.assign(headers, this.deviceHeaders());
        }
        return headers;
    },

    deviceHeaders() {
        // Browser device authentication is carried by the server-managed
        // HttpOnly cookie.  BOARD_CONFIG tokens are separate, explicit
        // integrations and remain handled by _headers above.
        return {};
    },

    async get(endpoint) {
        try {
            const response = await fetch(this.baseUrl + endpoint, {
                headers: this._headers()
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error('API GET Error:', error);
            throw error;
        }
    },

    // Liest alle Seiten eines paginierten Listenendpunkts (limit/offset/has_more, wie /api/tasks).
    // count ist die Zahl eindeutiger zurückgegebener Zeilen; total stammt von der letzten Serverseite.
    // offset bleibt der Startoffset (hier 0). Änderungen während des Ladens können Seiten verschieben:
    // die Liste wird live seitenweise gelesen und ist kein atomarer Snapshot.
    async getAllPages(endpoint, key = 'tasks', pageSize = 100, maxPages = 1000) {
        const merged = { success: true, count: 0, total: 0, has_more: false, offset: 0 };
        merged[key] = [];
        const seen = new Set();
        let offset = 0;
        for (let page = 0; page < maxPages; page++) {
            const sep = endpoint.includes('?') ? '&' : '?';
            const pageUrl = endpoint + sep + 'limit=' + pageSize + '&offset=' + offset;
            let data;
            try {
                data = await this.get(pageUrl);
            } catch (error) {
                const detail = error && error.message ? error.message : String(error);
                throw new Error('Task-Liste konnte nicht vollständig geladen werden: ' + detail);
            }
            if (!data || data.success !== true) {
                const detail = data && typeof data.error === 'string' ? data.error.trim() : '';
                throw new Error('Task-Liste konnte nicht vollständig geladen werden' +
                    (detail ? ': ' + detail : ': Ungültige Antwort vom Server.'));
            }

            if (!Array.isArray(data[key])) {
                throw new Error('Task-Liste unvollständig: Der Server lieferte keine gültige Aufgabenliste.');
            }
            if (typeof data.has_more !== 'boolean') {
                throw new Error('Task-Liste unvollständig: Der Server lieferte keinen gültigen has_more-Wert.');
            }
            const rows = data[key];
            if (data.has_more === true && rows.length === 0) {
                throw new Error('Task-Liste unvollständig: Der Server meldet ab Offset ' +
                    offset + ' weitere Seiten, liefert aber keine Einträge.');
            }
            for (const row of rows) {
                if (row && row.id !== undefined && row.id !== null) {
                    if (seen.has(row.id)) continue;
                    seen.add(row.id);
                }
                merged[key].push(row);
            }
            merged.total = typeof data.total === 'number' ? data.total : merged[key].length;
            if (data.applied_filters !== undefined) merged.applied_filters = data.applied_filters;
            merged.count = merged[key].length;
            if (data.has_more !== true) return merged;

            // Advance by raw rows from the server, including duplicate IDs filtered above.
            offset += rows.length;
        }
        throw new Error('Task-Liste unvollständig: Nach ' + maxPages +
            ' Seiten meldet der Server weitere Ergebnisse.');
    },
    async post(endpoint, data = {}) {
        try {
            const response = await fetch(this.baseUrl + endpoint, {
                method: 'POST',
                headers: this._headers({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(data)
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error('API POST Error:', error);
            throw error;
        }
    },

    async put(endpoint, data = {}) {
        try {
            const response = await fetch(this.baseUrl + endpoint, {
                method: 'PUT',
                headers: this._headers({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(data)
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error('API PUT Error:', error);
            throw error;
        }
    },

    async delete(endpoint) {
        try {
            const response = await fetch(this.baseUrl + endpoint, {
                method: 'DELETE',
                headers: this._headers()
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error('API DELETE Error:', error);
            throw error;
        }
    },

    // Spezifische Endpoints
    status: () => API.get('/api/status'),

    tasks: {
        list: (status) => API.getAllPages('/api/tasks' + (status ? `?status=${status}` : '')),
        summary: async (status = 'all') => {
            const data = await API.get('/api/tasks?status=' +
                encodeURIComponent(status || 'all') + '&limit=0');
            if (!data || data.success !== true) {
                const detail = data && typeof data.error === 'string' ? data.error.trim() : '';
                throw new Error('Task-Statistik konnte nicht geladen werden' +
                    (detail ? ': ' + detail : ': Ungültige Antwort vom Server.'));
            }
            if (!Number.isInteger(data.total) || data.total < 0) {
                throw new Error('Task-Statistik konnte nicht geladen werden: Ungültige Gesamtzahl.');
            }
            return data;
        },
        get: (id) => API.get(`/api/tasks/${id}`),
        create: (data) => API.post('/api/tasks', data),
        update: (id, data) => API.put(`/api/tasks/${id}`, data),
        delete: (id) => API.delete(`/api/tasks/${id}`)
    },

    scannedTasks: {
        list: (tool, status) => {
            let params = [];
            if (tool) params.push(`tool=${encodeURIComponent(tool)}`);
            if (status) params.push(`status=${status}`);
            return API.get('/api/scanned-tasks' + (params.length ? '?' + params.join('&') : ''));
        }
    },

    messages: {
        list: (direction, status) => {
            let params = [];
            if (direction) params.push(`direction=${direction}`);
            if (status) params.push(`status=${status}`);
            return API.get('/api/messages' + (params.length ? '?' + params.join('&') : ''));
        },
        create: (data) => API.post('/api/messages', data),
        markRead: (id) => API.put(`/api/messages/${id}/read`)
    },

    daemon: {
        jobs: () => API.get('/api/daemon/jobs'),
        createJob: (data) => API.post('/api/daemon/jobs', data),
        toggleJob: (id) => API.put(`/api/daemon/jobs/${id}/toggle`),
        runs: (jobId) => API.get('/api/daemon/runs' + (jobId ? `?job_id=${jobId}` : ''))
    },

    scanner: {
        run: () => API.post('/api/scanner/run'),
        status: () => API.get('/api/scanner/status'),
        tools: () => API.get('/api/scanner/tools'),
        config: () => API.get('/api/scanner/config')
    },

    agents: {
        list: () => API.get('/api/agents'),
        get: (id) => API.get(`/api/agents/${id}`),
        create: (data) => API.post('/api/agents', data),
        update: (id, data) => API.put(`/api/agents/${id}`, data),
        toggle: (id) => API.put(`/api/agents/${id}/toggle`),
        delete: (id) => API.delete(`/api/agents/${id}`)
    }
};


// Export fuer Module
if (typeof module !== 'undefined') {
    module.exports = API;
}

// Global aliases fuer einfache Verwendung (Browser)
window.API = API;
window.api = API;

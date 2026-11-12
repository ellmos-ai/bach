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

    // Liest ALLE Seiten eines paginierten Listenendpunkts (limit/offset/has_more, wie /api/tasks)
    // und liefert dieselbe Antwortform zurueck (Liste unter `key`, total, count, has_more=false).
    // Ein Fehler auf irgendeiner Seite wird unveraendert weitergereicht (kein stiller Teilerfolg);
    // Doppelte ids (parallele Aenderungen zwischen den Seiten) werden verworfen.
    // Der Server begrenzt jede Seite selbst (Standard 100); hier gibt es keine eigene Obergrenze
    // ausser `maxPages` als Schutz vor einer nie endenden has_more-Kette.
    async getAllPages(endpoint, key = 'tasks', pageSize = 100, maxPages = 1000) {
        const merged = { success: true, count: 0, total: 0, has_more: false, offset: 0 };
        merged[key] = [];
        const seen = new Set();
        let offset = 0;
        for (let page = 0; page < maxPages; page++) {
            const sep = endpoint.includes('?') ? '&' : '?';
            const data = await this.get(`${endpoint}${sep}limit=${pageSize}&offset=${offset}`);
            if (!data || data.success === false) return data;
            const rows = Array.isArray(data[key]) ? data[key] : [];
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
            if (data.has_more !== true || rows.length === 0) return merged;
            offset += rows.length;
        }
        merged.has_more = true; // maxPages erreicht: Rest ist nicht geladen
        return merged;
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

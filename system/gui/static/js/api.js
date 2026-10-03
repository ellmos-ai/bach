/**
 * BACH API Client
 * Wrapper fuer API-Aufrufe
 */

const API = {
    baseUrl: '',

    deviceHeaders() {
        const token = typeof localStorage === 'undefined' ? null : localStorage.getItem('bach_device_token');
        return token ? { Authorization: 'Bearer ' + token } : {};
    },

    async get(endpoint) {
        try {
            const response = await fetch(this.baseUrl + endpoint, { headers: this.deviceHeaders() });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            console.error('API GET Error:', error);
            throw error;
        }
    },

    async post(endpoint, data = {}) {
        try {
            const response = await fetch(this.baseUrl + endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...this.deviceHeaders() },
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
                headers: { 'Content-Type': 'application/json', ...this.deviceHeaders() },
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
                method: 'DELETE', headers: this.deviceHeaders()
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
        list: (status) => API.get('/api/tasks' + (status ? `?status=${status}` : '')),
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

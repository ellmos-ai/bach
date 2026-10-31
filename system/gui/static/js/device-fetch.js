/* Browser device credentials stay in the server-managed HttpOnly cookie. */
(() => {
    if (window.bachDeviceFetchInstalled) return;
    window.bachDeviceFetchInstalled = true;
    const originalFetch = window.fetch.bind(window);
    const isLoopbackHost = (h) => h === '127.0.0.1' || h === 'localhost' || h === '[::1]' || h === '::1';
    window.fetch = async (input, options = {}) => {
        const target = new URL(input instanceof Request ? input.url : input, location.href);
        if (target.origin !== location.origin || !target.pathname.startsWith('/api/')) {
            return originalFetch(input, options);
        }
        const headers = new Headers(options.headers ?? (input instanceof Request ? input.headers : undefined));
        let response = await originalFetch(input, {...options, headers});
        let manualLogout = false;
        try { manualLogout = typeof sessionStorage !== 'undefined' && sessionStorage.getItem('bach_manual_logout') === '1'; } catch (_) {}
        if (response.status === 401 && isLoopbackHost(target.hostname) && !window.__bachAutoSessionTried && !manualLogout && target.pathname !== '/api/devices/auto-session') {
            window.__bachAutoSessionTried = true;
            try {
                let preferredDeviceId = 'ASUS-GEI';
                try {
                    const storedId = typeof localStorage !== 'undefined' && localStorage.getItem('bach_device_id');
                    if (storedId) preferredDeviceId = storedId;
                } catch (_) {}
                const autoRes = await originalFetch('/api/devices/auto-session', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ device_id: preferredDeviceId }),
                });
                if (autoRes && autoRes.ok) {
                    response = await originalFetch(input, {...options, headers});
                }
            } catch (_) {}
        }
        if ((response.status === 401 || response.status === 403) &&
                document.body && !document.getElementById('bach-device-login-needed')) {
            const notice = document.createElement('p');
            notice.id = 'bach-device-login-needed';
            notice.setAttribute('role', 'alert');
            const link = document.createElement('a');
            link.href = '/token-dashboard';
            link.textContent = 'Geräteanmeldung prüfen';
            notice.append('Für diesen Zugriff ist eine gültige Geräteanmeldung erforderlich. ', link);
            document.body.prepend(notice);
        }
        return response;
    };
})();

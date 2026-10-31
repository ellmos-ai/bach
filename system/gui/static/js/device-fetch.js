/* Browser device credentials stay in the server-managed HttpOnly cookie. */
(() => {
    if (window.bachDeviceFetchInstalled) return;
    window.bachDeviceFetchInstalled = true;
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (input, options = {}) => {
        const target = new URL(input instanceof Request ? input.url : input, location.href);
        if (target.origin !== location.origin || !target.pathname.startsWith('/api/')) {
            return originalFetch(input, options);
        }
        const headers = new Headers(options.headers ?? (input instanceof Request ? input.headers : undefined));
        const response = await originalFetch(input, {...options, headers});
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

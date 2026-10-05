/**
 * device-auth.js — Geraetetoken-Anbindung des BACH-Frontends (#1456/#1500/#1501)
 *
 * Wird im <head> aller Templates eingebunden. AUSNAHME: device-tokens.html
 * bindet es NICHT ein (sonst Redirect-Loop bei 401).
 *
 * Patcht window.fetch global:
 *  - Same-Origin-Requests nach /api/* erhalten "Authorization: Bearer <token>"
 *    aus localStorage["bach_device_token"], sofern der Aufrufer selbst KEINEN
 *    Authorization-Header setzt (chat.html haengt sein Control-API-Token selbst
 *    an — ein vorhandener Header wird NIEMALS ueberschrieben).
 *  - 401 auf einem /api/-Request:
 *      * Wurde der Token von uns angehaengt -> Token aus localStorage loeschen
 *        (ungueltig oder gesperrt) und zu /device-tokens weiterleiten.
 *      * Kein Token im localStorage -> zu /device-tokens weiterleiten
 *        (Erst-Nutzung: Anmeldung noetig).
 *      * Authorization-Header vom Aufrufer -> unangetastet, die 401 behandelt
 *        die Seite selbst (z. B. abgelaufenes Control-Token: kein Loeschen
 *        des gueltigen Geraetetokens, kein Redirect).
 *    Loop-Schutz: kein Redirect, wenn bereits /device-tokens offen ist.
 *
 * Keine DOM-Abhaengigkeit — laeuft sofort nach dem Laden im <head>.
 */
(function () {
    "use strict";

    var STORAGE_KEY = "bach_device_token";
    var LOGIN_PATH = "/device-tokens";

    if (typeof window.fetch !== "function") {
        return; // sehr alter Browser: fetch unveraendert lassen
    }
    var originalFetch = window.fetch.bind(window);

    function readToken() {
        try {
            return window.localStorage.getItem(STORAGE_KEY) || "";
        } catch (e) {
            return ""; // localStorage blockiert (z. B. Privacy-Modus)
        }
    }

    function redirectToLogin() {
        var path = window.location.pathname;
        if (path === LOGIN_PATH || path === LOGIN_PATH + "/") {
            return; // Loop-Schutz
        }
        window.location.assign(LOGIN_PATH);
    }

    function watch(promise, tokenAttachedByUs) {
        return promise.then(function (response) {
            if (response && response.status === 401) {
                if (tokenAttachedByUs) {
                    try {
                        window.localStorage.removeItem(STORAGE_KEY);
                    } catch (e) { /* localStorage blockiert */ }
                }
                redirectToLogin();
            }
            return response;
        }, function (error) {
            throw error; // Netzwerkfehler durchreichen
        });
    }

    function requestUrl(input) {
        if (typeof input === "string") {
            return input;
        }
        if (input && typeof input.url === "string") {
            return input.url; // fetch(new Request(...))
        }
        return "";
    }

    function isSameOriginApiPath(url) {
        try {
            var parsed = new URL(url, window.location.href);
            if (parsed.origin !== window.location.origin) {
                return false; // fremde Herkunft nie anfassen
            }
            return parsed.pathname.indexOf("/api/") === 0;
        } catch (e) {
            return false;
        }
    }

    function headersHaveAuthorization(headers) {
        if (!headers) {
            return false;
        }
        if (typeof Headers !== "undefined" && headers instanceof Headers) {
            return headers.has("Authorization");
        }
        if (Array.isArray(headers)) {
            for (var i = 0; i < headers.length; i++) {
                if (headers[i] && String(headers[i][0]).toLowerCase() === "authorization") {
                    return true;
                }
            }
            return false;
        }
        if (typeof headers === "object") {
            for (var key in headers) {
                if (Object.prototype.hasOwnProperty.call(headers, key) &&
                        String(key).toLowerCase() === "authorization") {
                    return true;
                }
            }
        }
        return false;
    }

    function callerHasAuthorization(input, init) {
        if (init && headersHaveAuthorization(init.headers)) {
            return true;
        }
        if (typeof Request !== "undefined" && input instanceof Request) {
            return headersHaveAuthorization(input.headers);
        }
        return false;
    }

    window.fetch = function (input, init) {
        if (!isSameOriginApiPath(requestUrl(input))) {
            return originalFetch(input, init); // kein /api/-Pfad oder fremde Herkunft
        }

        if (callerHasAuthorization(input, init)) {
            // Vorhandene Authorization NIEMALS ueberschreiben (Control-API-Token!).
            // Auch bei 401 nicht eingreifen: Das ist Sache des Aufrufers.
            return originalFetch(input, init);
        }

        var token = readToken();
        if (!token) {
            // Erst-Nutzung ohne Geraetetoken: bei 401 zur Anmeldung leiten
            return watch(originalFetch(input, init), false);
        }

        try {
            if (typeof Request !== "undefined" && input instanceof Request) {
                var requestHeaders = new Headers(input.headers);
                requestHeaders.set("Authorization", "Bearer " + token);
                var requestInit = init ? Object.assign({}, init) : {};
                requestInit.headers = requestHeaders;
                return watch(originalFetch(new Request(input, requestInit)), true);
            }
            var fetchInit = init ? Object.assign({}, init) : {};
            fetchInit.headers = new Headers(init ? init.headers : undefined);
            fetchInit.headers.set("Authorization", "Bearer " + token);
            return watch(originalFetch(input, fetchInit), true);
        } catch (e) {
            // Anhaengen nicht moeglich (exotischer Fall): unveraendert senden
            return watch(originalFetch(input, init), false);
        }
    };
})();
(function (global) {
    'use strict';

    const STORAGE_KEY = 'bach.chat.draft.v1';
    const MAX_DRAFT_LENGTH = 200000;

    function resolveStorage(storage) {
        return storage || global.sessionStorage;
    }

    function store(text, storage) {
        if (typeof text !== 'string') {
            throw new TypeError('Chat draft must be a string');
        }
        if (text.length > MAX_DRAFT_LENGTH) {
            throw new RangeError('Chat draft is too large');
        }

        resolveStorage(storage).setItem(STORAGE_KEY, JSON.stringify({
            text: text,
            createdAt: Date.now()
        }));
    }

    function consume(storage) {
        const target = resolveStorage(storage);
        const raw = target.getItem(STORAGE_KEY);
        if (raw === null) return null;

        // Remove before parsing so malformed or stale drafts cannot loop forever.
        target.removeItem(STORAGE_KEY);

        try {
            const payload = JSON.parse(raw);
            if (!payload || typeof payload.text !== 'string') return null;
            if (payload.text.length > MAX_DRAFT_LENGTH) return null;
            return payload.text;
        } catch (error) {
            return null;
        }
    }

    global.BachChatDraft = Object.freeze({
        storageKey: STORAGE_KEY,
        store: store,
        consume: consume
    });
})(window);

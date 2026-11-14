(function (global) {
    'use strict';

    const STORAGE_KEY = 'bach.chat.draft.v1';
    const MAX_DRAFT_LENGTH = 200000;

    function resolveStorage(storage) {
        return storage || global.sessionStorage;
    }

    function store(text, storage, options) {
        let actualText = text;
        let meta = options || {};
        if (typeof text !== 'string') {
            if (text && typeof text === 'object' && typeof text.text === 'string') {
                actualText = text.text;
                meta = text;
            } else {
                throw new TypeError('Chat draft must be a string');
            }
        }
        if (actualText.length > MAX_DRAFT_LENGTH) {
            throw new RangeError('Chat draft is too large');
        }

        const payload = {
            text: actualText,
            autorun: !!meta.autorun,
            agent_id: meta.agent_id ? Number(meta.agent_id) || null : null,
            slot_id: meta.slot_id ? String(meta.slot_id) : null,
            persona: meta.persona ? String(meta.persona) : null,
            createdAt: Date.now()
        };

        resolveStorage(storage).setItem(STORAGE_KEY, JSON.stringify(payload));
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

            if (payload.autorun || payload.agent_id || payload.slot_id || payload.persona) {
                const wrapped = new String(payload.text);
                wrapped.autorun = !!payload.autorun;
                wrapped.agent_id = payload.agent_id || null;
                wrapped.slot_id = payload.slot_id || null;
                wrapped.persona = payload.persona || null;
                return wrapped;
            }
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

// SPDX-License-Identifier: MIT
/**
 * Universal Chat Voice Transcription (`ellmos-voice-io`) & ELLMOS Talk Launcher (#3763, #3764)
 * Attaches a microphone button (`🎤`) across Chat, Tasks, Notizen, and Prompt-Library inputs
 * with local STT (`/api/voice/stt` via MediaRecorder) and Web Speech API fallback.
 */
(() => {
  if (window.__ellmosVoiceMicInstalled) return;
  window.__ellmosVoiceMicInstalled = true;

  const TARGET_SELECTOR = [
    "textarea:not([data-no-voice-mic])",
    "input[data-chat-input]",
    "#chat-input",
    "#utteranceInput",
    "#header-talk-quick-input",
    "#tasks-search",
    ".task-create-dialog input[name='title']",
    "#notes-search-input",
    "#note-title-input",
    "#note-tag-input",
    "#prompt-library input[data-part='search']",
    "#prompt-library input[name='name']",
    ".chat-input",
    ".prompt-input",
  ].join(", ");

  function appendTranscript(el, transcript) {
    const clean = String(transcript || "").trim();
    if (!el || !clean) return;
    const cur = String(el.value || "");
    el.value = cur && !cur.endsWith(" ") ? `${cur} ${clean}` : `${cur}${clean}`;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    try { el.focus(); } catch (_) {}
  }

  async function dictateViaBackendStt(el, btn) {
    const lang = (document.documentElement.lang || "de") === "en" ? "en" : "de";
    if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function" || typeof window.MediaRecorder !== "function") {
      window.open("/talk?companion=1", "ellmos-talk-companion", "width=430,height=680");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks = [];
      const recorder = new MediaRecorder(stream);
      const origText = btn ? btn.textContent : "🎤";
      if (btn) btn.textContent = "🔴 3s…";
      recorder.ondataavailable = (ev) => {
        if (ev.data && ev.data.size > 0) chunks.push(ev.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (btn) btn.textContent = "⏳";
        try {
          const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
          const b64 = await new Promise((resolve) => {
            const reader = new FileReader();
            reader.onloadend = () => resolve(String(reader.result || "").split(",")[1] || "");
            reader.readAsDataURL(blob);
          });
          if (b64) {
            const res = await fetch("/api/voice/stt", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ audio_b64: b64, suffix: ".webm", language: lang }),
            });
            if (res.ok) {
              const data = await res.json();
              if (data?.text?.trim()) appendTranscript(el, data.text.trim());
            }
          }
        } catch (_) {}
        if (btn) btn.textContent = origText;
      };
      recorder.start();
      setTimeout(() => {
        if (recorder.state === "recording") recorder.stop();
      }, 3500);
    } catch (_) {}
  }

  function enhanceInputs(root = document) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    const inputs = root.querySelectorAll(TARGET_SELECTOR);
    inputs.forEach((el) => {
      if (el.dataset.ellmosVoiceEnhanced === "1") return;
      el.dataset.ellmosVoiceEnhanced = "1";
      const parent = el.parentElement;
      if (!parent) return;

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "ellmos-voice-mic-btn";
      btn.dataset.voiceMicBtn = "true";
      btn.title = "Direkt-Diktat per Mikrofon (/api/voice/stt · ellmos-voice-io)";
      btn.textContent = "🎤";
      btn.style.cssText =
        "margin-left:6px;padding:4px 8px;border-radius:8px;cursor:pointer;border:1px solid rgba(56,189,248,0.35);background:#1e293b;color:#f8fafc;";
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SR) {
          try {
            const rec = new SR();
            rec.lang = document.documentElement.lang === "en" ? "en-US" : "de-DE";
            rec.onresult = (e) => {
              const transcript = e.results?.[0]?.[0]?.transcript || "";
              if (transcript) appendTranscript(el, transcript);
            };
            rec.onerror = () => dictateViaBackendStt(el, btn);
            rec.start();
            return;
          } catch (_) {}
        }
        dictateViaBackendStt(el, btn);
      });
      if (el.nextSibling) {
        parent.insertBefore(btn, el.nextSibling);
      } else {
        parent.appendChild(btn);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => enhanceInputs(document));
  } else {
    enhanceInputs(document);
  }

  if (typeof MutationObserver === "function" && document.body) {
    let scheduled = false;
    const obs = new MutationObserver(() => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        enhanceInputs(document);
      });
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }
})();

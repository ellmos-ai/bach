// SPDX-License-Identifier: MIT
/**
 * Universal Chat Voice Transcription (`ellmos-voice-io`) & ELLMOS Talk Launcher (#3763, #3764)
 * Attaches a microphone button (`🎤`) and a live Talk companion shortcut (`🎙️`) to chat inputs.
 */
(() => {
  if (window.__ellmosVoiceMicInstalled) return;
  window.__ellmosVoiceMicInstalled = true;

  function enhanceInputs() {
    const inputs = document.querySelectorAll('textarea, input[data-chat-input], .chat-input, #utteranceInput');
    inputs.forEach((el) => {
      if (el.dataset.ellmosVoiceEnhanced === '1') return;
      el.dataset.ellmosVoiceEnhanced = '1';
      const parent = el.parentElement;
      if (!parent) return;

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ellmos-voice-mic-btn';
      btn.title = 'Spracheingabe (ellmos-voice-io / Web Speech)';
      btn.textContent = '🎤';
      btn.style.cssText = 'margin-left:6px;padding:6px 10px;border-radius:8px;cursor:pointer;border:1px solid rgba(148,163,184,0.3);background:#1e293b;color:#f8fafc;';
      btn.addEventListener('click', () => {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SR) {
          const rec = new SR();
          rec.lang = document.documentElement.lang === 'en' ? 'en-US' : 'de-DE';
          rec.onresult = (ev) => {
            const transcript = ev.results[0][0].transcript;
            el.value = (el.value ? el.value + ' ' : '') + transcript;
            el.dispatchEvent(new Event('input', { bubbles: true }));
          };
          rec.start();
        } else {
          window.open('/talk', '_blank', 'width=820,height=680');
        }
      });
      parent.appendChild(btn);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', enhanceInputs);
  } else {
    enhanceInputs();
  }
})();

/**
 * simulator.js — Call Simulator view
 * Sends messages to /simulate REST endpoint and renders the conversation.
 * Policyholders load from GET /simulate/policyholders; selected row sets simulated CLID (phone).
 */

let simConversationHistory = [];
let simIsLoading = false;
let recognition = null;
let isRecording = false;
let talkModeActive = false;
let talkModeQueue = [];
let ttsAudioPlaying = false;
let currentTtsAudio = null;
let autoConnectTimer = null;
let lastAssistantText = '';
let listenBlockedUntil = 0;
let ringTimer = null;
let ringAudioCtx = null;
let talkSpeechBuffer = '';
let talkCommitTimer = null;
let activeSimAbortController = null;
let activeTtsAbortController = null;
let stopGenerationToken = 0;
/** Last /simulate portal_intent (for live-agent handoff summary). */
let lastPortalIntent = null;

const STOP_ICON = `
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2">
    <rect x="6" y="6" width="12" height="12" rx="2" ry="2"></rect>
  </svg>`;
const MIC_ICON = `
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/>
  </svg>`;
const SEND_ICON = `
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <line x1="22" y1="2" x2="11" y2="13"/>
    <polygon points="22 2 15 22 11 13 2 9 22 2"/>
  </svg>`;

function setInputPlaceholder() {
  const input = document.getElementById('sim-input');
  if (!input) return;
  input.placeholder = talkModeActive
    ? "Talk mode enabled — speak now..."
    : "Type a caller message or use the mic...";
}

function setSendButtonLoading(isLoading) {
  const sendBtn = document.getElementById('sim-send-btn');
  if (!sendBtn) return;
  sendBtn.disabled = !!isLoading;
  sendBtn.innerHTML = isLoading ? '<div class="spinner"></div> Sending' : `${SEND_ICON}Send`;
}

function finishTTSCycle() {
  ttsAudioPlaying = false;
  currentTtsAudio = null;
  listenBlockedUntil = Date.now() + 380;
  updateMicButtonUI();
  if (talkModeActive) requestTalkModeListening(60);
}

function updateMicButtonUI() {
  const micBtn = document.getElementById('sim-mic-btn');
  if (!micBtn) return;

  if (talkModeActive) {
    micBtn.classList.add('recording');
    micBtn.title = ttsAudioPlaying
      ? 'AI speaking... click to stop Talk Mode'
      : 'Click to stop Talk Mode';
    micBtn.innerHTML = STOP_ICON;
    return;
  }

  if (isRecording) {
    micBtn.classList.add('recording');
    micBtn.title = 'Stop recording';
    micBtn.innerHTML = STOP_ICON;
    return;
  }

  micBtn.classList.remove('recording');
  micBtn.title = 'Start voice input';
  micBtn.innerHTML = MIC_ICON;
}

function maskPhone(phone) {
  if (!phone) return 'an unrecognized line';
  const d = phone.replace(/\D/g, '');
  if (d.length < 4) return phone;
  return '···-···-' + d.slice(-4);
}

function getSimWelcomeText() {
  const sel = document.getElementById('sim-policy-select');
  const opt = sel && sel.selectedOptions[0];
  if (!opt || !opt.value) {
    return (
      'Choose a policyholder on the left to simulate their phone number, then tell me your ' +
      'member ID and date of birth (YYYY-MM-DD).'
    );
  }
  return (
    `We detect you're calling from ${maskPhone(opt.dataset.phone || '')}. ` +
    'Please provide your member ID and date of birth (YYYY-MM-DD). You can send both in one message.'
  );
}

function onPolicyholderChange() {
  const row = document.getElementById('sim-detected-phone');
  const sel = document.getElementById('sim-policy-select');
  if (!row || !sel) return;
  const opt = sel.selectedOptions[0];
  if (!opt || !opt.value) {
    row.textContent = 'Select a policyholder…';
    if (autoConnectTimer) {
      clearTimeout(autoConnectTimer);
      autoConnectTimer = null;
    }
    return;
  }
  row.textContent = opt.dataset.phone || '—';
  if (simConversationHistory.length === 0) {
    const bubble = document.getElementById('sim-initial-msg');
    if (bubble) bubble.textContent = getSimWelcomeText();
  }
  const simViewActive = !!document.getElementById('view-simulator')?.classList.contains('active');
  if (simViewActive) triggerAutoRingAndConnect();
}

function ringBurst() {
  try {
    if (!ringAudioCtx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      ringAudioCtx = new Ctx();
    }
    const ctx = ringAudioCtx;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 750;
    gain.gain.value = 0.001;
    osc.connect(gain);
    gain.connect(ctx.destination);
    gain.gain.exponentialRampToValueAtTime(0.10, now + 0.03);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.38);
    osc.start(now);
    osc.stop(now + 0.40);
  } catch (e) {
    // ignore browser audio restrictions
  }
}

function startContinuousRing() {
  stopContinuousRing();
  ringBurst();
  ringTimer = setInterval(ringBurst, 1000);
}

function stopContinuousRing() {
  if (ringTimer) {
    clearInterval(ringTimer);
    ringTimer = null;
  }
  if (ringAudioCtx) {
    try { ringAudioCtx.close(); } catch (e) { }
    ringAudioCtx = null;
  }
}

function triggerAutoRingAndConnect() {
  if (autoConnectTimer) clearTimeout(autoConnectTimer);
  showToast('Ringing... connecting to Talk Mode', 'info');
  startContinuousRing();
  autoConnectTimer = setTimeout(() => {
    stopContinuousRing();
    const talk = document.getElementById('sim-talk-mode');
    if (!talk) return;
    talk.checked = true;
    toggleTalkModeUI();
    autoConnectTimer = null;
  }, 4500);
}

function normalizeSpeech(text) {
  return (text || '').toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
}

function digitCount(text) {
  return ((text || '').match(/\d/g) || []).length;
}

/** Utterances that carry member id / DOB — never drop as noise or echo heuristics. */
function isVerificationLikeText(text) {
  const t = text || '';
  if (digitCount(t) >= 4) return true;
  if (/\bpol\b|p\s*o\s*l|policy|member|birth|dob|date\s+of/i.test(t)) return true;
  return false;
}

/** Greetings / thanks — Web Speech often assigns low confidence; do not drop. */
function isCommonTalkPhraseWhitelisted(text) {
  const t = normalizeSpeech(text);
  if (!t || t.length > 96) return false;
  if (/^(hi|hello|hey|hiya|yo)\b/.test(t)) return true;
  if (/^(good morning|good afternoon|good evening|good day|greetings)\b/.test(t)) return true;
  if (/^(thanks|thank you|thankyou|bye|goodbye|cheers)\b/.test(t)) return true;
  if (/^how are you\b/.test(t)) return true;
  return false;
}

/**
 * Chrome exposes confidence 0–1 on alternatives; other browsers may omit it (null = don't gate).
 * Very low confidence on short non-numeric phrases is usually room noise / TV / other speakers.
 */
function shouldRejectDistantOrNoise(transcript, minConfidence) {
  if (minConfidence === null || minConfidence === undefined) return false;
  // Chromium may report 0 when confidence is unavailable; never drop on that.
  if (minConfidence <= 0) return false;
  const t = normalizeSpeech(transcript);
  if (isVerificationLikeText(transcript)) return false;
  if (isCommonTalkPhraseWhitelisted(transcript)) return false;
  if (t.length < 36) {
    if (minConfidence < 0.3) return true;
    if (minConfidence < 0.45 && digitCount(transcript) < 2) return true;
  }
  return false;
}

function isLikelyNoise(transcript) {
  if (isVerificationLikeText(transcript)) return false;
  if (isCommonTalkPhraseWhitelisted(transcript)) return false;
  const t = normalizeSpeech(transcript);
  if (!t) return true;
  if (t.length < 3) return true;
  const tokens = t.split(' ').filter(Boolean);
  if (tokens.length === 1 && tokens[0].length <= 2) return true;
  const filler = new Set(['uh', 'um', 'hmm', 'mm', 'ah', 'eh', 'noise', 'static']);
  if (tokens.every(tok => filler.has(tok))) return true;
  // Tiny single-token blurts only — do not drop real answers like "deductible" or "claims".
  if (tokens.length === 1 && tokens[0].length <= 4 && digitCount(transcript) === 0) return true;
  return false;
}

function likelyAssistantEcho(transcript) {
  if (isVerificationLikeText(transcript)) return false;
  const heard = normalizeSpeech(transcript);
  const spoken = normalizeSpeech(lastAssistantText);
  if (!heard || !spoken) return false;
  if (heard.length < 14) return false;
  if (spoken.includes(heard) || heard.includes(spoken.slice(0, Math.min(heard.length, spoken.length)))) {
    return true;
  }
  // Avoid flagging short user replies that share generic words with the assistant ("your", "member", …).
  if (heard.length < 28) return false;
  const heardTokens = new Set(heard.split(' ').filter(Boolean));
  const spokenTokens = spoken.split(' ').filter(Boolean);
  if (spokenTokens.length < 6) return false;
  let overlap = 0;
  for (const tok of spokenTokens) {
    if (heardTokens.has(tok)) overlap += 1;
  }
  return (overlap / spokenTokens.length) > 0.82;
}

/** Longer pause when caller may still be adding DOB after member id. */
function talkCommitDelayMs(buffer) {
  const b = (buffer || '').trim();
  const hasYear = /\b(19|20)\d{2}\b/.test(b);
  const hasPol = /\bpol\b|p\s*o\s*l|policy\s*number|member\s*id/i.test(b);
  if (hasPol && !hasYear) return 2800;
  if (isCommonTalkPhraseWhitelisted(b) && b.length < 48) return 950;
  return 1700;
}

function scheduleTalkCommit() {
  if (!talkModeActive) return;
  if (talkCommitTimer) clearTimeout(talkCommitTimer);
  talkCommitTimer = setTimeout(commitTalkSpeechBuffer, talkCommitDelayMs(talkSpeechBuffer));
}

function requestTalkModeListening(delayMs = 0) {
  if (!talkModeActive) return;
  setTimeout(() => {
    if (!talkModeActive) return;
    if (Date.now() < listenBlockedUntil) {
      requestTalkModeListening(200);
      return;
    }
    // After a reply, TTS may still be marked active briefly — retry instead of giving up once.
    if (simIsLoading || ttsAudioPlaying) {
      requestTalkModeListening(200);
      return;
    }
    startTalkModeListening();
  }, delayMs);
}

function commitTalkSpeechBuffer() {
  if (!talkModeActive) return;
  const text = talkSpeechBuffer.trim();
  talkSpeechBuffer = '';
  if (!text) {
    requestTalkModeListening(200);
    return;
  }
  if (likelyAssistantEcho(text)) {
    requestTalkModeListening(250);
    return;
  }
  // End current capture turn and send one consolidated utterance.
  stopRecording();
  sendMessage(text);
}

function hardStopAll(reason = 'Stopped.') {
  stopGenerationToken += 1;
  talkModeActive = false;
  talkSpeechBuffer = '';
  talkModeQueue = [];
  simIsLoading = false;
  setSendButtonLoading(false);
  if (talkCommitTimer) {
    clearTimeout(talkCommitTimer);
    talkCommitTimer = null;
  }
  if (autoConnectTimer) {
    clearTimeout(autoConnectTimer);
    autoConnectTimer = null;
  }
  stopContinuousRing();
  if (activeSimAbortController) {
    try { activeSimAbortController.abort(); } catch (e) { }
    activeSimAbortController = null;
  }
  if (activeTtsAbortController) {
    try { activeTtsAbortController.abort(); } catch (e) { }
    activeTtsAbortController = null;
  }
  if (currentTtsAudio) {
    try { currentTtsAudio.pause(); } catch (e) { }
    currentTtsAudio = null;
  }
  if ('speechSynthesis' in window) {
    try { window.speechSynthesis.cancel(); } catch (e) { }
  }
  ttsAudioPlaying = false;
  stopRecording();
  const talk = document.getElementById('sim-talk-mode');
  const chat = document.getElementById('sim-chat-mode');
  if (talk) talk.checked = false;
  if (chat) chat.checked = true;
  updateMicButtonUI();
  if (reason) showToast(reason, 'info');
}

async function loadSimulatorPolicyholders() {
  const select = document.getElementById('sim-policy-select');
  if (!select) return;
  select.innerHTML = '<option value="">Loading…</option>';
  const data = await api.get('/simulate/policyholders');
  if (!data || !Array.isArray(data.policyholders)) {
    select.innerHTML = '<option value="">Failed to load policyholders</option>';
    showToast('Could not load policyholders from API', 'error');
    return;
  }
  select.innerHTML = '<option value="">Select a policyholder…</option>';
  data.policyholders.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.member_id || '';
    opt.dataset.phone = p.phone || '';
    opt.textContent = `${p.member_id} — ${p.name || 'Member'} (${p.plan_name || 'Plan'})`;
    select.appendChild(opt);
  });
  select.onchange = onPolicyholderChange;
}

function setQuery(text) {
  const input = document.getElementById('sim-input');
  if (input) {
    input.value = text;
    input.focus();
  }
}

function toggleTalkModeUI() {
  const on = !!document.getElementById('sim-talk-mode')?.checked;
  const chat = document.getElementById('sim-chat-mode');
  talkModeActive = on;
  if (chat) chat.checked = !on;
  if (on) {
    showToast('Talk mode enabled: speak continuously, click mic to stop.', 'info');
    requestTalkModeListening(0);
  } else {
    stopRecording();
  }
  updateMicButtonUI();
}

function toggleChatModeUI() {
  const chatOn = !!document.getElementById('sim-chat-mode')?.checked;
  const talk = document.getElementById('sim-talk-mode');
  if (chatOn && talk) {
    talk.checked = false;
  }
  toggleTalkModeUI();
}

function appendMessage(role, text, isTyping = false) {
  const messages = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = `message ${role}${isTyping ? ' typing' : ''}`;

  const avatarText = role === 'user' ? 'You' : 'AI';
  const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  if (isTyping) {
    div.innerHTML = `
      <div class="msg-avatar">${avatarText}</div>
      <div class="msg-bubble">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>`;
  } else {
    div.innerHTML = `
      <div class="msg-avatar">${avatarText}</div>
      <div>
        <div class="msg-bubble">${escapeHtml(text)}</div>
        <div class="msg-time">${now}</div>
      </div>`;
  }

  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
  return div;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function inferVerifiedFromHistory(hist) {
  if (!Array.isArray(hist)) return false;
  return hist.some(
    (m) =>
      m &&
      m.role === 'assistant' &&
      /identity is verified|your identity is verified/i.test(String(m.content || ''))
  );
}

/**
 * Push current simulator transcript to the portal live-agent queue with full context.
 * Agents open /portal → Live agent queue → View context.
 */
async function submitLiveAgentHandoff(reason) {
  const sel = document.getElementById('sim-policy-select');
  const opt = sel && sel.selectedOptions[0];
  const simPhone = opt && opt.dataset.phone ? opt.dataset.phone : '';
  const memberId = opt && opt.value ? opt.value : '';
  if (!memberId || !simPhone) {
    showToast('Select a policyholder first.', 'error');
    return null;
  }
  const verified = inferVerifiedFromHistory(simConversationHistory);
  try {
    const r = await fetch(`${API_BASE}/portal/v1/live-agent/handoffs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversation_history: simConversationHistory,
        caller_phone: simPhone,
        simulated_member_id: memberId,
        verified,
        portal_intent: lastPortalIntent,
        reason: reason || 'user_requested',
        source: 'simulator',
      }),
    });
    if (r.ok) {
      showToast('Transfer queued — an agent can claim you in the portal Call desk with full context.', 'info');
      return await r.json();
    }
    showToast(`Live agent queue failed (${r.status})`, 'error');
  } catch (e) {
    showToast('Live agent queue failed.', 'error');
  }
  return null;
}

function removeHumanTransferOffers() {
  document.querySelectorAll('.human-transfer-offer-wrap').forEach((el) => el.remove());
}

/**
 * Shown after the AI could not answer confidently (fallback). User must confirm before handoff.
 */
function appendHumanTransferOffer() {
  removeHumanTransferOffers();
  const messages = document.getElementById('chat-messages');
  if (!messages) return;

  const wrap = document.createElement('div');
  wrap.className = 'message assistant human-transfer-offer-wrap';
  wrap.innerHTML = `
    <div class="msg-avatar" title="Handoff">⋯</div>
    <div>
      <div class="human-transfer-card">
        <div class="human-transfer-title">Connect with a team member?</div>
        <p class="human-transfer-desc">If you choose yes, your transcript is sent to the portal so an agent can pick this up with full context.</p>
        <div class="human-transfer-actions">
          <button type="button" class="btn btn-primary human-transfer-yes" style="font-size:0.82rem;padding:0.4rem 0.9rem;">Yes, transfer me</button>
          <button type="button" class="btn btn-ghost human-transfer-no" style="font-size:0.82rem;padding:0.4rem 0.9rem;">No, keep chatting</button>
        </div>
      </div>
      <div class="msg-time">${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
    </div>`;

  const yes = wrap.querySelector('.human-transfer-yes');
  const no = wrap.querySelector('.human-transfer-no');
  if (yes) {
    yes.addEventListener('click', async () => {
      yes.disabled = true;
      if (no) no.disabled = true;
      lastPortalIntent = 'request_live_agent';
      await submitLiveAgentHandoff('user_accepted_after_unclear_ai');
      removeHumanTransferOffers();
    });
  }
  if (no) {
    no.addEventListener('click', () => {
      removeHumanTransferOffers();
      showToast('Okay — ask another question anytime.', 'info');
    });
  }

  messages.appendChild(wrap);
  messages.scrollTop = messages.scrollHeight;
}

async function sendMessage(forcedText = null) {
  if (simIsLoading) {
    const queued = (forcedText || '').trim();
    if (queued) talkModeQueue.push(queued);
    return;
  }

  const input = document.getElementById('sim-input');
  const sel = document.getElementById('sim-policy-select');
  const demoMode = document.getElementById('sim-demo-mode')?.checked;
  const opt = sel && sel.selectedOptions[0];
  const simPhone = opt && opt.dataset.phone ? opt.dataset.phone : '';
  const selectedMember = opt && opt.value ? opt.value : '';

  const text = (forcedText || input.value).trim();
  if (!text) return;
  const thisToken = stopGenerationToken;

  if (!selectedMember || !simPhone) {
    showToast('Select a policyholder first (simulates detected phone)', 'error');
    return;
  }

  input.value = '';
  simIsLoading = true;
  setSendButtonLoading(true);

  // Show user message
  appendMessage('user', text);

  // Show typing indicator
  const typingEl = appendMessage('assistant', '', true);

  try {
    activeSimAbortController = new AbortController();
    const result = await api.post('/simulate', {
      caller_id: demoMode ? selectedMember : '__sim__',
      caller_phone: simPhone,
      message: text,
      conversation_history: simConversationHistory,
      demo_mode: !!demoMode,
    }, { signal: activeSimAbortController.signal });
    activeSimAbortController = null;
    if (thisToken !== stopGenerationToken) {
      typingEl.remove();
      return;
    }

    typingEl.remove();

    if (result && result.agent_response) {
      appendMessage('assistant', result.agent_response);
      lastAssistantText = result.agent_response || '';
      simConversationHistory = result.conversation_history || [];
      lastPortalIntent = result.portal_intent || null;

      // Show elapsed time as subtle toast
      if (result.elapsed_ms) {
        showToast(`⚡ Response in ${result.elapsed_ms}ms`, 'info');
      }

      if (result.portal_intent === 'request_live_agent') {
        submitLiveAgentHandoff('explicit_intent');
      } else if (result.offer_human_transfer) {
        appendHumanTransferOffer();
      }

      // Play the TTS audio response (optional per-intent voice from portal)
      playTTS(result.agent_response, result.voice_id);

    } else {
      appendMessage('assistant', `Sorry, the backend could not be reached at ${API_BASE}.`);
      showToast('Backend unreachable — start the FastAPI server', 'error');
    }
  } catch (err) {
    activeSimAbortController = null;
    typingEl.remove();
    if (thisToken !== stopGenerationToken) return;
    appendMessage('assistant', 'Error communicating with the AI backend. Is the server running?');
    showToast('Connection error', 'error');
  }

  simIsLoading = false;
  setSendButtonLoading(false);
  input.focus();
  if (talkModeQueue.length > 0) {
    const nextText = talkModeQueue.shift();
    if (nextText) {
      setTimeout(() => sendMessage(nextText), 250);
      return;
    }
  }
  if (talkModeActive) {
    requestTalkModeListening(120);
  }
}

// ── Voice Input & Output ─────────────────────────────────────────────────────

function initSpeechRecognition() {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    showToast('Speech recognition is not supported in this browser.', 'error');
    return false;
  }

  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRec();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = 'en-US';
  recognition.maxAlternatives = 1;

  recognition.onresult = (event) => {
    let finalTranscript = '';
    let interimTranscript = '';
    let minConfidence = null;
    for (let i = event.resultIndex; i < event.results.length; ++i) {
      const alt = event.results[i][0];
      if (event.results[i].isFinal) {
        finalTranscript += alt.transcript;
        const c = alt.confidence;
        if (typeof c === 'number' && !Number.isNaN(c)) {
          minConfidence = minConfidence === null ? c : Math.min(minConfidence, c);
        }
      } else {
        interimTranscript += alt.transcript;
      }
    }

    const input = document.getElementById('sim-input');
    if (talkModeActive && (simIsLoading || ttsAudioPlaying)) {
      if (interimTranscript) input.value = interimTranscript;
      return;
    }

    // Still speaking (interim text) — slide the silence window so we don't cut off mid–member ID + DOB.
    if (talkModeActive && interimTranscript.trim()) {
      input.value = `${talkSpeechBuffer} ${interimTranscript}`.trim();
      scheduleTalkCommit();
    } else if (!finalTranscript) {
      input.value = interimTranscript;
    }

    if (finalTranscript) {
      const normalized = finalTranscript.trim();
      if (!normalized) return;
      if (shouldRejectDistantOrNoise(normalized, minConfidence)) return;
      if (isLikelyNoise(normalized)) return;
      if (talkModeActive) {
        if (likelyAssistantEcho(normalized)) return;
        talkSpeechBuffer = `${talkSpeechBuffer} ${normalized}`.trim();
        scheduleTalkCommit();
      } else {
        input.value = normalized;
        // Auto send when finishing speech
        setTimeout(sendMessage, 500);
      }
    }
  };

  recognition.onerror = (event) => {
    console.error('Speech recognition error', event.error);
    stopRecording();
    if (event.error !== 'no-speech') {
      showToast('Microphone error: ' + event.error, 'error');
    }
    if (talkModeActive) {
      requestTalkModeListening(700);
    }
  };

  recognition.onend = () => {
    stopRecording();
    if (talkModeActive && !simIsLoading) {
      requestTalkModeListening(350);
    }
  };

  return true;
}

function toggleRecording() {
  if (talkModeActive) {
    // In talk mode, mic button acts as STOP control for the continuous loop.
    hardStopAll('Talk mode stopped.');
    return;
  }
  if (isRecording) {
    stopRecording();
  } else {
    if (!recognition && !initSpeechRecognition()) return;

    try {
      recognition.start();
      isRecording = true;
      document.getElementById('sim-input').placeholder = "Listening...";
      updateMicButtonUI();
    } catch (e) {
      console.error(e);
    }
  }
}

function startTalkModeListening() {
  if (!talkModeActive) return;
  if (simIsLoading || ttsAudioPlaying) {
    requestTalkModeListening(200);
    return;
  }
  if (Date.now() < listenBlockedUntil) {
    requestTalkModeListening(200);
    return;
  }
  if (isRecording) return;
  if (!recognition && !initSpeechRecognition()) return;
  try {
    recognition.start();
    isRecording = true;
    document.getElementById('sim-input').placeholder = "Talk mode listening...";
    updateMicButtonUI();
  } catch (e) {
    requestTalkModeListening(400);
  }
}

function stopRecording() {
  if (talkCommitTimer) {
    clearTimeout(talkCommitTimer);
    talkCommitTimer = null;
  }
  if (isRecording) {
    isRecording = false;
    if (recognition) {
      try { recognition.stop(); } catch (e) { }
    }
  }
  setInputPlaceholder();
  updateMicButtonUI();
}

async function playTTS(text, voiceId) {
  try {
    // Prevent assistant voice from being captured as next user input.
    if (isRecording) stopRecording();
    ttsAudioPlaying = true;
    listenBlockedUntil = Date.now() + 6000;
    updateMicButtonUI();

    activeTtsAbortController = new AbortController();
    const response = await fetch(`${API_BASE}/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice_id: voiceId || null }),
      signal: activeTtsAbortController.signal,
    });
    activeTtsAbortController = null;

    if (!response.ok) throw new Error('TTS request failed');

    // Check if backend returned a JSON flag requesting browser fallback
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      const data = await response.json();
      if (data.fallback) {
        // ElevenLabs not configured, use browser SpeechSynthesis
        console.log("ElevenLabs API key missing, falling back to browser TTS...");
        fallbackBrowserTTS(text);
        return;
      }
    }

    // Proceed with backend Audio bytes
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentTtsAudio = audio;
    audio.onended = finishTTSCycle;
    audio.onerror = finishTTSCycle;
    await audio.play();

  } catch (err) {
    activeTtsAbortController = null;
    console.error("Failed to fetch backend TTS:", err);
    ttsAudioPlaying = false;
    updateMicButtonUI();
    fallbackBrowserTTS(text);
  }
}

function fallbackBrowserTTS(text) {
  if ('speechSynthesis' in window) {
    ttsAudioPlaying = true;
    updateMicButtonUI();
    const utterance = new SpeechSynthesisUtterance(text);

    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find(
      (v) =>
        /Microsoft .*Natasha|Microsoft .*Jenny|Google UK English Female|Samantha|Karen/i.test(
          v.name
        )
    );
    if (preferred) utterance.voice = preferred;

    utterance.rate = 0.98;
    utterance.pitch = 1.04;
    utterance.onend = finishTTSCycle;
    utterance.onerror = finishTTSCycle;
    window.speechSynthesis.speak(utterance);
  } else {
    ttsAudioPlaying = false;
    updateMicButtonUI();
  }
}

function clearSimulation() {
  hardStopAll('');
  removeHumanTransferOffers();
  lastPortalIntent = null;
  simConversationHistory = [];
  talkModeQueue = [];
  talkSpeechBuffer = '';
  if (talkCommitTimer) {
    clearTimeout(talkCommitTimer);
    talkCommitTimer = null;
  }
  if (autoConnectTimer) {
    clearTimeout(autoConnectTimer);
    autoConnectTimer = null;
  }
  stopContinuousRing();
  if (currentTtsAudio) {
    try { currentTtsAudio.pause(); } catch (e) { }
    currentTtsAudio = null;
  }
  ttsAudioPlaying = false;
  updateMicButtonUI();
  const messages = document.getElementById('chat-messages');
  const welcome = getSimWelcomeText();
  messages.innerHTML = `
    <div class="message assistant">
      <div class="msg-avatar">AI</div>
      <div class="msg-bubble" id="sim-initial-msg">${escapeHtml(welcome)}</div>
    </div>`;
  showToast('Conversation cleared', 'info');
}

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('sim-policy-select')) {
    loadSimulatorPolicyholders();
  }
  const talk = document.getElementById('sim-talk-mode');
  if (talk) {
    talk.addEventListener('change', toggleTalkModeUI);
    toggleTalkModeUI();
  }
  const chat = document.getElementById('sim-chat-mode');
  if (chat) {
    chat.addEventListener('change', toggleChatModeUI);
  }
  updateMicButtonUI();
});

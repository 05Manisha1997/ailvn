/**
 * simulator.js — Call Simulator view
 * Sends messages to /simulate REST endpoint and renders the conversation.
 */

let simConversationHistory = [];
let simIsLoading = false;
let recognition = null;
let isRecording = false;

function setQuery(text) {
  const input = document.getElementById('sim-input');
  if (input) {
    input.value = text;
    input.focus();
  }
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

async function sendMessage() {
  if (simIsLoading) return;

  const input = document.getElementById('sim-input');
  const sendBtn = document.getElementById('sim-send-btn');
  const callerId = document.getElementById('sim-caller-id').value;
  const demoMode = document.getElementById('sim-demo-mode').checked;

  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  simIsLoading = true;
  sendBtn.disabled = true;
  sendBtn.innerHTML = '<div class="spinner"></div> Sending';

  // Show user message
  appendMessage('user', text);

  // Show typing indicator
  const typingEl = appendMessage('assistant', '', true);

  try {
    const result = await api.post('/simulate', {
      caller_id: callerId,
      message: text,
      conversation_history: simConversationHistory,
      demo_mode: demoMode,
    });

    typingEl.remove();

    if (result && result.agent_response) {
      appendMessage('assistant', result.agent_response);
      simConversationHistory = result.conversation_history || [];

      // Show elapsed time as subtle toast
      if (result.elapsed_ms) {
        showToast(`⚡ Response in ${result.elapsed_ms}ms`, 'info');
      }

      // Play the TTS audio response
      playTTS(result.agent_response);

    } else {
      appendMessage('assistant', 'Sorry, the backend could not be reached. Make sure the server is running on localhost:8000.');
      showToast('Backend unreachable — start the FastAPI server', 'error');
    }
  } catch (err) {
    typingEl.remove();
    appendMessage('assistant', 'Error communicating with the AI backend. Is the server running?');
    showToast('Connection error', 'error');
  }

  simIsLoading = false;
  sendBtn.disabled = false;
  sendBtn.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <line x1="22" y1="2" x2="11" y2="13"/>
      <polygon points="22 2 15 22 11 13 2 9 22 2"/>
    </svg>
    Send`;
  input.focus();
}

// ── Voice Input & Output ─────────────────────────────────────────────────────

function initSpeechRecognition() {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    showToast('Speech recognition is not supported in this browser.', 'error');
    return false;
  }

  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRec();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = 'en-US';

  recognition.onresult = (event) => {
    let finalTranscript = '';
    let interimTranscript = '';
    for (let i = event.resultIndex; i < event.results.length; ++i) {
      if (event.results[i].isFinal) {
        finalTranscript += event.results[i][0].transcript;
      } else {
        interimTranscript += event.results[i][0].transcript;
      }
    }

    const input = document.getElementById('sim-input');
    if (finalTranscript) {
      input.value = finalTranscript;
      // Auto send when finishing speech
      setTimeout(sendMessage, 500);
    } else {
      input.value = interimTranscript;
    }
  };

  recognition.onerror = (event) => {
    console.error('Speech recognition error', event.error);
    stopRecording();
    if (event.error !== 'no-speech') {
      showToast('Microphone error: ' + event.error, 'error');
    }
  };

  recognition.onend = () => {
    stopRecording();
  };

  return true;
}

function toggleRecording() {
  if (isRecording) {
    stopRecording();
  } else {
    if (!recognition && !initSpeechRecognition()) return;

    try {
      recognition.start();
      isRecording = true;
      document.getElementById('sim-input').placeholder = "Listening...";
      const micBtn = document.getElementById('sim-mic-btn');
      micBtn.classList.add('recording');
      micBtn.innerHTML = `
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2">
                <rect x="6" y="6" width="12" height="12" rx="2" ry="2"></rect>
              </svg>`;
    } catch (e) {
      console.error(e);
    }
  }
}

function stopRecording() {
  if (!isRecording) return;
  isRecording = false;
  if (recognition) {
    try { recognition.stop(); } catch (e) { }
  }
  document.getElementById('sim-input').placeholder = "Type a caller message or use the mic...";
  const micBtn = document.getElementById('sim-mic-btn');
  micBtn.classList.remove('recording');
  micBtn.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/>
      </svg>`;
}

async function playTTS(text) {
  try {
    const response = await fetch(`${API_BASE}/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });

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
    audio.play();

  } catch (err) {
    console.error("Failed to fetch backend TTS:", err);
    fallbackBrowserTTS(text);
  }
}

function fallbackBrowserTTS(text) {
  if ('speechSynthesis' in window) {
    const utterance = new SpeechSynthesisUtterance(text);

    // Try to pick a decent female voice if available
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find(v => v.name.includes('Google UK English Female') || v.name.includes('Samantha'));
    if (preferred) utterance.voice = preferred;

    utterance.rate = 1.05;
    utterance.pitch = 1.0;
    window.speechSynthesis.speak(utterance);
  }
}

function clearSimulation() {
  simConversationHistory = [];
  const messages = document.getElementById('chat-messages');
  messages.innerHTML = `
    <div class="message assistant">
      <div class="msg-avatar">AI</div>
      <div class="msg-bubble">
        Thank you for calling InsureCo. Please state your policy number and date of birth to begin.
      </div>
    </div>`;
  showToast('Conversation cleared', 'info');
}

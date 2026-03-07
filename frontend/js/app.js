/**
 * app.js — SPA routing, global state, and API client
 */

// ── Config ──────────────────────────────────────────────────────────────────
const API_BASE = (window.location.port === '3000' || window.location.port === '')
  ? 'http://localhost:8000'
  : window.location.origin;

// ── Global State ─────────────────────────────────────────────────────────────
const AppState = {
  currentView: 'dashboard',
  conversationHistory: [],
  activeCalls: [],
};

// ── View Router ──────────────────────────────────────────────────────────────
function showView(viewName) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));

  const view = document.getElementById(`view-${viewName}`);
  const navBtn = document.getElementById(`nav-${viewName}`);
  if (view) view.classList.add('active');
  if (navBtn) navBtn.classList.add('active');

  AppState.currentView = viewName;

  const titles = {
    dashboard: ['Live Calls', 'Real-time call monitoring'],
    simulator: ['Call Simulator', 'Test the AI agent pipeline'],
    analytics: ['Analytics', 'Performance metrics & insights'],
    policies: ['Policy Manager', 'Manage policyholders & documents'],
    templates: ['Response Templates', 'Manage agent response formatting'],
  };
  const [title, sub] = titles[viewName] || ['Dashboard', ''];
  document.getElementById('view-title').textContent = title;
  document.getElementById('view-subtitle').textContent = sub;

  // Lazy-init charts only when analytics is opened
  if (viewName === 'analytics' && typeof initCharts === 'function') {
    setTimeout(initCharts, 100);
  }
}

// ── API Client ────────────────────────────────────────────────────────────────
const api = {
  async get(path) {
    try {
      const r = await fetch(`${API_BASE}${path}`);
      if (!r.ok) throw new Error(r.statusText);
      return r.json();
    } catch {
      return null;
    }
  },
  async post(path, body) {
    try {
      const r = await fetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(r.statusText);
      return r.json();
    } catch (e) {
      return null;
    }
  },
};

// ── Toast Notifications ──────────────────────────────────────────────────────
function showToast(message, type = 'success') {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span class="toast-icon">${icons[type] || 'ℹ️'}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ── Time formatter ───────────────────────────────────────────────────────────
function timeAgo(isoString) {
  const diff = (Date.now() - new Date(isoString).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

// ── Theme Toggle ─────────────────────────────────────────────────────────────
window.toggleTheme = function () {
  console.log("Toggle Theme Clicked");
  const body = document.body;
  body.classList.toggle('light-theme');
  const isLight = body.classList.contains('light-theme');
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
  console.log("Theme set to:", isLight ? 'light' : 'dark');
}

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  console.log("App Init...");
  const savedTheme = localStorage.getItem('theme');
  if (savedTheme === 'light') {
    document.body.classList.add('light-theme');
  }
  showView('dashboard');
});

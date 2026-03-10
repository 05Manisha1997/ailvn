/**
 * dashboard.js — Live calls view with polling & activity feed
 */

const DEMO_ACTIVITY = [
    { color: 'act-teal', text: 'POL-001 (Sarah O\'Brien) — Hospital eligibility query resolved', time: '2m ago' },
    { color: 'act-green', text: 'POL-002 (James Murphy) — Claim limit confirmed via RAG', time: '5m ago' },
    { color: 'act-blue', text: 'POL-004 (Ciarán Walsh) — Deductible status provided', time: '11m ago' },
    { color: 'act-yellow', text: 'POL-003 (Aoife Kelly) — Transferred to specialist (out-of-scope)', time: '18m ago' },
    { color: 'act-teal', text: 'POL-005 (Niamh Brennan) — Surgery coverage confirmed at 90%', time: '24m ago' },
    { color: 'act-green', text: 'POL-001 (Sarah O\'Brien) — Mental health coverage enquiry done', time: '31m ago' },
];

function renderCallCard(call) {
    const initials = call.caller_id ? call.caller_id.substring(0, 3).toUpperCase() : '???';
    const status = call.status || 'active';
    const started = call.started_at ? timeAgo(call.started_at) : '–';
    return `
    <div class="call-card">
      <div class="call-avatar">${initials}</div>
      <div class="call-info">
        <div class="call-id">${call.caller_id || call.id}</div>
        <div class="call-meta">Started ${started} · ${call.id}</div>
      </div>
      <span class="call-duration">Live</span>
      <span class="badge ${status}">${status}</span>
    </div>`;
}

async function refreshCalls() {
    const data = await api.get('/calls');
    const list = document.getElementById('call-list');
    const empty = document.getElementById('call-empty');
    const badge = document.getElementById('active-call-badge');
    const kpiVal = document.getElementById('kpi-active-val');
    const pulse = document.getElementById('kpi-pulse');

    if (!data) return;

    const calls = data.calls || [];
    AppState.activeCalls = calls;

    // Update badge and KPI
    const count = calls.length;
    badge.textContent = count;
    badge.classList.toggle('visible', count > 0);
    kpiVal.textContent = count;
    pulse.classList.toggle('active', count > 0);

    if (count === 0) {
        empty.style.display = '';
        // Remove any old call cards
        list.querySelectorAll('.call-card').forEach(el => el.remove());
    } else {
        empty.style.display = 'none';
        list.innerHTML = calls.map(renderCallCard).join('');
    }
}

function renderActivityFeed() {
    const feed = document.getElementById('activity-feed');
    if (!feed) return;
    feed.innerHTML = DEMO_ACTIVITY.map(item => `
    <div class="activity-item">
      <div class="activity-dot ${item.color}"></div>
      <span>${item.text}</span>
      <span class="activity-time">${item.time}</span>
    </div>`).join('');
}

// Poll every 5 seconds
let dashboardInterval = null;

document.addEventListener('DOMContentLoaded', () => {
    refreshCalls();
    renderActivityFeed();
    dashboardInterval = setInterval(() => {
        if (AppState.currentView === 'dashboard') refreshCalls();
    }, 5000);
});

/**
 * dashboard.js — Live calls view with polling & activity feed
 */

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

function renderActivityFeed(calls = []) {
    const feed = document.getElementById('activity-feed');
    if (!feed) return;
    if (!calls.length) {
        feed.innerHTML = `
        <div class="activity-item">
          <div class="activity-dot act-blue"></div>
          <span>No recent activity yet. Incoming calls will appear here.</span>
          <span class="activity-time">now</span>
        </div>`;
        return;
    }
    const items = [...calls]
        .sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''))
        .slice(0, 8)
        .map((call, idx) => {
            const color = idx % 3 === 0 ? 'act-teal' : idx % 3 === 1 ? 'act-green' : 'act-blue';
            const who = call.caller_id || call.id || 'Unknown caller';
            const state = call.status || 'active';
            return {
                color,
                text: `${who} — status ${state}`,
                time: call.started_at ? timeAgo(call.started_at) : 'just now',
            };
        });
    feed.innerHTML = items.map(item => `
    <div class="activity-item">
      <div class="activity-dot ${item.color}"></div>
      <span>${item.text}</span>
      <span class="activity-time">${item.time}</span>
    </div>`).join('');
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
    renderActivityFeed(calls);
}

// Poll every 5 seconds
let dashboardInterval = null;

document.addEventListener('DOMContentLoaded', () => {
    refreshCalls();
    dashboardInterval = setInterval(() => {
        if (AppState.currentView === 'dashboard') refreshCalls();
    }, 5000);
});

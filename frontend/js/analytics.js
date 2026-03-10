/**
 * analytics.js — Analytics view charts and animated counters
 */

let chartsInitialised = false;

function animateCounter(el) {
    const target = parseInt(el.dataset.target, 10);
    const isPct = el.classList.contains('pct');
    const duration = 1200;
    const start = performance.now();

    function step(now) {
        const elapsed = now - start;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
        const value = Math.round(eased * target);
        el.textContent = isPct ? `${value}%` : value;
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

function initCharts() {
    if (chartsInitialised) return;
    chartsInitialised = true;

    // Animate counters
    document.querySelectorAll('.counter').forEach(el => animateCounter(el));

    // ── Intent Donut Chart ────────────────────────────────────────────────────
    const intentCtx = document.getElementById('intent-chart');
    if (intentCtx) {
        new Chart(intentCtx, {
            type: 'doughnut',
            data: {
                labels: ['Coverage Check', 'Hospital Eligibility', 'Claim Limit', 'Deductible', 'Treatment', 'Other'],
                datasets: [{
                    data: [18, 12, 8, 5, 3, 1],
                    backgroundColor: [
                        'rgba(0,212,170,.85)',
                        'rgba(79,142,247,.85)',
                        'rgba(167,139,250,.85)',
                        'rgba(52,211,153,.85)',
                        'rgba(251,191,36,.85)',
                        'rgba(248,113,113,.85)',
                    ],
                    borderColor: 'rgba(10,13,20,1)',
                    borderWidth: 3,
                    hoverOffset: 6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '70%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: '#94a3b8',
                            font: { family: 'Inter', size: 11 },
                            padding: 12,
                            boxWidth: 10,
                            borderRadius: 3,
                        },
                    },
                    tooltip: {
                        backgroundColor: '#0f1420',
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1,
                        titleColor: '#e2e8f0',
                        bodyColor: '#94a3b8',
                        callbacks: {
                            label: (ctx) => ` ${ctx.label}: ${ctx.raw} calls`,
                        },
                    },
                },
            },
        });
    }

    // ── Hourly Bar Chart ──────────────────────────────────────────────────────
    const hourlyCtx = document.getElementById('hourly-chart');
    if (hourlyCtx) {
        const hours = Array.from({ length: 24 }, (_, i) =>
            `${String(i).padStart(2, '0')}:00`
        );
        const data = [2, 1, 0, 0, 0, 0, 1, 3, 5, 7, 6, 4, 3, 5, 4, 2, 2, 1, 1, 0, 0, 0, 0, 0];

        new Chart(hourlyCtx, {
            type: 'bar',
            data: {
                labels: hours,
                datasets: [{
                    label: 'Calls',
                    data,
                    backgroundColor: (ctx) => {
                        const gradient = ctx.chart.ctx.createLinearGradient(0, 0, 0, 240);
                        gradient.addColorStop(0, 'rgba(0,212,170,.9)');
                        gradient.addColorStop(1, 'rgba(79,142,247,.3)');
                        return gradient;
                    },
                    borderRadius: 6,
                    borderSkipped: false,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: '#0f1420',
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1,
                        titleColor: '#e2e8f0',
                        bodyColor: '#94a3b8',
                        callbacks: {
                            label: (ctx) => ` ${ctx.raw} call${ctx.raw !== 1 ? 's' : ''}`,
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(255,255,255,.04)' },
                        ticks: { color: '#4a5568', font: { size: 10 }, maxTicksLimit: 12 },
                    },
                    y: {
                        grid: { color: 'rgba(255,255,255,.04)' },
                        ticks: { color: '#4a5568', stepSize: 2 },
                        beginAtZero: true,
                    },
                },
            },
        });
    }
}

// Re-initialise charts if analytics is opened after first paint
document.addEventListener('DOMContentLoaded', () => {
    // Charts will init lazily on first view switch to analytics
});

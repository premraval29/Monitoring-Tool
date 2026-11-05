// PulseMon Frontend Client

let performanceChart = null;
const MAX_CHART_POINTS = 60; // 60 seconds = 1 minute of visible real-time activity
let ws = null;
let reconnectTimer = null;

// Telemetry history buffer for brief analytics modal
window.metricsHistoryBuffer = [];
let activeModalType = null;
let activeModalParam = null;
let modalChart = null;

// Color helper based on percentage
function getStatusColor(percent) {
  if (percent >= 85) return { bg: 'bg-rose-500', text: 'text-rose-400', border: 'border-rose-500/20' };
  if (percent >= 70) return { bg: 'bg-amber-500', text: 'text-amber-400', border: 'border-amber-500/20' };
  return { bg: 'bg-indigo-500', text: 'text-indigo-400', border: 'border-indigo-500/20' };
}

// Initialize Chart.js
function initChart() {
  const ctx = document.getElementById('livePerformanceChart').getContext('2d');
  
  // Gradients
  const cpuGrad = ctx.createLinearGradient(0, 0, 0, 240);
  cpuGrad.addColorStop(0, 'rgba(99, 102, 241, 0.35)');
  cpuGrad.addColorStop(1, 'rgba(99, 102, 241, 0.0)');

  const ramGrad = ctx.createLinearGradient(0, 0, 0, 240);
  ramGrad.addColorStop(0, 'rgba(16, 185, 129, 0.35)');
  ramGrad.addColorStop(1, 'rgba(16, 185, 129, 0.0)');

  performanceChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'CPU (User + Sys) %',
          data: [],
          borderColor: '#6366f1',
          backgroundColor: cpuGrad,
          fill: true,
          tension: 0.3,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
        {
          label: 'RAM %',
          data: [],
          borderColor: '#10b981',
          backgroundColor: ramGrad,
          fill: true,
          tension: 0.3,
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false, // Zero lag on 1-second real-time streaming
      scales: {
        x: {
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: { color: '#94a3b8', font: { size: 10 }, maxRotation: 0 }
        },
        y: {
          min: 0,
          max: 100,
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: { 
            color: '#94a3b8', 
            font: { size: 10 },
            callback: value => `${value}%`
          }
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1e293b',
          titleColor: '#f8fafc',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1,
          padding: 8,
          displayColors: true,
          callbacks: {
            label: context => `${context.dataset.label}: ${context.parsed.y}%`
          }
        }
      }
    }
  });
}

function updateChart(timestamp, cpuPercent, ramPercent) {
  if (!performanceChart) return;

  const date = new Date(timestamp * 1000);
  const timeLabel = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  performanceChart.data.labels.push(timeLabel);
  performanceChart.data.datasets[0].data.push(cpuPercent);
  performanceChart.data.datasets[1].data.push(ramPercent);

  if (performanceChart.data.labels.length > MAX_CHART_POINTS) {
    performanceChart.data.labels.shift();
    performanceChart.data.datasets[0].data.shift();
    performanceChart.data.datasets[1].data.shift();
  }

  performanceChart.update('none');
}

// Render System Info Header
function updateSystemInfo(info) {
  if (!info) return;
  window.currentSystemInfo = info;
  const cpuPart = info.cpu_brand ? `${info.cpu_brand} • ` : '';
  const line = `${info.hostname} • ${info.os} ${info.os_release} (${info.architecture}) • ${cpuPart}${info.cpu_physical_cores} Cores (${info.cpu_logical_cores} Threads)`;
  document.getElementById('host-spec-line').textContent = line;
  document.getElementById('cpu-core-count').textContent = `(${info.cpu_logical_cores} cores)`;
}

// Render Per-Core CPU Bars
function updatePerCoreBars(perCoreList) {
  const container = document.getElementById('per-core-container');
  if (!container || !perCoreList) return;

  container.innerHTML = perCoreList.map((percent, idx) => {
    const col = getStatusColor(percent);
    return `
      <div class="space-y-1">
        <div class="flex justify-between text-xs text-slate-400">
          <span class="font-mono">Core ${idx}</span>
          <span class="font-mono font-semibold ${col.text}">${percent}%</span>
        </div>
        <div class="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
          <div class="${col.bg} h-1.5 rounded-full transition-all duration-300" style="width: ${percent}%"></div>
        </div>
      </div>
    `;
  }).join('');
}

// Render Disks Table
function updateDisksTable(disks) {
  const tbody = document.getElementById('disks-table-body');
  if (!tbody || !disks || disks.length === 0) return;

  tbody.innerHTML = disks.map(d => {
    let barColor = 'bg-indigo-500';
    if (d.percent >= 85) barColor = 'bg-rose-500';
    else if (d.percent >= 70) barColor = 'bg-amber-500';

    return `
      <tr class="hover:bg-slate-800/40 transition">
        <td class="py-3 px-4 font-semibold text-white">
          <div>${d.name || d.mount}</div>
          ${d.breakdown ? `<div class="text-[10px] font-normal text-slate-400 mt-0.5">${d.breakdown}</div>` : ''}
        </td>
        <td class="py-3 px-4 font-mono text-slate-400">${d.mount}</td>
        <td class="py-3 px-4 text-slate-400 font-mono">${d.device}</td>
        <td class="py-3 px-4 uppercase text-slate-400">${d.fstype || 'N/A'}</td>
        <td class="py-3 px-4 w-44">
          <div class="flex items-center space-x-2">
            <div class="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
              <div class="${barColor} h-2 rounded-full transition-all duration-300" style="width: ${d.percent}%"></div>
            </div>
            <span class="text-xs font-mono font-medium text-slate-200 w-10 text-right">${d.percent}%</span>
          </div>
        </td>
        <td class="py-3 px-4 font-mono text-slate-300">${d.used_human} / ${d.total_human}</td>
        <td class="py-3 px-4 font-mono text-emerald-400 font-medium">${d.free_human}</td>
      </tr>
    `;
  }).join('');
}

// Render Database Cards
function updateDatabases(dbs) {
  const container = document.getElementById('databases-grid');
  if (!container) return;

  if (!dbs || dbs.length === 0) {
    container.innerHTML = `
      <div class="col-span-full bg-slate-900 border border-slate-800 rounded-2xl p-6 text-center text-slate-500 text-xs">
        No databases configured or enabled in config.yaml.
      </div>
    `;
    return;
  }

  container.innerHTML = dbs.map(db => {
    const isOnline = db.status === 'online';
    const isDisabled = db.status === 'disabled';

    let badgeClass = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
    let statusText = 'Online';
    let pulseClass = 'bg-emerald-400';

    if (isDisabled) {
      badgeClass = 'bg-slate-500/10 text-slate-400 border-slate-500/20';
      statusText = 'Disabled';
      pulseClass = 'bg-slate-400';
    } else if (!isOnline) {
      badgeClass = 'bg-rose-500/10 text-rose-400 border-rose-500/20';
      statusText = 'Offline';
      pulseClass = 'bg-rose-400';
    }

    const typeIcon = db.type === 'PostgreSQL' 
      ? `<svg class="w-6 h-6 text-sky-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14h2v2h-2zm0-10h2v8h-2z"/></svg>`
      : `<svg class="w-6 h-6 text-amber-400" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>`;

    return `
      <div data-modal-type="db" data-db-name="${db.name}" class="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-sm hover:border-indigo-500/50 hover:shadow-lg hover:shadow-indigo-500/5 transition cursor-pointer group">
        <div class="flex items-start justify-between mb-4">
          <div class="flex items-center space-x-3">
            <div class="p-2.5 rounded-xl bg-slate-800/80 border border-slate-700/50">
              ${typeIcon}
            </div>
            <div>
              <div class="flex items-center space-x-2">
                <h3 class="text-sm font-bold text-white group-hover:text-indigo-300 transition">${db.name}</h3>
                <span class="text-xs text-slate-400 font-mono">(${db.type})</span>
              </div>
              <p class="text-xs text-slate-500 font-mono">${db.version || 'Waiting for connection...'}</p>
            </div>
          </div>
          <div class="flex items-center space-x-2">
            <span class="flex items-center space-x-1.5 text-xs px-2.5 py-1 rounded-full font-medium border ${badgeClass}">
              <span class="w-1.5 h-1.5 rounded-full ${pulseClass} ${isOnline ? 'animate-pulse' : ''}"></span>
              <span>${statusText}</span>
            </span>
            <svg class="w-3.5 h-3.5 text-slate-500 group-hover:text-indigo-400 transition" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
          </div>
        </div>

        ${isOnline ? `
          <div class="grid grid-cols-3 gap-2 pt-3 border-t border-slate-800/80 text-center">
            <div class="bg-slate-800/40 rounded-xl p-2.5">
              <span class="text-[10px] text-slate-400 uppercase font-semibold block">Latency</span>
              <span class="text-sm font-mono font-bold text-emerald-400">${db.latency_ms} ms</span>
            </div>
            <div class="bg-slate-800/40 rounded-xl p-2.5">
              <span class="text-[10px] text-slate-400 uppercase font-semibold block">Connections</span>
              <span class="text-sm font-mono font-bold text-slate-200">${db.active_connections} <span class="text-xs text-slate-400 font-normal">/ ${db.total_connections}</span></span>
            </div>
            <div class="bg-slate-800/40 rounded-xl p-2.5">
              <span class="text-[10px] text-slate-400 uppercase font-semibold block">DB Size</span>
              <span class="text-sm font-mono font-bold text-slate-200">${db.database_size_human}</span>
            </div>
          </div>
        ` : `
          <div class="pt-3 border-t border-slate-800/80">
            <div class="bg-rose-500/10 border border-rose-500/20 rounded-xl p-3 text-xs text-rose-300 font-mono break-words">
              <span class="font-bold">Error:</span> ${db.error || 'Connection timed out or refused.'}
            </div>
          </div>
        `}
      </div>
    `;
  }).join('');
}

// Render Alerts in Notification Center
let currentActiveAlerts = [];

function formatRelativeTime(timestampSeconds) {
  if (!timestampSeconds) return 'Just now';
  const elapsed = Math.max(0, Math.round(Date.now() / 1000 - timestampSeconds));
  if (elapsed < 10) return 'Just now';
  if (elapsed < 60) return `${elapsed}s ago`;
  const mins = Math.floor(elapsed / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return `${hours}h ${remMins}m ago`;
}

function updateAlerts(alerts) {
  const safeAlerts = alerts || [];
  currentActiveAlerts = safeAlerts;

  const btn = document.getElementById('alert-notifications-btn');
  const badgeContainer = document.getElementById('alerts-badge-container');
  const badgeCount = document.getElementById('alerts-badge-count');
  const pingDot = document.getElementById('alerts-ping-dot');
  const statusTag = document.getElementById('alerts-status-tag');
  const listContainer = document.getElementById('alerts-dropdown-list');
  const clearResolvedBtn = document.getElementById('alerts-clear-resolved-btn');

  const firingAlerts = safeAlerts.filter(a => a.state === 'firing');
  const resolvedAlerts = safeAlerts.filter(a => a.state === 'resolved');

  const count = firingAlerts.length;
  const hasDanger = firingAlerts.some(a => a.level === 'danger');

  if (clearResolvedBtn) {
    if (resolvedAlerts.length > 0) {
      clearResolvedBtn.classList.remove('hidden');
    } else {
      clearResolvedBtn.classList.add('hidden');
    }
  }

  if (count === 0 && resolvedAlerts.length === 0) {
    // Healthy / Zero Alerts State
    if (badgeContainer) badgeContainer.classList.add('hidden');
    if (btn) {
      btn.className = 'relative flex items-center justify-center p-2 rounded-xl bg-slate-800/80 border border-slate-700/60 text-slate-400 hover:text-slate-200 hover:border-slate-600 transition shadow-sm focus:outline-none';
    }
    if (statusTag) {
      statusTag.textContent = '0 Active';
      statusTag.className = 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700/60';
    }
    if (listContainer) {
      listContainer.innerHTML = `
        <div class="py-6 px-4 text-center">
          <div class="w-10 h-10 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 mx-auto flex items-center justify-center mb-2.5">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          </div>
          <h4 class="text-xs font-bold text-slate-200">All Systems Operational</h4>
          <p class="text-[11px] text-slate-400 mt-1">Zero active alerts or threshold violations.</p>
        </div>
      `;
    }
    return;
  }

  // Active Firing Alerts State
  if (count > 0) {
    if (badgeContainer) badgeContainer.classList.remove('hidden');
    if (badgeCount) badgeCount.textContent = count > 9 ? '9+' : String(count);

    if (hasDanger) {
      if (btn) {
        btn.className = 'relative flex items-center justify-center p-2 rounded-xl bg-rose-500/10 border border-rose-500/40 text-rose-400 hover:bg-rose-500/20 hover:border-rose-400 transition shadow-sm focus:outline-none';
      }
      if (pingDot) pingDot.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75';
      if (badgeCount) badgeCount.className = 'relative inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold font-mono text-white bg-rose-600 rounded-full shadow-md';
      if (statusTag) {
        statusTag.textContent = `${count} Critical`;
        statusTag.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/30';
      }
    } else {
      if (btn) {
        btn.className = 'relative flex items-center justify-center p-2 rounded-xl bg-amber-500/10 border border-amber-500/40 text-amber-400 hover:bg-amber-500/20 hover:border-amber-400 transition shadow-sm focus:outline-none';
      }
      if (pingDot) pingDot.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75';
      if (badgeCount) badgeCount.className = 'relative inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold font-mono text-white bg-amber-500 rounded-full shadow-md';
      if (statusTag) {
        statusTag.textContent = `${count} Active`;
        statusTag.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30';
      }
    }
  } else {
    // Only resolved notifications exist
    if (badgeContainer) badgeContainer.classList.add('hidden');
    if (btn) {
      btn.className = 'relative flex items-center justify-center p-2 rounded-xl bg-slate-800/80 border border-emerald-500/40 text-emerald-400 hover:border-emerald-300 transition shadow-sm focus:outline-none';
    }
    if (statusTag) {
      statusTag.textContent = `${resolvedAlerts.length} Resolved`;
      statusTag.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
    }
  }

  if (listContainer) {
    listContainer.innerHTML = safeAlerts.map(a => {
      const isResolved = a.state === 'resolved';
      const isDanger = a.level === 'danger';

      if (isResolved) {
        const timeObj = a.timestamp ? new Date(a.timestamp * 1000) : new Date();
        const timeStr = a.time_str || timeObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const durSeconds = a.active_duration_seconds || 0;
        const durText = durSeconds > 0 ? ` (was active for ${durSeconds >= 60 ? Math.floor(durSeconds / 60) + 'm ' + (durSeconds % 60) + 's' : durSeconds + 's'})` : '';

        return `
          <div class="border border-emerald-500/40 bg-emerald-950/20 rounded-xl p-3 shadow-sm hover:border-emerald-400/60 transition">
            <div class="flex items-center justify-between mb-1.5">
              <div class="flex items-center space-x-1.5 min-w-0">
                <svg class="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                <span class="font-bold uppercase text-[11px] tracking-wider text-emerald-300 truncate">${a.source}</span>
              </div>
              <div class="flex items-center space-x-2 shrink-0">
                <span class="text-[10px] font-mono text-slate-400 bg-slate-900/80 px-1.5 py-0.5 rounded border border-slate-800">${timeStr}</span>
                <span class="text-[9px] font-mono uppercase font-bold px-1.5 py-0.5 rounded border bg-emerald-500/20 text-emerald-300 border-emerald-500/30">
                  RESOLVED
                </span>
                <button type="button" class="btn-dismiss-alert text-slate-400 hover:text-white text-xs px-1 hover:bg-slate-800 rounded transition" data-alert-key="${a.key || a.source}" title="Dismiss">×</button>
              </div>
            </div>
            <p class="text-xs text-slate-300 leading-snug pl-5 mb-2">${a.message}</p>
            <div class="flex items-center justify-between pl-5 pt-1.5 border-t border-slate-800/60 text-[10px] text-slate-500">
              <span class="flex items-center space-x-1">
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                <span>Resolved at ${timeStr}${durText}</span>
              </span>
              <span class="font-mono text-emerald-400 font-semibold">Normal</span>
            </div>
          </div>
        `;
      }

      // Firing alert
      const borderCol = isDanger ? 'border-rose-500/40 bg-rose-950/20' : 'border-amber-500/40 bg-amber-950/20';
      const tagCol = isDanger ? 'bg-rose-500/20 text-rose-400 border-rose-500/30' : 'bg-amber-500/20 text-amber-400 border-amber-500/30';
      const icon = isDanger 
        ? `<svg class="w-4 h-4 text-rose-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>`
        : `<svg class="w-4 h-4 text-amber-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`;

      const timeObj = a.timestamp ? new Date(a.timestamp * 1000) : new Date();
      const timeStr = a.time_str || timeObj.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const elapsedStr = formatRelativeTime(a.timestamp);

      const recoveringBadge = a.is_recovering 
        ? `<span class="text-[9px] font-mono text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">recovering (${a.recovery_seconds_left}s)</span>`
        : '';

      return `
        <div class="border ${borderCol} rounded-xl p-3 shadow-sm hover:border-slate-600 transition">
          <div class="flex items-center justify-between mb-1.5">
            <div class="flex items-center space-x-1.5 min-w-0">
              ${icon}
              <span class="font-bold uppercase text-[11px] tracking-wider text-white truncate">${a.source}</span>
            </div>
            <div class="flex items-center space-x-2 shrink-0">
              ${recoveringBadge}
              <span class="text-[10px] font-mono text-slate-400 bg-slate-900/80 px-1.5 py-0.5 rounded border border-slate-800">${timeStr}</span>
              <span class="text-[9px] font-mono uppercase font-bold px-1.5 py-0.5 rounded border ${tagCol}">
                ${isDanger ? 'CRITICAL' : 'WARNING'}
              </span>
            </div>
          </div>
          <p class="text-xs text-slate-300 leading-snug pl-5 mb-2">${a.message}</p>
          <div class="flex items-center justify-between pl-5 pt-1.5 border-t border-slate-800/60 text-[10px] text-slate-500">
            <span class="flex items-center space-x-1">
              <span class="w-1.5 h-1.5 rounded-full ${isDanger ? 'bg-rose-400' : 'bg-amber-400'}"></span>
              <span>${a.is_recovering ? 'Under limit — verifying recovery' : `Detected at ${timeStr}`}</span>
            </span>
            <span class="font-mono text-slate-400">${elapsedStr}</span>
          </div>
        </div>
      `;
    }).join('');

    // Attach click listeners to dismiss buttons
    listContainer.querySelectorAll('.btn-dismiss-alert').forEach(btnEl => {
      btnEl.addEventListener('click', async (e) => {
        e.stopPropagation();
        const key = btnEl.getAttribute('data-alert-key');
        try {
          await fetch('/api/alerts/clear-resolved', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: key }),
          });
        } catch (err) {}
      });
    });
  }
}

function flashPulseIndicator() {
  const dot = document.getElementById('update-pulse-indicator');
  if (dot) {
    dot.style.opacity = '1';
    setTimeout(() => {
      dot.style.opacity = '0';
    }, 350);
  }
}

// Full Metrics Snapshot Update
function handleMetricsUpdate(metrics) {
  if (!metrics || !metrics.system) return;
  flashPulseIndicator();

  const sys = metrics.system;

  // Uptime
  const uptimeEl = document.getElementById('uptime-val');
  if (uptimeEl && sys.uptime_human) {
    uptimeEl.textContent = sys.uptime_human;
  }

  // CPU (User + System total, and breakdown)
  const cpu = sys.cpu;
  if (cpu) {
    document.getElementById('cpu-total-percent').textContent = `${cpu.total_percent}%`;
    const cpuBar = document.getElementById('cpu-progress-bar');
    cpuBar.style.width = `${cpu.total_percent}%`;
    
    // Colorize CPU bar
    if (cpu.total_percent >= 85) cpuBar.className = 'bg-rose-500 h-2 rounded-full transition-all duration-300';
    else if (cpu.total_percent >= 70) cpuBar.className = 'bg-amber-500 h-2 rounded-full transition-all duration-300';
    else cpuBar.className = 'bg-indigo-500 h-2 rounded-full transition-all duration-300';

    // Activity Monitor style breakdown pills
    const userEl = document.getElementById('cpu-user-val');
    const sysEl = document.getElementById('cpu-sys-val');
    const idleEl = document.getElementById('cpu-idle-val');
    if (userEl && cpu.user_percent !== undefined) userEl.textContent = `${cpu.user_percent}%`;
    if (sysEl && cpu.system_percent !== undefined) sysEl.textContent = `${cpu.system_percent}%`;
    if (idleEl && cpu.idle_percent !== undefined) idleEl.textContent = `${cpu.idle_percent}%`;

    if (cpu.load_avg) {
      const loadLabelEl = document.getElementById('cpu-load-label');
      const loadAvgEl = document.getElementById('cpu-load-avg');
      const isWin = (window.currentSystemInfo?.os || '').toLowerCase().includes('win');
      if (isWin && cpu.process_count) {
        if (loadLabelEl) loadLabelEl.textContent = 'Procs / Threads:';
        loadAvgEl.textContent = `${cpu.process_count} / ${cpu.thread_count ? cpu.thread_count.toLocaleString() : '--'}`;
      } else {
        if (loadLabelEl) loadLabelEl.textContent = 'Load Avg:';
        loadAvgEl.textContent = cpu.load_avg.map(v => typeof v === 'number' ? v.toFixed(2) : v).join(', ');
      }
    }

    if (cpu.per_core_percent) {
      updatePerCoreBars(cpu.per_core_percent);
    }
  }

  // RAM (100% Activity Monitor Aligned)
  const ram = sys.ram;
  if (ram) {
    document.getElementById('ram-percent').textContent = `${ram.percent}%`;
    document.getElementById('ram-usage-text').textContent = `${ram.used_human} / ${ram.total_human}`;
    document.getElementById('ram-available-val').textContent = ram.available_human;
    if (document.getElementById('ram-total-val')) document.getElementById('ram-total-val').textContent = ram.total_human;
    
    // Memory Pressure Badge
    const pressureBadge = document.getElementById('ram-pressure-badge');
    if (pressureBadge && ram.memory_pressure) {
      pressureBadge.textContent = `Pressure: ${ram.memory_pressure}`;
      if (ram.memory_pressure === 'Critical') {
        pressureBadge.className = 'px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20';
      } else if (ram.memory_pressure === 'Warning') {
        pressureBadge.className = 'px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20';
      } else {
        pressureBadge.className = 'px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
      }
    }

    const ramBar = document.getElementById('ram-progress-bar');
    ramBar.style.width = `${ram.percent}%`;
    if (ram.memory_pressure === 'Critical' || ram.percent >= 95) ramBar.className = 'bg-rose-500 h-2 rounded-full transition-all duration-300';
    else if (ram.memory_pressure === 'Warning' || ram.percent >= 90) ramBar.className = 'bg-amber-500 h-2 rounded-full transition-all duration-300';
    else ramBar.className = 'bg-emerald-500 h-2 rounded-full transition-all duration-300';

    // Activity Monitor / Windows breakdown pills
    const isWin = (window.currentSystemInfo?.os || '').toLowerCase().includes('win');
    const appEl = document.getElementById('ram-app-val');
    const wiredEl = document.getElementById('ram-wired-val');
    const compEl = document.getElementById('ram-comp-val');
    const cacheEl = document.getElementById('ram-cached-val');
    const swapUsedEl = document.getElementById('ram-swap-used-val');

    const appLabel = document.getElementById('ram-pill-app-label');
    const wiredLabel = document.getElementById('ram-pill-wired-label');
    const compLabel = document.getElementById('ram-comp-label');
    const cacheLabel = document.getElementById('ram-pill-cached-label');
    const swapLabel = document.getElementById('ram-pill-swap-label');

    const appPill = document.getElementById('ram-pill-app');
    const wiredPill = document.getElementById('ram-pill-wired');
    const compPill = document.getElementById('ram-pill-comp');
    const cachePill = document.getElementById('ram-pill-cached');
    const swapPill = document.getElementById('ram-pill-swap');

    if (isWin) {
      if (appLabel) appLabel.textContent = 'In Use';
      if (wiredLabel) wiredLabel.textContent = 'Pool';
      if (compLabel) compLabel.textContent = 'Paged';
      if (cacheLabel) cacheLabel.textContent = 'Cache';
      if (swapLabel) swapLabel.textContent = 'Paging';

      if (appPill) appPill.title = 'In Use (Active Working Set)';
      if (wiredPill) wiredPill.title = 'Non-paged Pool (Kernel pinned)';
      if (compPill) compPill.title = 'Paged Pool';
      if (cachePill) cachePill.title = 'Standby System File Cache';
      if (swapPill) swapPill.title = 'Pagefile on disk';
    } else {
      if (appLabel) appLabel.textContent = 'App';
      if (wiredLabel) wiredLabel.textContent = 'Wire';
      if (compLabel) compLabel.textContent = 'Comp';
      if (cacheLabel) cacheLabel.textContent = 'Cache';
      if (swapLabel) swapLabel.textContent = 'Swap';
    }

    if (appEl && ram.app_memory_human) appEl.textContent = ram.app_memory_human;
    if (wiredEl && ram.wired_memory_human) wiredEl.textContent = ram.wired_memory_human;
    if (compEl && ram.compressed_memory_human) compEl.textContent = ram.compressed_memory_human;
    if (cacheEl && ram.cached_memory_human) cacheEl.textContent = ram.cached_memory_human;
    if (swapUsedEl && ram.swap_used_human) swapUsedEl.textContent = ram.swap_used_human;

    // Swap Card
    document.getElementById('swap-percent').textContent = `${ram.swap_percent}%`;
    document.getElementById('swap-usage-text').textContent = `${ram.swap_used_human} / ${ram.swap_total_human}`;
    document.getElementById('swap-total-val').textContent = ram.swap_total_human;
    document.getElementById('swap-progress-bar').style.width = `${ram.swap_percent}%`;
  }

  // Disk I/O & Activity (Matching Activity Monitor)
  const disk = sys.disk;
  if (disk) {
    if (document.getElementById('disk-read-rate')) document.getElementById('disk-read-rate').textContent = disk.read_rate_human;
    if (document.getElementById('disk-write-rate')) document.getElementById('disk-write-rate').textContent = disk.write_rate_human;
    if (document.getElementById('disk-read-iops')) document.getElementById('disk-read-iops').textContent = `${disk.read_iops || 0} /s`;
    if (document.getElementById('disk-write-iops')) document.getElementById('disk-write-iops').textContent = `${disk.write_iops || 0} /s`;
    if (document.getElementById('disk-total-read')) document.getElementById('disk-total-read').textContent = disk.total_read_human || '--';
    if (document.getElementById('disk-total-written')) document.getElementById('disk-total-written').textContent = disk.total_write_human || '--';
    if (document.getElementById('disk-total-read-count')) document.getElementById('disk-total-read-count').textContent = disk.total_read_count_formatted || '--';
    if (document.getElementById('disk-total-write-count')) document.getElementById('disk-total-write-count').textContent = disk.total_write_count_formatted || '--';

    if (disk.partitions) {
      updateDisksTable(disk.partitions);
    }
  }

  // Databases
  updateDatabases(metrics.databases);

  // Alerts
  updateAlerts(metrics.alerts);

  // Update Line Chart (Synchronized Total CPU and RAM %)
  updateChart(metrics.timestamp, cpu.total_percent, ram.percent);
}

// WebSocket Connection Setup
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/live`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    // Synchronize client saved cadence to server on connect
    const saved = localStorage.getItem('pulse_poll_interval');
    if (saved) {
      ws.send(JSON.stringify({ type: 'SET_INTERVAL', interval: parseFloat(saved) }));
    }
  };

  ws.onmessage = (event) => {
    // Guard against plain text heartbeat responses
    if (event.data === 'pong') return;

    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'PONG') return;

      if (msg.type === 'INITIAL_STATE') {
        updateSystemInfo(msg.system_info);
        if (msg.alert_thresholds) {
          syncAlertThresholdsUI(msg.alert_thresholds);
        }
        if (msg.poll_interval && !localStorage.getItem('pulse_poll_interval')) {
          const selectEl = document.getElementById('update-cadence-select');
          if (selectEl) selectEl.value = String(Math.round(msg.poll_interval));
        }
        if (msg.history && msg.history.length > 0) {
          window.metricsHistoryBuffer = [...msg.history];
          msg.history.slice(-60).forEach(sample => {
            const cpuPct = sample.system?.cpu?.total_percent !== undefined ? sample.system.cpu.total_percent : (sample.cpu_total || 0);
            const ramPct = sample.system?.ram?.percent !== undefined ? sample.system.ram.percent : (sample.ram_percent || 0);
            updateChart(sample.timestamp, cpuPct, ramPct);
          });
        }
        if (msg.latest) {
          if (window.metricsHistoryBuffer.length === 0) window.metricsHistoryBuffer.push(msg.latest);
          handleMetricsUpdate(msg.latest);
        }
      } else if (msg.type === 'METRIC_UPDATE') {
        window.metricsHistoryBuffer.push(msg.data);
        if (window.metricsHistoryBuffer.length > 300) window.metricsHistoryBuffer.shift();
        handleMetricsUpdate(msg.data);
        if (activeModalType) {
          updateModalLive(msg.data);
        }
      } else if (msg.type === 'INTERVAL_UPDATE') {
        const selectEl = document.getElementById('update-cadence-select');
        if (selectEl) {
          selectEl.value = String(Math.round(msg.interval));
        }
      } else if (msg.type === 'ALERTS_CONFIG_UPDATE') {
        if (msg.alerts) {
          syncAlertThresholdsUI(msg.alerts);
        }
        if (msg.active_alerts) {
          updateAlerts(msg.active_alerts);
        }
      }
    } catch (e) {
      console.error('Error handling WS message:', e);
    }
  };

  ws.onclose = () => {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = (err) => {
    ws.close();
  };
}

// Fallback fetch static info via REST API
async function loadInitialStaticInfo() {
  try {
    const res = await fetch('/api/system/info');
    const json = await res.json();
    if (json.status === 'success') {
      updateSystemInfo(json.data);
    }
  } catch (e) {
    console.error('Could not fetch static system info:', e);
  }
}

// ==========================================
// Drill-Down Brief Analytics Modal System
// With Historical Timeline (5m, 15m, 1h, 5h, 24h, All Time)
// ==========================================

let activeModalTimeline = 'live';

function formatBytesRate(bytesPerSec) {
  if (bytesPerSec === undefined || bytesPerSec === null || isNaN(bytesPerSec)) return '0 B/s';
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s'];
  let val = Math.max(0, Number(bytesPerSec));
  let idx = 0;
  while (val >= 1000 && idx < units.length - 1) {
    val /= 1000;
    idx++;
  }
  return `${val >= 100 ? val.toFixed(0) : val >= 10 ? val.toFixed(1) : val.toFixed(2)} ${units[idx]}`;
}

function formatTimelineTimestamp(ts, range) {
  if (!ts) return '--';
  const d = new Date(ts * 1000);
  if (range === 'live' || range === '5m' || range === '15m') {
    return d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  if (range === '1h' || range === '5h') {
    return d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit' });
  }
  return `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit' })}`;
}

function getTimelineStepSize(range, totalDuration) {
  switch (range) {
    case 'live':
    case '5m':
      return 60; // 1 minute
    case '15m':
      return 180; // 3 minutes
    case '1h':
      return 600; // 10 minutes
    case '5h':
      return 3600; // 1 hour
    case '24h':
      return 14400; // 4 hours
    case 'all':
      if (totalDuration <= 86400) return 14400; // 4 hours
      if (totalDuration <= 259200) return 43200; // 12 hours
      return 86400; // 24 hours (1 day)
    default:
      return 60;
  }
}

function createTimeXAxis(startTs, endTs, timelineRange) {
  const duration = Math.max(1, endTs - startTs);
  const step = getTimelineStepSize(timelineRange, duration);
  return {
    type: 'linear',
    min: startTs,
    max: endTs,
    grid: { color: 'rgba(51, 65, 85, 0.25)' },
    afterBuildTicks: (axis) => {
      const min = axis.min;
      const max = axis.max;
      const s = getTimelineStepSize(activeModalTimeline, max - min);
      const firstTick = Math.ceil(min / s) * s;
      const ticks = [];
      for (let t = firstTick; t <= max; t += s) {
        ticks.push({ value: t, label: formatTimelineTimestamp(t, activeModalTimeline) });
      }
      axis.ticks = ticks;
    },
    ticks: {
      color: '#64748b',
      stepSize: step,
      font: { size: 10 },
      callback: (val) => formatTimelineTimestamp(val, activeModalTimeline)
    }
  };
}

function updateTimelinePillsUI(activeRange) {
  document.querySelectorAll('#modal-timeline-selector .timeline-pill').forEach(btn => {
    const r = btn.getAttribute('data-timeline-range');
    if (r === activeRange) {
      if (r === 'live') {
        btn.className = 'timeline-pill px-2.5 py-1 rounded-lg font-medium transition bg-emerald-600 text-white shadow-sm flex items-center space-x-1.5';
      } else {
        btn.className = 'timeline-pill px-2.5 py-1 rounded-lg font-medium transition bg-indigo-600 text-white shadow-sm flex items-center space-x-1.5';
      }
    } else {
      btn.className = 'timeline-pill px-2.5 py-1 rounded-lg font-medium transition text-slate-400 hover:text-white hover:bg-slate-800 flex items-center space-x-1.5';
    }
  });
}

function updateTimelineStatusBadge(range, count = null, isLive = false) {
  const dot = document.getElementById('modal-timeline-dot');
  const text = document.getElementById('modal-timeline-text');
  if (!dot || !text) return;
  if (isLive || range === 'live') {
    dot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
    text.textContent = 'Live Streaming (Oscilloscope)';
  } else {
    dot.className = 'w-2 h-2 rounded-full bg-amber-400';
    text.textContent = count !== null
      ? `Frozen Snapshot (${range.toUpperCase()}) • ${count} points`
      : `Loading ${range.toUpperCase()} data...`;
  }
}

function closeAnalyticsModal() {
  const modal = document.getElementById('analytics-modal');
  const content = document.getElementById('analytics-modal-content');
  if (!modal || !content) return;

  modal.classList.add('opacity-0');
  content.classList.remove('scale-100');
  content.classList.add('scale-95');

  setTimeout(() => {
    modal.classList.add('hidden');
    if (modalChart) {
      modalChart.destroy();
      modalChart = null;
    }
    activeModalType = null;
    activeModalParam = null;
    activeModalTimeline = 'live';
  }, 200);
}

function renderModalChartFromData(type, param, timelineRange, points, summary = null, rangeStartTime = null, rangeEndTime = null) {
  const titleEl = document.getElementById('modal-title');
  const subtitleEl = document.getElementById('modal-subtitle');
  const badgeEl = document.getElementById('modal-badge');
  const iconContainer = document.getElementById('modal-icon-container');
  const statCurrent = document.getElementById('modal-stat-current');
  const statAvg = document.getElementById('modal-stat-avg');
  const statPeak = document.getElementById('modal-stat-peak');
  const statLow = document.getElementById('modal-stat-low');
  const subBreakdown = document.getElementById('modal-sub-breakdown');

  if (modalChart) {
    modalChart.destroy();
    modalChart = null;
  }

  // Update dynamic chart heading and time window text
  const headingEl = document.getElementById('modal-chart-heading');
  const windowTextEl = document.getElementById('modal-chart-window-text');
  const rangeTitles = {
    'live': 'Telemetry History — Live Streaming (5m Window)',
    '5m': 'Telemetry History — Last 5 Minutes (Frozen Snapshot)',
    '15m': 'Telemetry History — Last 15 Minutes (Frozen Snapshot)',
    '1h': 'Telemetry History — Last 1 Hour (Frozen Snapshot)',
    '5h': 'Telemetry History — Last 5 Hours (Frozen Snapshot)',
    '24h': 'Telemetry History — Last 24 Hours (Frozen Snapshot)',
    'all': 'Telemetry History — All Time History (Frozen Snapshot)'
  };

  if (headingEl) {
    headingEl.textContent = rangeTitles[timelineRange] || `Telemetry History (${timelineRange.toUpperCase()})`;
  }

  // Normalized data getters supporting both live buffer and timeline API payloads
  const getPointTs = p => p.timestamp || p.bucket_ts || (p.x !== undefined ? p.x : 0);
  const getPointCpuTotal = p => p.cpu_total !== undefined ? p.cpu_total : (p.system?.cpu?.total_percent !== undefined ? p.system.cpu.total_percent : (p.y !== undefined ? p.y : 0));
  const getPointCpuUser = p => p.cpu_user !== undefined ? p.cpu_user : (p.system?.cpu?.user_percent || 0);
  const getPointCpuSys = p => p.cpu_system !== undefined ? p.cpu_system : (p.system?.cpu?.system_percent || 0);
  const getPointRamPct = p => p.ram_percent !== undefined ? p.ram_percent : (p.system?.ram?.percent !== undefined ? p.system.ram.percent : (p.y !== undefined ? p.y : 0));
  const getPointSwapPct = p => p.swap_percent !== undefined ? p.swap_percent : (p.system?.ram?.swap_percent !== undefined ? p.system.ram.swap_percent : (p.y !== undefined ? p.y : 0));
  const getPointDiskReadSec = p => p.disk_read_sec !== undefined ? p.disk_read_sec : (p.system?.disk?.read_bytes_sec || 0);
  const getPointDiskWriteSec = p => p.disk_write_sec !== undefined ? p.disk_write_sec : (p.system?.disk?.write_bytes_sec || 0);
  const getPointDatabases = p => p.databases || [];

  const nowTs = Math.round(Date.now() / 1000);
  let startTs = nowTs - 300;
  let endTs = nowTs;

  if (timelineRange === 'live') {
    startTs = nowTs - 300;
    endTs = nowTs;
  } else if (rangeStartTime !== null && rangeStartTime !== undefined && rangeEndTime !== null && rangeEndTime !== undefined) {
    startTs = Math.round(rangeStartTime);
    endTs = Math.round(rangeEndTime);
  } else if (points && points.length >= 2) {
    startTs = Math.round(getPointTs(points[0]));
    endTs = Math.round(getPointTs(points[points.length - 1]));
    if (startTs >= endTs) startTs = endTs - 300;
  }

  // Ensure live window only loads relevant points without ancient history bloat
  const chartPoints = (points || []).length > 0
    ? (timelineRange === 'live'
        ? (points || []).filter(p => getPointTs(p) >= (startTs - 15))
        : (points || []))
    : [];

  if (windowTextEl) {
    const firstStr = formatTimelineTimestamp(startTs, timelineRange);
    const lastStr = formatTimelineTimestamp(endTs, timelineRange);
    windowTextEl.textContent = timelineRange === 'live'
      ? `${firstStr} → ${lastStr}`
      : `${firstStr} → ${lastStr} (Frozen)`;
  }

  const latestLive = (window.metricsHistoryBuffer && window.metricsHistoryBuffer.length > 0)
    ? window.metricsHistoryBuffer[window.metricsHistoryBuffer.length - 1]
    : {};

  const ctx = document.getElementById('modalDetailedChart').getContext('2d');
  let datasets = [];
  let scales = {
    x: createTimeXAxis(startTs, endTs, timelineRange),
    y: {
      grid: { color: 'rgba(51, 65, 85, 0.25)' },
      ticks: { color: '#64748b', font: { size: 10 } }
    }
  };

  if (type === 'cpu') {
    titleEl.textContent = 'CPU Performance Analytics';
    subtitleEl.textContent = 'Real-time multi-core workload distribution and process states';
    badgeEl.textContent = 'Host CPU';
    badgeEl.className = 'text-xs px-2.5 py-0.5 rounded-full font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20';
    iconContainer.className = 'w-10 h-10 rounded-xl bg-indigo-500/10 text-indigo-400 flex items-center justify-center border border-indigo-500/20';
    iconContainer.innerHTML = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"/></svg>`;

    const totalCoords = chartPoints.map(p => ({ x: getPointTs(p), y: getPointCpuTotal(p) }));
    const userCoords = chartPoints.map(p => ({ x: getPointTs(p), y: getPointCpuUser(p) }));
    const sysCoords = chartPoints.map(p => ({ x: getPointTs(p), y: getPointCpuSys(p) }));
    const totalVals = totalCoords.map(c => c.y);

    if (summary && summary.cpu) {
      statCurrent.textContent = `${summary.cpu.cur !== undefined ? summary.cpu.cur : (totalVals[totalVals.length - 1] || 0)}%`;
      statAvg.textContent = `${summary.cpu.avg || 0}%`;
      statPeak.textContent = `${summary.cpu.peak || 0}%`;
      statLow.textContent = `${summary.cpu.low || 0}%`;
    } else {
      const cur = totalVals[totalVals.length - 1] || 0;
      const avg = totalVals.length ? (totalVals.reduce((a, b) => a + b, 0) / totalVals.length).toFixed(1) : 0;
      const peak = totalVals.length ? Math.max(...totalVals).toFixed(1) : 0;
      const low = totalVals.length ? Math.min(...totalVals).toFixed(1) : 0;
      statCurrent.textContent = `${cur}%`;
      statAvg.textContent = `${avg}%`;
      statPeak.textContent = `${peak}%`;
      statLow.textContent = `${low}%`;
    }

    scales.y.suggestedMin = 0;
    scales.y.suggestedMax = 100;
    scales.y.ticks.callback = (val) => `${val}%`;

    datasets = [
      {
        label: 'Total CPU %',
        data: totalCoords,
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99, 102, 241, 0.15)',
        fill: true,
        tension: 0.25,
        borderWidth: 2,
        pointRadius: 0
      },
      {
        label: 'User %',
        data: userCoords,
        borderColor: '#a855f7',
        borderWidth: 1.5,
        tension: 0.25,
        pointRadius: 0
      },
      {
        label: 'System %',
        data: sysCoords,
        borderColor: '#38bdf8',
        borderWidth: 1.5,
        tension: 0.25,
        pointRadius: 0
      }
    ];

    const cpuObj = latestLive.system?.cpu || {};
    const perCore = cpuObj.per_core_percent || [];
    const loadAvg = cpuObj.load_avg || [0, 0, 0];

    const isWin = (window.currentSystemInfo?.os || '').toLowerCase().includes('win');
    let loadAvgLabel = `Load Avg: ${loadAvg.map(v => typeof v === 'number' ? v.toFixed(2) : v).join(', ')}`;
    if (isWin && cpuObj.process_count) {
      loadAvgLabel = `Processes: ${cpuObj.process_count} • Threads: ${cpuObj.thread_count ? cpuObj.thread_count.toLocaleString() : '--'}${cpuObj.handle_count ? ' • Handles: ' + cpuObj.handle_count.toLocaleString() : ''}`;
    }

    subBreakdown.innerHTML = `
      <div class="bg-slate-800/30 border border-slate-800 rounded-2xl p-4">
        <div class="flex items-center justify-between mb-3">
          <span class="text-xs uppercase font-semibold text-slate-300">Current Per-Core Workload Distribution</span>
          <span class="text-xs font-mono text-slate-400">${loadAvgLabel}</span>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
          ${perCore.map((p, idx) => {
            const col = getStatusColor(p);
            return `
              <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2 text-center">
                <span class="text-[10px] text-slate-400 block font-mono">Core ${idx}</span>
                <span class="text-xs font-bold font-mono ${col.text}">${p}%</span>
                <div class="w-full bg-slate-700 rounded-full h-1 mt-1 overflow-hidden">
                  <div class="${col.bg} h-1 rounded-full" style="width: ${p}%"></div>
                </div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;
  } else if (type === 'ram') {
    titleEl.textContent = 'Memory (RAM) Architecture Analytics';
    subtitleEl.textContent = 'Kernel memory paging, unified architecture & memory pressure';
    badgeEl.textContent = `Pressure: ${latestLive.system?.ram?.memory_pressure || 'Normal'}`;
    badgeEl.className = 'text-xs px-2.5 py-0.5 rounded-full font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
    iconContainer.className = 'w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400 flex items-center justify-center border border-emerald-500/20';
    iconContainer.innerHTML = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 14h-2v-2h2v2zm0-4h-2V7h2v5z"/></svg>`;

    const ramCoords = chartPoints.map(p => ({ x: getPointTs(p), y: getPointRamPct(p) }));
    const ramVals = ramCoords.map(c => c.y);

    if (summary && summary.ram) {
      statCurrent.textContent = latestLive.system?.ram?.used_human || `${summary.ram.cur || 0}%`;
      statAvg.textContent = `${summary.ram.avg || 0}%`;
      statPeak.textContent = `${summary.ram.peak || 0}%`;
      statLow.textContent = `${summary.ram.low || 0}%`;
    } else {
      const cur = ramVals[ramVals.length - 1] || 0;
      const avg = ramVals.length ? (ramVals.reduce((a, b) => a + b, 0) / ramVals.length).toFixed(1) : 0;
      const peak = ramVals.length ? Math.max(...ramVals).toFixed(1) : 0;
      const low = ramVals.length ? Math.min(...ramVals).toFixed(1) : 0;
      statCurrent.textContent = `${latestLive.system?.ram?.used_human || cur + '%'}`;
      statAvg.textContent = `${avg}%`;
      statPeak.textContent = `${peak}%`;
      statLow.textContent = `${low}%`;
    }

    scales.y.suggestedMin = 0;
    scales.y.suggestedMax = 100;
    scales.y.ticks.callback = (val) => `${val}%`;

    datasets = [
      {
        label: 'Memory Used %',
        data: ramCoords,
        borderColor: '#10b981',
        backgroundColor: 'rgba(16, 185, 129, 0.15)',
        fill: true,
        tension: 0.25,
        borderWidth: 2,
        pointRadius: 0
      }
    ];

    const ram = latestLive.system?.ram || {};
    const osType = (window.currentSystemInfo?.os || '').toLowerCase();
    let ramSubtitle = 'Virtual Memory Counters';
    let breakdownCards = '';

    if (osType.includes('darwin') || osType.includes('mac')) {
      ramSubtitle = 'Activity Monitor Virtual Memory Counters';
    } else if (osType.includes('linux')) {
      ramSubtitle = 'Linux Kernel Memory & Buffer Cache Counters';
    } else if (osType.includes('win')) {
      ramSubtitle = 'Windows Memory Manager Counters';
    }

    if (osType.includes('win')) {
      breakdownCards = `
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">In Use (Working Set)</span>
          <span class="font-mono font-bold text-emerald-400">${ram.app_memory_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Non-paged Pool</span>
          <span class="font-mono font-bold text-amber-400">${ram.wired_memory_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Paged Pool</span>
          <span class="font-mono font-bold text-purple-400">${ram.compressed_memory_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">System Cache</span>
          <span class="font-mono font-bold text-slate-200">${ram.cached_memory_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Physical RAM</span>
          <span class="font-mono font-bold text-slate-200">${ram.total_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Available RAM</span>
          <span class="font-mono font-bold text-emerald-300">${ram.available_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Pagefile on Disk</span>
          <span class="font-mono font-bold text-sky-400">${ram.swap_used_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Committed Memory</span>
          <span class="font-mono font-bold text-indigo-400">${ram.commit_total_human && ram.commit_limit_human ? ram.commit_total_human + ' / ' + ram.commit_limit_human : (ram.memory_pressure || 'Normal')}</span>
        </div>
      `;
    } else {
      breakdownCards = `
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">App Memory</span>
          <span class="font-mono font-bold text-emerald-400">${ram.app_memory_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Wired Memory</span>
          <span class="font-mono font-bold text-amber-400">${ram.wired_memory_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Compressed</span>
          <span class="font-mono font-bold text-purple-400">${ram.compressed_memory_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Cached Files</span>
          <span class="font-mono font-bold text-slate-200">${ram.cached_memory_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Physical RAM</span>
          <span class="font-mono font-bold text-slate-200">${ram.total_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Available Free</span>
          <span class="font-mono font-bold text-emerald-300">${ram.available_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Swap Used</span>
          <span class="font-mono font-bold text-sky-400">${ram.swap_used_human || '--'}</span>
        </div>
        <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
          <span class="text-[10px] text-slate-400 uppercase block">Memory Pressure</span>
          <span class="font-mono font-bold text-emerald-400">${ram.memory_pressure || 'Normal'}</span>
        </div>
      `;
    }

    subBreakdown.innerHTML = `
      <div class="bg-slate-800/30 border border-slate-800 rounded-2xl p-4">
        <span class="text-xs uppercase font-semibold text-slate-300 block mb-3">${ramSubtitle}</span>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-center text-xs">
          ${breakdownCards}
        </div>
      </div>
    `;
  } else if (type === 'disk') {
    titleEl.textContent = 'Disk Activity & Throughput Analytics';
    subtitleEl.textContent = 'Real-time read/write bandwidth and IO operations';
    badgeEl.textContent = 'Storage I/O';
    badgeEl.className = 'text-xs px-2.5 py-0.5 rounded-full font-semibold bg-sky-500/10 text-sky-400 border border-sky-500/20';
    iconContainer.className = 'w-10 h-10 rounded-xl bg-sky-500/10 text-sky-400 flex items-center justify-center border border-sky-500/20';
    iconContainer.innerHTML = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2 1.5 3 3.5 3h9c2 0 3.5-1 3.5-3V7c0-2-1.5-3-3.5-3h-9C5.5 4 4 5 4 7zm0 5h16"/></svg>`;

    const readCoords = chartPoints.map(p => ({ x: getPointTs(p), y: Number((getPointDiskReadSec(p) / 1048576).toFixed(2)) }));
    const writeCoords = chartPoints.map(p => ({ x: getPointTs(p), y: Number((getPointDiskWriteSec(p) / 1048576).toFixed(2)) }));
    const readMBVals = readCoords.map(c => c.y);
    const writeMBVals = writeCoords.map(c => c.y);

    if (summary && summary.disk) {
      statCurrent.textContent = formatBytesRate(summary.disk.cur_read_sec || 0);
      statAvg.textContent = `Write: ${formatBytesRate(summary.disk.avg_write_sec || 0)}`;
      statPeak.textContent = `Peak R: ${formatBytesRate(summary.disk.peak_read_sec || 0)}`;
      statLow.textContent = `Peak W: ${formatBytesRate(summary.disk.peak_write_sec || 0)}`;
    } else {
      const curRead = latestLive.system?.disk?.read_rate_human || '0 B/s';
      const curWrite = latestLive.system?.disk?.write_rate_human || '0 B/s';
      const peakRead = readMBVals.length ? Math.max(...readMBVals).toFixed(2) : 0;
      const peakWrite = writeMBVals.length ? Math.max(...writeMBVals).toFixed(2) : 0;
      statCurrent.textContent = curRead;
      statAvg.textContent = `Write: ${curWrite}`;
      statPeak.textContent = `Peak R: ${peakRead} MB/s`;
      statLow.textContent = `Peak W: ${peakWrite} MB/s`;
    }

    scales.y.ticks.callback = (val) => `${val} MB/s`;

    datasets = [
      {
        label: 'Read Rate (MB/s)',
        data: readCoords,
        borderColor: '#38bdf8',
        backgroundColor: 'rgba(56, 189, 248, 0.15)',
        fill: true,
        tension: 0.25,
        borderWidth: 2,
        pointRadius: 0
      },
      {
        label: 'Write Rate (MB/s)',
        data: writeCoords,
        borderColor: '#f59e0b',
        backgroundColor: 'rgba(245, 158, 11, 0.15)',
        fill: true,
        tension: 0.25,
        borderWidth: 2,
        pointRadius: 0
      }
    ];

    const disk = latestLive.system?.disk || {};
    subBreakdown.innerHTML = `
      <div class="bg-slate-800/30 border border-slate-800 rounded-2xl p-4">
        <span class="text-xs uppercase font-semibold text-slate-300 block mb-3">Lifetime Disk Statistics & IOPS</span>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-center text-xs">
          <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
            <span class="text-[10px] text-slate-400 uppercase block">Data Read</span>
            <span class="font-mono font-bold text-sky-400">${disk.total_read_human || '--'}</span>
          </div>
          <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
            <span class="text-[10px] text-slate-400 uppercase block">Data Written</span>
            <span class="font-mono font-bold text-amber-400">${disk.total_write_human || '--'}</span>
          </div>
          <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
            <span class="text-[10px] text-slate-400 uppercase block">Read IOPS</span>
            <span class="font-mono font-bold text-sky-300">${disk.read_iops || 0} /s</span>
          </div>
          <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
            <span class="text-[10px] text-slate-400 uppercase block">Write IOPS</span>
            <span class="font-mono font-bold text-amber-300">${disk.write_iops || 0} /s</span>
          </div>
        </div>
      </div>
    `;
  } else if (type === 'swap') {
    titleEl.textContent = 'Swap Memory Analytics';
    subtitleEl.textContent = 'Paging file capacity and memory swap exhaustion';
    badgeEl.textContent = 'Virtual Memory';
    badgeEl.className = 'text-xs px-2.5 py-0.5 rounded-full font-semibold bg-purple-500/10 text-purple-400 border border-purple-500/20';
    iconContainer.className = 'w-10 h-10 rounded-xl bg-purple-500/10 text-purple-400 flex items-center justify-center border border-purple-500/20';
    iconContainer.innerHTML = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/></svg>`;

    const swapCoords = chartPoints.map(p => ({ x: getPointTs(p), y: getPointSwapPct(p) }));
    const swapVals = swapCoords.map(c => c.y);

    if (summary && summary.swap) {
      statCurrent.textContent = latestLive.system?.ram?.swap_used_human || `${summary.swap.cur || 0}%`;
      statAvg.textContent = `${summary.swap.avg || 0}%`;
      statPeak.textContent = `${summary.swap.peak || 0}%`;
      statLow.textContent = `${summary.swap.low || 0}%`;
    } else {
      const cur = swapVals[swapVals.length - 1] || 0;
      const avg = swapVals.length ? (swapVals.reduce((a, b) => a + b, 0) / swapVals.length).toFixed(1) : 0;
      const peak = swapVals.length ? Math.max(...swapVals).toFixed(1) : 0;
      const low = swapVals.length ? Math.min(...swapVals).toFixed(1) : 0;
      statCurrent.textContent = latestLive.system?.ram?.swap_used_human || `${cur}%`;
      statAvg.textContent = `${avg}%`;
      statPeak.textContent = `${peak}%`;
      statLow.textContent = `${low}%`;
    }

    scales.y.suggestedMin = 0;
    scales.y.suggestedMax = 100;
    scales.y.ticks.callback = (val) => `${val}%`;

    datasets = [
      {
        label: 'Swap Used %',
        data: swapCoords,
        borderColor: '#a855f7',
        backgroundColor: 'rgba(168, 85, 247, 0.15)',
        fill: true,
        tension: 0.25,
        borderWidth: 2,
        pointRadius: 0
      }
    ];

    const ram = latestLive.system?.ram || {};
    subBreakdown.innerHTML = `
      <div class="bg-slate-800/30 border border-slate-800 rounded-2xl p-4">
        <span class="text-xs uppercase font-semibold text-slate-300 block mb-3">Swap Disk Partition Allocation</span>
        <div class="grid grid-cols-3 gap-2.5 text-center text-xs">
          <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
            <span class="text-[10px] text-slate-400 uppercase block">Swap Used</span>
            <span class="font-mono font-bold text-purple-400">${ram.swap_used_human || '--'}</span>
          </div>
          <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
            <span class="text-[10px] text-slate-400 uppercase block">Total Swap Size</span>
            <span class="font-mono font-bold text-slate-200">${ram.swap_total_human || '--'}</span>
          </div>
          <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
            <span class="text-[10px] text-slate-400 uppercase block">Swap Percentage</span>
            <span class="font-mono font-bold text-purple-300">${ram.swap_percent || 0}%</span>
          </div>
        </div>
      </div>
    `;
  } else if (type === 'db') {
    const liveDbs = latestLive.databases || [];
    const db = liveDbs.find(d => d.name === param) || liveDbs[0] || {};

    titleEl.textContent = `${db.name || 'Database'} Telemetry`;
    subtitleEl.textContent = `${db.version || db.type || 'Database Engine'} • Historical query latency and connections`;
    badgeEl.textContent = db.status ? db.status.toUpperCase() : 'UNKNOWN';
    badgeEl.className = db.status === 'online'
      ? 'text-xs px-2.5 py-0.5 rounded-full font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
      : 'text-xs px-2.5 py-0.5 rounded-full font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20';

    iconContainer.className = 'w-10 h-10 rounded-xl bg-amber-500/10 text-amber-400 flex items-center justify-center border border-amber-500/20';
    iconContainer.innerHTML = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"/></svg>`;

    const latCoords = chartPoints.map(p => {
      const match = getPointDatabases(p).find(d => d.name === (db.name || param));
      return { x: getPointTs(p), y: match && typeof match.latency_ms === 'number' ? match.latency_ms : 0 };
    });

    const connCoords = chartPoints.map(p => {
      const match = getPointDatabases(p).find(d => d.name === (db.name || param));
      return { x: getPointTs(p), y: match && typeof match.active_connections === 'number' ? match.active_connections : 0 };
    });

    const latVals = latCoords.map(c => c.y);
    const curLat = latVals[latVals.length - 1] || 0;
    const avgLat = latVals.length ? (latVals.reduce((a, b) => a + b, 0) / latVals.length).toFixed(2) : 0;
    const peakLat = latVals.length ? Math.max(...latVals).toFixed(2) : 0;

    statCurrent.textContent = `${curLat} ms`;
    statAvg.textContent = `${avgLat} ms`;
    statPeak.textContent = `${peakLat} ms`;
    statLow.textContent = `${db.active_connections || 0} conns`;

    scales = {
      x: createTimeXAxis(startTs, endTs, timelineRange),
      y: {
        type: 'linear',
        position: 'left',
        grid: { color: 'rgba(51, 65, 85, 0.25)' },
        ticks: { color: '#10b981', font: { size: 10 }, callback: (v) => `${v} ms` }
      },
      y1: {
        type: 'linear',
        position: 'right',
        grid: { drawOnChartArea: false },
        ticks: { color: '#38bdf8', font: { size: 10 }, stepSize: 1 }
      }
    };

    datasets = [
      {
        label: 'Latency (ms)',
        data: latCoords,
        borderColor: '#10b981',
        backgroundColor: 'rgba(16, 185, 129, 0.15)',
        fill: true,
        yAxisID: 'y',
        tension: 0.25,
        borderWidth: 2,
        pointRadius: 0
      },
      {
        label: 'Connections',
        data: connCoords,
        borderColor: '#38bdf8',
        yAxisID: 'y1',
        tension: 0.25,
        borderWidth: 2,
        pointRadius: 0
      }
    ];

    subBreakdown.innerHTML = `
      <div class="bg-slate-800/30 border border-slate-800 rounded-2xl p-4">
        <span class="text-xs uppercase font-semibold text-slate-300 block mb-3">${db.name || 'Database'} Instance Specs</span>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-center text-xs">
          <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
            <span class="text-[10px] text-slate-400 uppercase block">Database Size</span>
            <span class="font-mono font-bold text-slate-200">${db.database_size_human || '--'}</span>
          </div>
          <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
            <span class="text-[10px] text-slate-400 uppercase block">Active / Max Conns</span>
            <span class="font-mono font-bold text-sky-400">${db.active_connections !== undefined ? db.active_connections : '--'} / ${db.total_connections !== undefined ? db.total_connections : '--'}</span>
          </div>
          <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
            <span class="text-[10px] text-slate-400 uppercase block">Roundtrip Latency</span>
            <span class="font-mono font-bold text-emerald-400">${db.latency_ms !== undefined && db.latency_ms !== null ? db.latency_ms + ' ms' : '--'}</span>
          </div>
          <div class="bg-slate-800/60 border border-slate-700/40 rounded-xl p-2.5">
            <span class="text-[10px] text-slate-400 uppercase block">Health State</span>
            <span class="font-mono font-bold ${db.status === 'online' ? 'text-emerald-400' : 'text-rose-400'}">${(db.status || 'unknown').toUpperCase()}</span>
          </div>
        </div>
      </div>
    `;
  }

  modalChart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
      plugins: {
        legend: {
          labels: { color: '#94a3b8', font: { size: 11 } }
        },
        tooltip: {
          backgroundColor: '#0f172a',
          titleColor: '#f8fafc',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1,
          padding: 10,
          callbacks: {
            title: (items) => {
              if (!items || !items.length) return '';
              const xVal = items[0].parsed.x;
              return formatTimelineTimestamp(xVal, activeModalTimeline);
            },
            label: (context) => {
              const label = context.dataset.label || '';
              const val = context.parsed.y;
              if (val === null || val === undefined) return label;
              if (activeModalType === 'cpu' || activeModalType === 'ram' || activeModalType === 'swap') {
                return `${label}: ${val}%`;
              }
              if (activeModalType === 'disk') {
                return `${label}: ${val} MB/s`;
              }
              if (activeModalType === 'db') {
                if (context.datasetIndex === 0) return `${label}: ${val} ms`;
                return `${label}: ${val} conns`;
              }
              return `${label}: ${val}`;
            }
          }
        }
      },
      scales: scales
    }
  });
}

async function switchModalTimeline(range) {
  if (!activeModalType) return;
  activeModalTimeline = range;
  updateTimelinePillsUI(range);

  if (range === 'live') {
    updateTimelineStatusBadge('live', null, true);
    if (!window.metricsHistoryBuffer || window.metricsHistoryBuffer.length < 100) {
      try {
        const res = await fetch('/api/metrics/timeline?range=5m&max_points=300');
        if (res.ok) {
          const data = await res.json();
          if (data.status === 'success' && data.points && data.points.length > 0) {
            window.metricsHistoryBuffer = data.points;
          }
        }
      } catch (e) {
        console.error('Could not fetch live baseline:', e);
      }
    }
    const history = (window.metricsHistoryBuffer && window.metricsHistoryBuffer.length > 0)
      ? window.metricsHistoryBuffer
      : [];
    renderModalChartFromData(activeModalType, activeModalParam, 'live', history, null);
    return;
  }

  // Any other range: '5m', '15m', '1h', '5h', '24h', 'all' -> Completely Frozen Historical Snapshot!
  updateTimelineStatusBadge(range, null, false);
  try {
    const res = await fetch(`/api/metrics/timeline?range=${encodeURIComponent(range)}&max_points=120`);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    }
    const data = await res.json();
    if (data.status === 'success') {
      updateTimelineStatusBadge(range, data.count, false);
      renderModalChartFromData(activeModalType, activeModalParam, range, data.points || [], data.summary, data.start_time, data.end_time);
    }
  } catch (e) {
    console.error('Failed to load historical timeline:', e);
    const text = document.getElementById('modal-timeline-text');
    if (text) text.textContent = `Timeline API error — check server logs`;
    const history = (window.metricsHistoryBuffer && window.metricsHistoryBuffer.length > 0)
      ? window.metricsHistoryBuffer
      : [];
    renderModalChartFromData(activeModalType, activeModalParam, 'live', history, null);
  }
}

function openAnalyticsModal(type, param = null) {
  const modal = document.getElementById('analytics-modal');
  const content = document.getElementById('analytics-modal-content');
  if (!modal || !content) return;

  activeModalType = type;
  activeModalParam = param;
  activeModalTimeline = 'live';

  updateTimelinePillsUI('live');
  updateTimelineStatusBadge('live', null, true);

  // If local buffer has fewer than 100 points, immediately fetch 5m from API to fill live 5-minute window
  if (!window.metricsHistoryBuffer || window.metricsHistoryBuffer.length < 100) {
    fetch('/api/metrics/timeline?range=5m&max_points=300')
      .then(r => r.json())
      .then(data => {
        if (data.status === 'success' && data.points && data.points.length > 0) {
          window.metricsHistoryBuffer = data.points;
          if (activeModalTimeline === 'live' && modalChart) {
            renderModalChartFromData(type, param, 'live', window.metricsHistoryBuffer, data.summary, data.start_time, data.end_time);
          }
        }
      })
      .catch(() => {});
  }

  const history = window.metricsHistoryBuffer && window.metricsHistoryBuffer.length > 0
    ? window.metricsHistoryBuffer
    : [];

  renderModalChartFromData(type, param, 'live', history, null);

  // Reveal modal with smooth animation
  modal.classList.remove('hidden');
  requestAnimationFrame(() => {
    modal.classList.remove('opacity-0');
    content.classList.remove('scale-95');
    content.classList.add('scale-100');
  });
}

function updateModalLive(metric) {
  if (!modalChart || !activeModalType || !metric) return;
  
  // FROZEN GUARANTEE: If ANY historical range is selected (5m, 15m, 1h, 5h, 24h, all), DO NOT touch the chart!
  if (activeModalTimeline !== 'live') return;

  const now = Math.round(metric.timestamp || (Date.now() / 1000));
  const minTs = now - 300;

  // 1. Advance both physical boundaries in unison
  modalChart.options.scales.x.min = minTs;
  modalChart.options.scales.x.max = now;

  // 2. Append new Cartesian coordinate to datasets
  if (activeModalType === 'cpu') {
    const total = metric.system?.cpu?.total_percent || 0;
    const user = metric.system?.cpu?.user_percent || 0;
    const sys = metric.system?.cpu?.system_percent || 0;

    modalChart.data.datasets[0].data.push({ x: now, y: total });
    if (modalChart.data.datasets[1]) modalChart.data.datasets[1].data.push({ x: now, y: user });
    if (modalChart.data.datasets[2]) modalChart.data.datasets[2].data.push({ x: now, y: sys });

    const statCurrent = document.getElementById('modal-stat-current');
    if (statCurrent) statCurrent.textContent = `${total}%`;
  } else if (activeModalType === 'ram') {
    const ramPct = metric.system?.ram?.percent || 0;
    modalChart.data.datasets[0].data.push({ x: now, y: ramPct });

    const statCurrent = document.getElementById('modal-stat-current');
    if (statCurrent) statCurrent.textContent = `${metric.system?.ram?.used_human || '0 GB'}`;
  } else if (activeModalType === 'disk') {
    const rMB = Number(((metric.system?.disk?.read_bytes_sec || 0) / 1000000).toFixed(2));
    const wMB = Number(((metric.system?.disk?.write_bytes_sec || 0) / 1000000).toFixed(2));

    modalChart.data.datasets[0].data.push({ x: now, y: rMB });
    if (modalChart.data.datasets[1]) modalChart.data.datasets[1].data.push({ x: now, y: wMB });

    const statCurrent = document.getElementById('modal-stat-current');
    if (statCurrent) statCurrent.textContent = metric.system?.disk?.read_rate_human || '0 B/s';
  } else if (activeModalType === 'swap') {
    const swapPct = metric.system?.ram?.swap_percent || 0;
    modalChart.data.datasets[0].data.push({ x: now, y: swapPct });

    const statCurrent = document.getElementById('modal-stat-current');
    if (statCurrent) statCurrent.textContent = metric.system?.ram?.swap_used_human || '0 B';
  } else if (activeModalType === 'db') {
    const db = (metric.databases || []).find(d => d.name === activeModalParam);
    if (db) {
      modalChart.data.datasets[0].data.push({ x: now, y: db.latency_ms || 0 });
      if (modalChart.data.datasets[1]) modalChart.data.datasets[1].data.push({ x: now, y: db.active_connections || 0 });

      const statCurrent = document.getElementById('modal-stat-current');
      if (statCurrent) statCurrent.textContent = `${db.latency_ms} ms`;
    }
  }

  // 3. Prune points older than sliding window (with small safety buffer)
  const pruneThreshold = minTs - 10;
  modalChart.data.datasets.forEach(ds => {
    while (ds.data.length > 0 && ds.data[0].x < pruneThreshold) {
      ds.data.shift();
    }
  });

  // 4. Update window range text dynamically
  const windowTextEl = document.getElementById('modal-chart-window-text');
  if (windowTextEl) {
    const firstStr = formatTimelineTimestamp(minTs, 'live');
    const lastStr = formatTimelineTimestamp(now, 'live');
    windowTextEl.textContent = `${firstStr} → ${lastStr}`;
  }

  // 5. Dynamically refresh 5m window aggregate stats (Avg, Peak, Low)
  const primaryDs = modalChart.data.datasets[0];
  if (primaryDs && primaryDs.data && primaryDs.data.length > 0) {
    const vals = primaryDs.data.map(d => d.y);
    const statAvg = document.getElementById('modal-stat-avg');
    const statPeak = document.getElementById('modal-stat-peak');
    const statLow = document.getElementById('modal-stat-low');
    if (vals.length > 0) {
      if (activeModalType === 'cpu' || activeModalType === 'ram' || activeModalType === 'swap') {
        const avg = (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1);
        const peak = Math.max(...vals).toFixed(1);
        const low = Math.min(...vals).toFixed(1);
        if (statAvg) statAvg.textContent = `${avg}%`;
        if (statPeak) statPeak.textContent = `${peak}%`;
        if (statLow) statLow.textContent = `${low}%`;
      } else if (activeModalType === 'db') {
        const avg = (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2);
        const peak = Math.max(...vals).toFixed(2);
        if (statAvg) statAvg.textContent = `${avg} ms`;
        if (statPeak) statPeak.textContent = `${peak} ms`;
      }
    }
  }

  modalChart.update('none');
}

function initModalListeners() {
  document.addEventListener('click', (e) => {
    // Timeline buttons (5m, 15m, 1h, 5h, 24h, all)
    const timelineBtn = e.target.closest('[data-timeline-range]');
    if (timelineBtn) {
      const range = timelineBtn.getAttribute('data-timeline-range');
      switchModalTimeline(range);
      return;
    }

    const card = e.target.closest('[data-modal-type]');
    if (card) {
      const type = card.getAttribute('data-modal-type');
      const param = card.getAttribute('data-db-name');
      openAnalyticsModal(type, param);
      return;
    }

    if (e.target.id === 'analytics-modal') {
      closeAnalyticsModal();
    }
  });

  const closeBtn = document.getElementById('modal-close-btn');
  if (closeBtn) {
    closeBtn.addEventListener('click', closeAnalyticsModal);
  }

  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeAnalyticsModal();
    }
  });
}

// Cadence Dropdown Selector
function initCadenceSelector() {
  const selectEl = document.getElementById('update-cadence-select');
  if (!selectEl) return;
  const saved = localStorage.getItem('pulse_poll_interval');
  if (saved) selectEl.value = saved;

  selectEl.addEventListener('change', (e) => {
    const val = parseFloat(e.target.value);
    localStorage.setItem('pulse_poll_interval', String(val));
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'SET_INTERVAL', interval: val }));
    } else {
      fetch('/api/settings/interval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interval: val }),
      }).catch(() => {});
    }
  });
}

// Alerts Notification Center Popover Initializer
function initAlertsDropdown() {
  const btn = document.getElementById('alert-notifications-btn');
  const dropdown = document.getElementById('alerts-dropdown');
  const closeBtn = document.getElementById('alerts-close-btn');

  if (!btn || !dropdown) return;

  const toggleDropdown = (e) => {
    e.stopPropagation();
    const isHidden = dropdown.classList.contains('hidden');
    if (isHidden) {
      dropdown.classList.remove('hidden');
    } else {
      dropdown.classList.add('hidden');
    }
  };

  const closeDropdown = () => {
    if (!dropdown.classList.contains('hidden')) {
      dropdown.classList.add('hidden');
    }
  };

  btn.addEventListener('click', toggleDropdown);

  if (closeBtn) {
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      closeDropdown();
    });
  }

  const clearResolvedBtn = document.getElementById('alerts-clear-resolved-btn');
  if (clearResolvedBtn) {
    clearResolvedBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        await fetch('/api/alerts/clear-resolved', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        });
      } catch (err) {}
    });
  }

  // Prevent clicks inside dropdown from bubbling up and closing it
  dropdown.addEventListener('click', (e) => {
    e.stopPropagation();
  });

  // Global click outside dismiss
  document.addEventListener('click', (e) => {
    if (!dropdown.contains(e.target) && !btn.contains(e.target)) {
      closeDropdown();
    }
  });

  // Escape key closes dropdown
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeDropdown();
    }
  });

  // Render initial empty / healthy state
  updateAlerts([]);
}

// ==========================================
// Warning Limits Configuration Modal
// ==========================================

let currentAlertThresholds = {
  duration_seconds: 90.0,
  cpu_threshold_percent: 90.0,
  ram_threshold_percent: 90.0,
  disk_threshold_percent: 85.0,
  swap_threshold_percent: 80.0,
  db_latency_threshold_ms: 200.0,
};

function updateAlertsFooterThresholds() {
  const footerEl = document.getElementById('alerts-footer-thresholds-text');
  if (footerEl && currentAlertThresholds) {
    const t = currentAlertThresholds;
    const dur = t.duration_seconds !== undefined ? t.duration_seconds : 90;
    const cpu = t.cpu_threshold_percent !== undefined ? t.cpu_threshold_percent : 90;
    const ram = t.ram_threshold_percent !== undefined ? t.ram_threshold_percent : 90;
    const disk = t.disk_threshold_percent !== undefined ? t.disk_threshold_percent : 85;
    footerEl.textContent = `Hysteresis: ${dur}s • CPU ≥${cpu}% • RAM ≥${ram}% • Disk ≥${disk}%`;
  }
}

function syncAlertThresholdsUI(thresholds) {
  if (!thresholds) return;
  currentAlertThresholds = { ...currentAlertThresholds, ...thresholds };
  window.currentAlertThresholds = currentAlertThresholds;

  const pairs = [
    { range: 'thresh-duration-range', num: 'thresh-duration-num', key: 'duration_seconds' },
    { range: 'thresh-cpu-range', num: 'thresh-cpu-num', key: 'cpu_threshold_percent' },
    { range: 'thresh-ram-range', num: 'thresh-ram-num', key: 'ram_threshold_percent' },
    { range: 'thresh-disk-range', num: 'thresh-disk-num', key: 'disk_threshold_percent' },
    { range: 'thresh-swap-range', num: 'thresh-swap-num', key: 'swap_threshold_percent' },
    { range: 'thresh-db-range', num: 'thresh-db-num', key: 'db_latency_threshold_ms' },
  ];

  pairs.forEach(({ range, num, key }) => {
    const rEl = document.getElementById(range);
    const nEl = document.getElementById(num);
    const val = currentAlertThresholds[key];
    if (rEl && val !== undefined) rEl.value = String(val);
    if (nEl && val !== undefined) nEl.value = String(val);
  });

  updateAlertsFooterThresholds();
}

let currentSettingsTab = 'thresholds';

function switchSettingsTab(tabName) {
  currentSettingsTab = tabName;
  const threshTabBtn = document.getElementById('modal-tab-thresholds-btn');
  const emailTabBtn = document.getElementById('modal-tab-email-btn');
  const threshPane = document.getElementById('tab-pane-thresholds');
  const emailPane = document.getElementById('tab-pane-email');
  const resetBtn = document.getElementById('thresh-reset-btn');
  const saveText = document.getElementById('thresh-save-text');

  if (tabName === 'email') {
    if (threshTabBtn) {
      threshTabBtn.className = 'px-4 py-2.5 text-xs font-bold text-slate-400 hover:text-slate-200 border-b-2 border-transparent transition flex items-center space-x-2 focus:outline-none';
    }
    if (emailTabBtn) {
      emailTabBtn.className = 'px-4 py-2.5 text-xs font-bold text-indigo-400 border-b-2 border-indigo-500 transition flex items-center space-x-2 focus:outline-none';
    }
    if (threshPane) threshPane.classList.add('hidden');
    if (emailPane) emailPane.classList.remove('hidden');
    if (resetBtn) resetBtn.classList.add('hidden');
    if (saveText) saveText.textContent = 'Save Email Settings';

    // Fetch latest email settings
    fetch('/api/settings/email')
      .then(r => r.json())
      .then(data => {
        if (data.status === 'success' && data.email) {
          const em = data.email;
          const enCb = document.getElementById('email-enabled-checkbox');
          const recIn = document.getElementById('email-recipient-input');
          const sendDisp = document.getElementById('email-sender-display');
          const resCb = document.getElementById('email-send-resolved-checkbox');
          if (enCb) enCb.checked = !!em.enabled;
          if (recIn) recIn.value = em.recipient_email || '';
          if (sendDisp) sendDisp.textContent = em.sender_email || 'vardhakpatel6@gmail.com';
          if (resCb) resCb.checked = !!em.send_on_resolved;
        }
      })
      .catch(() => {});
  } else {
    if (threshTabBtn) {
      threshTabBtn.className = 'px-4 py-2.5 text-xs font-bold text-indigo-400 border-b-2 border-indigo-500 transition flex items-center space-x-2 focus:outline-none';
    }
    if (emailTabBtn) {
      emailTabBtn.className = 'px-4 py-2.5 text-xs font-bold text-slate-400 hover:text-slate-200 border-b-2 border-transparent transition flex items-center space-x-2 focus:outline-none';
    }
    if (threshPane) threshPane.classList.remove('hidden');
    if (emailPane) emailPane.classList.add('hidden');
    if (resetBtn) resetBtn.classList.remove('hidden');
    if (saveText) saveText.textContent = 'Save Limits';
  }
}

function openThresholdsModal(initialTab = 'thresholds') {
  const modal = document.getElementById('thresholds-modal');
  const content = document.getElementById('thresholds-modal-content');
  if (!modal || !content) return;

  switchSettingsTab(initialTab);
  syncAlertThresholdsUI(currentAlertThresholds);

  modal.classList.remove('hidden');
  requestAnimationFrame(() => {
    modal.classList.remove('opacity-0');
    content.classList.remove('scale-95');
    content.classList.add('scale-100');
  });
}

function closeThresholdsModal() {
  const modal = document.getElementById('thresholds-modal');
  const content = document.getElementById('thresholds-modal-content');
  if (!modal || !content) return;

  modal.classList.add('opacity-0');
  content.classList.remove('scale-100');
  content.classList.add('scale-95');
  setTimeout(() => {
    modal.classList.add('hidden');
  }, 200);
}

function initThresholdsModal() {
  const settingsBtn = document.getElementById('settings-btn');
  const configureHeaderBtn = document.getElementById('alerts-configure-header-btn');
  const configureFooterBtn = document.getElementById('alerts-configure-footer-btn');
  const emailHeaderBtn = document.getElementById('alerts-email-header-btn');
  const closeBtn = document.getElementById('thresholds-close-btn');
  const cancelBtn = document.getElementById('thresh-cancel-btn');
  const resetBtn = document.getElementById('thresh-reset-btn');
  const saveBtn = document.getElementById('thresh-save-btn');
  const modal = document.getElementById('thresholds-modal');
  const content = document.getElementById('thresholds-modal-content');

  const tabThreshBtn = document.getElementById('modal-tab-thresholds-btn');
  const tabEmailBtn = document.getElementById('modal-tab-email-btn');
  if (tabThreshBtn) tabThreshBtn.addEventListener('click', () => switchSettingsTab('thresholds'));
  if (tabEmailBtn) tabEmailBtn.addEventListener('click', () => switchSettingsTab('email'));

  const openAndDismissDropdown = (tab = 'thresholds') => {
    const dropdown = document.getElementById('alerts-dropdown');
    if (dropdown) dropdown.classList.add('hidden');
    openThresholdsModal(tab);
  };

  if (settingsBtn) settingsBtn.addEventListener('click', () => openAndDismissDropdown('thresholds'));
  if (configureHeaderBtn) configureHeaderBtn.addEventListener('click', () => openAndDismissDropdown('thresholds'));
  if (configureFooterBtn) configureFooterBtn.addEventListener('click', () => openAndDismissDropdown('thresholds'));
  if (emailHeaderBtn) emailHeaderBtn.addEventListener('click', () => openAndDismissDropdown('email'));
  if (closeBtn) closeBtn.addEventListener('click', closeThresholdsModal);
  if (cancelBtn) cancelBtn.addEventListener('click', closeThresholdsModal);

  if (modal && content) {
    modal.addEventListener('click', (e) => {
      if (!content.contains(e.target)) {
        closeThresholdsModal();
      }
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
      closeThresholdsModal();
    }
  });

  const pairs = [
    { range: 'thresh-duration-range', num: 'thresh-duration-num' },
    { range: 'thresh-cpu-range', num: 'thresh-cpu-num' },
    { range: 'thresh-ram-range', num: 'thresh-ram-num' },
    { range: 'thresh-disk-range', num: 'thresh-disk-num' },
    { range: 'thresh-swap-range', num: 'thresh-swap-num' },
    { range: 'thresh-db-range', num: 'thresh-db-num' },
  ];

  pairs.forEach(({ range, num }) => {
    const rEl = document.getElementById(range);
    const nEl = document.getElementById(num);
    if (rEl && nEl) {
      rEl.addEventListener('input', () => {
        nEl.value = rEl.value;
      });
      nEl.addEventListener('input', () => {
        const val = parseFloat(nEl.value);
        if (!isNaN(val)) {
          rEl.value = String(val);
        }
      });
    }
  });

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      syncAlertThresholdsUI({
        duration_seconds: 90.0,
        cpu_threshold_percent: 90.0,
        ram_threshold_percent: 90.0,
        disk_threshold_percent: 85.0,
        swap_threshold_percent: 80.0,
        db_latency_threshold_ms: 200.0,
      });
    });
  }

  // Test Email Button
  const testBtn = document.getElementById('email-test-btn');
  if (testBtn) {
    testBtn.addEventListener('click', async () => {
      const recInput = document.getElementById('email-recipient-input');
      const testSpinner = document.getElementById('email-test-spinner');
      const testText = document.getElementById('email-test-text');
      const testStatus = document.getElementById('email-test-status');

      const recipient = (recInput ? recInput.value : '').trim();
      if (!recipient) {
        if (testStatus) {
          testStatus.className = 'p-3 rounded-xl text-xs bg-rose-500/10 border border-rose-500/30 text-rose-300';
          testStatus.textContent = 'Please enter a recipient email address to send the test alert.';
          testStatus.classList.remove('hidden');
        }
        if (recInput) recInput.focus();
        return;
      }

      if (testSpinner) testSpinner.classList.remove('hidden');
      if (testText) testText.textContent = 'Sending...';
      testBtn.disabled = true;
      if (testStatus) testStatus.classList.add('hidden');

      try {
        const res = await fetch('/api/alerts/test-email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ recipient_email: recipient }),
        });
        const data = await res.json();
        if (res.ok && data.status === 'success') {
          if (testStatus) {
            testStatus.className = 'p-3 rounded-xl text-xs bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 flex items-center space-x-2';
            testStatus.innerHTML = `
              <svg class="w-4 h-4 text-emerald-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
              <span><strong>Delivered!</strong> Test alert sent successfully to ${recipient}.</span>
            `;
            testStatus.classList.remove('hidden');
          }
        } else {
          if (testStatus) {
            testStatus.className = 'p-3 rounded-xl text-xs bg-rose-500/10 border border-rose-500/30 text-rose-300 space-y-1';
            testStatus.innerHTML = `
              <div><strong>Delivery Failed:</strong> ${data.message || 'Unknown error'}</div>
              <div class="text-[11px] text-rose-400/80">Sender is verified as vardhakpatel6@gmail.com. Please check recipient address and Mailjet account status.</div>
            `;
            testStatus.classList.remove('hidden');
          }
        }
      } catch (err) {
        if (testStatus) {
          testStatus.className = 'p-3 rounded-xl text-xs bg-rose-500/10 border border-rose-500/30 text-rose-300';
          testStatus.textContent = `Network error sending test email: ${err.message}`;
          testStatus.classList.remove('hidden');
        }
      } finally {
        if (testSpinner) testSpinner.classList.add('hidden');
        if (testText) testText.textContent = 'Send Test Email';
        testBtn.disabled = false;
      }
    });
  }

  // Unified Save Button (handles Limits or Email settings based on active tab)
  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      const spinner = document.getElementById('thresh-save-spinner');
      const text = document.getElementById('thresh-save-text');
      if (spinner) spinner.classList.remove('hidden');
      saveBtn.disabled = true;

      if (currentSettingsTab === 'email') {
        if (text) text.textContent = 'Saving Email...';
        const enabledCb = document.getElementById('email-enabled-checkbox');
        const recIn = document.getElementById('email-recipient-input');
        const resCb = document.getElementById('email-send-resolved-checkbox');

        const emailPayload = {
          enabled: enabledCb ? enabledCb.checked : true,
          recipient_email: recIn ? recIn.value.trim() : '',
          send_on_resolved: resCb ? resCb.checked : true,
          sender_email: 'vardhakpatel6@gmail.com',
        };

        try {
          const res = await fetch('/api/settings/email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(emailPayload),
          });
          const data = await res.json();
          if (data.status === 'success') {
            if (text) text.textContent = 'Saved!';
            setTimeout(() => {
              closeThresholdsModal();
              if (text) text.textContent = 'Save Email Settings';
              if (spinner) spinner.classList.add('hidden');
              saveBtn.disabled = false;
            }, 350);
          } else {
            alert(`Failed to save email settings: ${data.message || 'Unknown error'}`);
            if (text) text.textContent = 'Save Email Settings';
            if (spinner) spinner.classList.add('hidden');
            saveBtn.disabled = false;
          }
        } catch (err) {
          console.error('Error saving email settings:', err);
          alert('Network error while saving email settings.');
          if (text) text.textContent = 'Save Email Settings';
          if (spinner) spinner.classList.add('hidden');
          saveBtn.disabled = false;
        }
      } else {
        // Warning limits save
        if (text) text.textContent = 'Saving Limits...';
        const getVal = (id, fallback) => {
          const el = document.getElementById(id);
          const val = el ? parseFloat(el.value) : fallback;
          return isNaN(val) ? fallback : val;
        };

        const payload = {
          duration_seconds: getVal('thresh-duration-num', 90.0),
          cpu_threshold_percent: getVal('thresh-cpu-num', 90.0),
          ram_threshold_percent: getVal('thresh-ram-num', 90.0),
          disk_threshold_percent: getVal('thresh-disk-num', 85.0),
          swap_threshold_percent: getVal('thresh-swap-num', 80.0),
          db_latency_threshold_ms: getVal('thresh-db-num', 200.0),
        };

        try {
          const res = await fetch('/api/settings/alerts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          const data = await res.json();
          if (data.status === 'success') {
            syncAlertThresholdsUI(data.alerts);
            if (data.active_alerts) {
              updateAlerts(data.active_alerts);
            }
            if (text) text.textContent = 'Saved!';
            setTimeout(() => {
              closeThresholdsModal();
              if (text) text.textContent = 'Save Limits';
              if (spinner) spinner.classList.add('hidden');
              saveBtn.disabled = false;
            }, 350);
          } else {
            alert(`Failed to save warning limits: ${data.message || 'Unknown error'}`);
            if (text) text.textContent = 'Save Limits';
            if (spinner) spinner.classList.add('hidden');
            saveBtn.disabled = false;
          }
        } catch (err) {
          console.error('Error saving alert thresholds:', err);
          alert('Network error while saving warning limits.');
          if (text) text.textContent = 'Save Limits';
          if (spinner) spinner.classList.add('hidden');
          saveBtn.disabled = false;
        }
      }
    });
  }

  // Fetch initial thresholds and email settings on load
  fetch('/api/settings/alerts')
    .then(r => r.json())
    .then(data => {
      if (data.status === 'success' && data.alerts) {
        syncAlertThresholdsUI(data.alerts);
      }
    })
    .catch(() => {});

  fetch('/api/settings/email')
    .then(r => r.json())
    .then(data => {
      if (data.status === 'success' && data.email) {
        const em = data.email;
        const recIn = document.getElementById('email-recipient-input');
        const enCb = document.getElementById('email-enabled-checkbox');
        const sendDisp = document.getElementById('email-sender-display');
        const resCb = document.getElementById('email-send-resolved-checkbox');
        if (recIn && em.recipient_email) recIn.value = em.recipient_email;
        if (enCb && em.enabled !== undefined) enCb.checked = em.enabled;
        if (sendDisp && em.sender_email) sendDisp.textContent = em.sender_email;
        if (resCb && em.send_on_resolved !== undefined) resCb.checked = em.send_on_resolved;
      }
    })
    .catch(() => {});
}

// App Entrypoint
document.addEventListener('DOMContentLoaded', () => {
  initCadenceSelector();
  initAlertsDropdown();
  initThresholdsModal();
  initModalListeners();
  initChart();
  loadInitialStaticInfo();
  connectWebSocket();

  setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send('ping');
    }
  }, 20000);
});

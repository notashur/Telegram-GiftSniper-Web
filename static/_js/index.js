// Ask for notification permission
async function requestNotificationPermission() {
    if ('Notification' in window && 'serviceWorker' in navigator) {
        const permission = await Notification.requestPermission();
        if (permission === 'granted') {
            console.log('Notification permission granted');
            await registerServiceWorker();
        } else {
            console.log('Notification permission denied');
        }
    } else {
        console.log('Notifications or Service Workers not supported');
    }
}

// Register Service Worker (required for push notifications)
async function registerServiceWorker() {
    try {
        const registration = await navigator.serviceWorker.register("/static/js-obfuscated/sw.js");
        console.log('Service Worker registered');

        // Subscribe to push notifications
        const subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array('BDkbsnnqmQYzhBXrZV_cPKeP4zlRA7redTyOz7SRGigQNY0fMUUTTnikEQqH5UlZED3Vt5KEq2_JX3deVlCxC_s')
        });

        // Send subscription to Flask backend
        await fetch('/save-subscription', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(subscription)
        });
    } catch (error) {
        console.error('Service Worker registration failed:', error);
    }
}

// Helper function to convert VAPID key
function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    return Uint8Array.from([...rawData].map(char => char.charCodeAt(0)));
}

// Call this when the user logs in or enables notifications
requestNotificationPermission();

function showConfirmDialog(button) {
    const dialog = document.getElementById('confirmDialog');
    const title = document.getElementById('confirmTitle');
    const message = document.getElementById('confirmMessage');
    const actionBtn = document.getElementById('confirmAction');
    const isRunning = button.getAttribute('data-bot-status') === 'running';
    if (isRunning) {
        title.textContent = 'Stop Bot';
        message.textContent = 'Are you sure you want to stop the bot?';
        actionBtn.textContent = 'Stop';
        actionBtn.className = 'px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white font-semibold transition';
    } else {
        title.textContent = 'Start Bot';
        message.textContent = 'Are you sure you want to start the bot?';
        actionBtn.textContent = 'Start';
        actionBtn.className = 'px-4 py-2 rounded-lg bg-green-600 hover:bg-green-700 text-white font-semibold transition';
    }

    actionBtn.onclick = function () {
        dialog.classList.add('hidden');
        toggleBot(); // Actual function to start/stop the bot
        // Disable the confirm button to prevent double-clicks
        actionBtn.disabled = true;
        actionBtn.classList.add('btn-loading');
    };

    dialog.classList.remove('hidden');
}

function closeConfirmDialog() {
    document.getElementById('confirmDialog').classList.add('hidden');
}


document.addEventListener('DOMContentLoaded', function () {
    refreshQuickLogs();
    refreshBotStatus();

    // Check if bot is running and start timer if needed
    if (document.getElementById('bot-status-text').textContent.trim() === 'Running') {
        startRuntimeTimer();
    }
});
// Dark mode toggle
function toggleDarkMode() {
    document.body.classList.toggle('dark-mode');
    localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
}

// Check for saved dark mode preference
if (localStorage.getItem('darkMode') === 'true') {
    document.body.classList.add('dark-mode');
}
function showNotification(message, type = 'info', duration = 5000) {
    const container = document.getElementById('notification-container');
    if (!container) return;

    const notification = document.createElement('div');
    notification.className = `notification ${type}`;

    // Icons for different notification types
    const icons = {
        success: 'fas fa-check-circle',
        error: 'fas fa-exclamation-circle',
        warning: 'fas fa-exclamation-triangle',
        info: 'fas fa-info-circle'
    };

    notification.innerHTML = `
        <i class="notification-icon ${icons[type] || icons.info}"></i>
        <span>${message}</span>
        <span class="notification-close" onclick="this.parentElement.remove()">
            <i class="fas fa-times"></i>
        </span>
    `;

    container.appendChild(notification);

    // Auto-remove after duration
    if (duration > 0) {
        setTimeout(() => {
            notification.style.animation = 'fadeOut 0.3s ease-out forwards';
            setTimeout(() => notification.remove(), 300);
        }, duration);
    }

    return notification;
}
// Update your JavaScript
let runtimeInterval = null;

function formatRuntime(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    return [
        hours.toString().padStart(2, '0'),
        minutes.toString().padStart(2, '0'),
        secs.toString().padStart(2, '0')
    ].join(':');
}

async function updateRuntimeDisplay() {
    try {
        const response = await fetch('/api/bot/runtime');
        const data = await response.json();

        if (data.runtime > 0) {
            document.getElementById('bot-runtime').textContent = formatRuntime(data.runtime);
            return true;
        } else {
            document.getElementById('bot-runtime').textContent = '00:00:00';
            return false;
        }
    } catch (error) {
        console.error('Error fetching runtime:', error);
        return false;
    }
}

function startRuntimeTimer() {
    // Clear any existing interval
    if (runtimeInterval) clearInterval(runtimeInterval);

    // Update immediately and then every second
    updateRuntimeDisplay();
    runtimeInterval = setInterval(updateRuntimeDisplay, 1000);
}

function stopRuntimeTimer() {
    if (runtimeInterval) {
        clearInterval(runtimeInterval);
        runtimeInterval = null;
    }
    document.getElementById('bot-runtime').textContent = '00:00:00';
}
async function toggleBot() {
    const isRunning = document.getElementById('bot-status-text').textContent.trim() === 'Running';
    const btn = document.querySelector('button[data-bot-status]');

    // Disable button and show loading
    btn.disabled = true;
    btn.classList.add('btn-loading');

    try {
        const response = await fetch(`/api/bot/${isRunning ? 'stop' : 'start'}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const result = await response.json();

        if (result.status === 'success') {
            showNotification(result.message, 'success');
            if (!isRunning) {
                startRuntimeTimer();
            } else {
                stopRuntimeTimer();
            }
            setTimeout(() => location.reload(), 1000);
        } else {
            showNotification(result.message, 'error');
            // Re-enable button if there was an error
            btn.disabled = false;
            btn.classList.remove('btn-loading');
        }
    } catch (error) {
        showNotification('Failed to communicate with server', 'error');
        console.error('Error:', error);
        // Re-enable button on error
        btn.disabled = false;
        btn.classList.remove('btn-loading');
    }
}
let currentPage = 1;
const logsPerPage = 10;
let refreshInterval;

async function refreshQuickLogs(page = currentPage) {  // Use currentPage as default
    try {
        const response = await fetch(`/quick-logs?page=${page}&per_page=${logsPerPage}`);
        const data = await response.json();

        const logsContainer = document.getElementById('quick-logs-content');
        const paginationControls = document.getElementById('pagination-controls');
        const prevButton = document.getElementById('prev-page');
        const nextButton = document.getElementById('next-page');
        const pageInfo = document.getElementById('page-info');

        if (logsContainer && data.logs) {
            // Update logs
            logsContainer.innerHTML = data.logs.map(log => {
                // Split timestamp from message
                const timestampEnd = log.indexOf(']');
                const timestamp = log.substring(1, timestampEnd);
                let message = log.substring(timestampEnd + 2);

                // Make Telegram URLs clickable
                message = message.replace(
                    /(https?:\/\/t\.me\/[^\s]+)/g,
                    '<a href="$1" target="_blank" rel="noopener noreferrer" class="text-blue-500 hover:underline">$1</a>'
                );

                return `
                    <li class="${getLogColorClass(log)}">
                        <span class="text-gray-500 text-xs">${timestamp}</span>
                        <span class="block">${message}</span>
                    </li>
                `;
            }).join('');

            // Update pagination controls
            pageInfo.textContent = `Page ${data.pagination.current_page} of ${data.pagination.total_pages}`;

            // Show/hide controls
            paginationControls.classList.toggle('hidden', data.pagination.total_pages <= 1);

            // Show/hide buttons
            prevButton.classList.toggle('hidden', data.pagination.current_page === 1);
            nextButton.classList.toggle('hidden', data.pagination.current_page === data.pagination.total_pages);

            // Update current page
            currentPage = data.pagination.current_page;
        }
    } catch (error) {
        console.error('Error refreshing logs:', error);
    }
}

// Event listeners
document.getElementById('prev-page').addEventListener('click', () => {
    refreshQuickLogs(currentPage - 1);
});

document.getElementById('next-page').addEventListener('click', () => {
    refreshQuickLogs(currentPage + 1);
});

// Combined status and logs refresh
// Modify your refreshBotStatus function
async function refreshBotStatus() {
    try {
        const response = await fetch('/api/bot/status');
        const data = await response.json();

        const statusText = document.getElementById('bot-status-text');
        const balanceStarsText = document.getElementById('current-balance-stars');
        const balanceTonText = document.getElementById('current-balance-ton');
        const bot_cycles = document.getElementById('bot-cycles');

        if (statusText) {
            statusText.textContent = data.running ? 'Running' : 'Stopped';
            statusText.className = `text-sm font-medium ${data.running ? 'text-green-400' : 'text-red-400'}`;
            // Start/stop timer based on status
            if (data.running) {
                startRuntimeTimer();
            } else {
                stopRuntimeTimer();
            }
        }
        if (balanceStarsText && data.balance_stars !== undefined) {
            balanceStarsText.textContent = data.balance_stars + '⭐';
        }
        if (balanceTonText && data.balance_ton !== undefined) {
            balanceTonText.textContent = data.balance_ton + '💎';
        }
        if (bot_cycles) {
            bot_cycles.textContent = `Cycles: ${data.bot_cycles}`;
        }
        // Update the button based on bot status
        const btn = document.querySelector('button[data-bot-status]');
        if (btn) {
            // Set the data-bot-status attribute
            btn.setAttribute('data-bot-status', data.running ? 'running' : 'stopped');

            // Remove existing classes
            btn.classList.remove('bg-red-600', 'hover:bg-red-700', 'bg-green-600', 'hover:bg-green-700', 'btn-loading');

            // Add classes based on status
            if (data.running) {
                btn.classList.add('bg-red-600', 'hover:bg-red-700');
                // Change icon and text to Stop
                btn.innerHTML = `<i class="fas fa-stop mr-2"></i>Stop`;
            } else {
                btn.classList.add('bg-green-600', 'hover:bg-green-700');
                // Change icon and text to Start
                btn.innerHTML = `<i class="fas fa-play mr-2"></i>Start`;
            }

            // Ensure button is enabled
            btn.disabled = false;
        }
    } catch (error) {
        console.error('Error refreshing status:', error);
    }
}
// Helper function for log colors
function getLogColorClass(log) {
    if (log.includes('✅')) return 'text-green-400';
    if (log.includes('❌')) return 'text-red-400';
    if (log.includes('⛔')) return 'text-yellow-400';
    return 'text-gray-400';
}

// Set up intervals
setInterval(refreshBotStatus, 5000);
setInterval(refreshQuickLogs, 3000);  // More frequent log updates
const subscriptionInfo = document.getElementById('subscription-info');
const expiryTimestamp = parseInt(subscriptionInfo.dataset.expiry, 10);
// proceed with countdown logic
const countdownEl = document.getElementById('countdown-timer');

function updateCountdown() {
    const now = new Date().getTime();
    const distance = expiryTimestamp - now;

    if (distance < 0) {
        countdownEl.innerHTML = "<span class='text-red-400'>Expired</span>";
        return;
    }

    const days = Math.floor(distance / (1000 * 60 * 60 * 24));
    const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
    const seconds = Math.floor((distance % (1000 * 60)) / 1000);

    countdownEl.innerHTML = `${days}d ${hours}h ${minutes}m ${seconds}s remaining`;
}

updateCountdown();
setInterval(updateCountdown, 1000);


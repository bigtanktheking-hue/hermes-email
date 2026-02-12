// ── MailTank Mobile Web App ─────────────────────────────────

// ── Helpers ────────────────────────────────────────────────

async function api(path, opts = {}) {
    opts.headers = opts.headers || {};
    opts.headers['Content-Type'] = 'application/json';
    opts.headers['X-Requested-With'] = 'mailtank';
    if (opts.method && opts.method !== 'GET') {
        opts.headers['X-CSRF-Token'] = window.CSRF_TOKEN || '';
    }
    const controller = new AbortController();
    const timeout = setTimeout(function() { controller.abort(); }, 60000);
    opts.signal = controller.signal;
    let res;
    try {
        res = await fetch(path, opts);
    } finally {
        clearTimeout(timeout);
    }
    if (res.status === 401) {
        window.location.href = '/login';
        throw new Error('Unauthorized');
    }
    if (!res.ok) {
        const err = await res.json().catch(function() { return {}; });
        throw new Error(err.error || 'Request failed (' + res.status + ')');
    }
    return res.json();
}

function esc(s) {
    if (s && typeof s === 'object') {
        // AI sometimes returns objects like {sender, subject}
        s = Object.values(s).join(' — ');
    }
    const d = document.createElement('div');
    d.textContent = String(s || '');
    return d.innerHTML;
}

function showLoading(el) {
    el.innerHTML = '<div class="flex justify-center py-8"><div class="spinner"></div></div>';
    el.classList.remove('hidden');
}

function showResult(el, html) {
    el.innerHTML = '<div class="fade-in">' + html + '</div>';
    el.classList.remove('hidden');
}

function showError(el, msg) {
    el.innerHTML = '<div class="bg-red-900 text-red-200 text-sm rounded-xl p-4 fade-in">' + esc(msg) + '</div>';
    el.classList.remove('hidden');
}


function showToast(msg, type) {
    type = type || 'error';
    var t = document.createElement('div');
    t.className = 'fixed top-4 left-1/2 -translate-x-1/2 px-4 py-2 rounded-lg text-sm z-50 fade-in ' + 
        (type === 'error' ? 'bg-red-600' : 'bg-green-600') + ' text-white shadow-lg';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function() { t.remove(); }, 4000);
}
// ── Tab Switching ──────────────────────────────────────────

function switchTab(name) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
    document.querySelector('[data-tab="' + name + '"]').classList.add('active');

    if (name === 'settings') loadDomains();
    if (name === 'emails') loadEmails();
    if (name === 'agents') loadAgents();
    if (name === 'chat') {
        const el = document.getElementById('chat-messages');
        el.scrollTop = el.scrollHeight;
    }
}

// ── Dashboard ──────────────────────────────────────────────

function fmtNum(n) {
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
    return String(n);
}

async function loadStats(retries) {
    retries = retries || 0;
    try {
        const data = await api('/api/stats');
        document.getElementById('stat-unread').textContent = fmtNum(data.unread);
        document.getElementById('stat-vip').textContent = fmtNum(data.vip_unread);
        document.getElementById('stat-contacts').textContent = data.vip_contacts;
        document.getElementById('stat-domains').textContent = data.vip_domains;
    } catch (e) {
        console.error('Stats error:', e);
        if (retries < 2) {
            setTimeout(function() { loadStats(retries + 1); }, 2000);
        }
    }
}

// Load recent unread emails on home page
async function loadHomeEmails(retries) {
    retries = retries || 0;
    const el = document.getElementById('home-emails');
    if (!el) return;
    el.innerHTML = '<div class="flex justify-center py-4"><div class="spinner"></div></div>';
    try {
        const data = await api('/api/emails?per_page=20');
        if (!data.emails || data.emails.length === 0) {
            el.innerHTML = '<div class="text-center text-gray-500 py-4 text-sm">No unread emails</div>';
            return;
        }
        el.innerHTML = renderEmailCards(data.emails, true);
    } catch (e) {
        if (retries < 2) {
            setTimeout(function() { loadHomeEmails(retries + 1); }, 2000);
        } else {
            el.innerHTML = '<div class="text-red-400 text-sm p-2">' + esc(e.message) + ' <button onclick="loadHomeEmails()" class="text-cyan-400 underline ml-2">Retry</button></div>';
        }
    }
}

function renderEmailCards(emails, withReplyBtn) {
    let html = '';
    emails.forEach(function(e) {
        const from = esc(e.from || '');
        const subj = esc(e.subject || '(no subject)');
        const snippet = esc(e.snippet || e.body_preview || '');
        let shortDate = '';
        try {
            const d = new Date(e.date);
            const today = new Date();
            if (d.toDateString() === today.toDateString()) {
                shortDate = d.toLocaleTimeString(undefined, {hour:'numeric', minute:'2-digit'});
            } else {
                shortDate = d.toLocaleDateString(undefined, {month:'short', day:'numeric'});
            }
        } catch(ex) { shortDate = ''; }

        html += '<div class="bg-gray-800 rounded-xl p-3 fade-in cursor-pointer hover:bg-gray-750 transition" onclick="openEmail(\'' + esc(e.id) + '\')">';
        html += '<div class="flex items-start justify-between gap-2">';
        html += '<div class="flex-1 min-w-0">';
        html += '<div class="font-semibold text-sm truncate">' + from + '</div>';
        html += '<div class="text-sm text-gray-200 truncate">' + subj + '</div>';
        html += '<div class="text-xs text-gray-500 truncate mt-1">' + snippet + '</div>';
        html += '</div>';
        html += '<div class="text-right flex-shrink-0">';
        html += '<div class="text-xs text-gray-500 whitespace-nowrap">' + shortDate + '</div>';
        if (withReplyBtn) {
            html += '<button onclick="event.stopPropagation(); draftReply(\'' + esc(e.id) + '\', this)" class="mt-2 bg-cyan-700 hover:bg-cyan-600 text-white text-xs rounded-lg px-2 py-1 transition">Reply</button>';
        }
        html += '</div></div>';
        html += '<div id="draft-' + e.id + '" class="hidden mt-2" onclick="event.stopPropagation()"></div>';
        html += '</div>';
    });
    return html;
}

// ── Email Detail Modal ────────────────────────────────────

let currentEmailId = null;
let currentEmail = null;

async function openEmail(emailId) {
    currentEmailId = emailId;
    const modal = document.getElementById('email-modal');
    modal.classList.remove('hidden');
    document.getElementById('modal-subject').textContent = 'Loading...';
    document.getElementById('modal-from').textContent = '';
    document.getElementById('modal-date').textContent = '';
    document.getElementById('modal-body').textContent = '';
    document.getElementById('modal-reply-section').classList.add('hidden');
    document.getElementById('modal-send-status').classList.add('hidden');

    try {
        const data = await api('/api/email/' + emailId);
        currentEmail = data;
        document.getElementById('modal-subject').textContent = data.subject || '(no subject)';
        document.getElementById('modal-from').textContent = data.from || '';
        let dateStr = '';
        try {
            const d = new Date(data.date);
            dateStr = d.toLocaleString();
        } catch(ex) { dateStr = data.date || ''; }
        document.getElementById('modal-date').textContent = dateStr;
        document.getElementById('modal-body').textContent = data.body || data.body_preview || '(no body)';
    } catch (e) {
        document.getElementById('modal-body').textContent = 'Error loading email: ' + e.message;
    }
}

function closeEmailModal() {
    document.getElementById('email-modal').classList.add('hidden');
    currentEmailId = null;
    currentEmail = null;
}

async function draftReplyModal() {
    if (!currentEmailId) return;
    const btn = document.getElementById('modal-draft-btn');
    btn.textContent = 'Drafting...';
    btn.disabled = true;
    try {
        const data = await api('/api/draft-reply', {
            method: 'POST',
            body: JSON.stringify({ email_id: currentEmailId }),
        });
        const section = document.getElementById('modal-reply-section');
        section.classList.remove('hidden');
        const textarea = document.getElementById('modal-reply-text');
        if (data.needs_reply && data.draft) {
            textarea.value = data.draft;
        } else {
            textarea.value = '';
            textarea.placeholder = 'AI says no reply needed, but you can write one anyway...';
        }
        textarea.focus();
        btn.textContent = 'Re-draft';
    } catch (e) {
        showToast('Error: ' + e.message);
        btn.textContent = 'Draft Reply';
    }
    btn.disabled = false;
}

function closeReplySection() {
    document.getElementById('modal-reply-section').classList.add('hidden');
}

async function sendReplyModal() {
    const body = document.getElementById('modal-reply-text').value.trim();
    if (!body) { showToast('Reply cannot be empty'); return; }
    if (!confirm('Send this reply?')) return;

    const status = document.getElementById('modal-send-status');
    status.innerHTML = '<div class="flex items-center gap-2 text-cyan-400 text-sm"><div class="spinner" style="width:16px;height:16px;border-width:2px;"></div> Sending...</div>';
    status.classList.remove('hidden');

    try {
        const data = await api('/api/send-reply', {
            method: 'POST',
            body: JSON.stringify({ email_id: currentEmailId, body: body }),
        });
        status.innerHTML = '<div class="text-green-400 text-sm font-semibold fade-in">Sent to ' + esc(data.to) + '</div>';
        document.getElementById('modal-reply-text').value = '';
        // Refresh home emails
        setTimeout(function() { loadHomeEmails(); loadStats(); }, 1000);
    } catch (e) {
        status.innerHTML = '<div class="text-red-400 text-sm">' + esc(e.message) + '</div>';
    }
}

async function draftAllRepliesHome() {
    const el = document.getElementById('home-drafts');
    showLoading(el);
    try {
        const data = await api('/api/draft-replies-batch', {
            method: 'POST',
            body: JSON.stringify({ count: 20 }),
        });
        if (!data.drafts || data.drafts.length === 0) {
            showResult(el, '<div class="bg-gray-800 rounded-xl p-4 text-center text-gray-400">No emails to process</div>');
            return;
        }
        let html = '<div class="space-y-3">';
        html += '<div class="text-cyan-400 font-semibold text-sm">' + data.needs_reply + ' of ' + data.count + ' emails need replies</div>';
        data.drafts.forEach(function(d, idx) {
            html += '<div class="bg-gray-800 rounded-xl p-3 fade-in" id="batch-draft-' + idx + '">';
            html += '<div class="flex items-center gap-2 mb-1 cursor-pointer" onclick="openEmail(\'' + esc(d.id) + '\')">';
            html += '<span class="w-2 h-2 rounded-full flex-shrink-0 ' + (d.needs_reply ? 'bg-cyan-400' : 'bg-gray-600') + '"></span>';
            html += '<div class="font-semibold text-sm truncate flex-1">' + esc(d.subject) + '</div>';
            html += '</div>';
            html += '<div class="text-xs text-gray-400 mb-1">' + esc(d.from) + '</div>';
            if (d.needs_reply && d.draft) {
                html += '<textarea id="batch-text-' + idx + '" rows="3" class="w-full bg-gray-700 text-gray-200 text-sm rounded-lg p-2 mt-2 focus:outline-none focus:ring-1 focus:ring-cyan-500">' + esc(d.draft) + '</textarea>';
                html += '<div class="flex gap-2 mt-2">';
                html += '<button onclick="approveSend(\'' + esc(d.id) + '\', ' + idx + ')" class="flex-1 bg-green-600 hover:bg-green-500 text-white text-xs font-semibold rounded-lg py-2 transition">Approve & Send</button>';
                html += '<button onclick="skipDraft(' + idx + ')" class="bg-gray-600 hover:bg-gray-500 text-white text-xs rounded-lg px-3 py-2 transition">Skip</button>';
                html += '</div>';
                html += '<div id="batch-status-' + idx + '" class="hidden mt-1"></div>';
            } else {
                html += '<div class="text-xs text-gray-500 italic">No reply needed</div>';
            }
            html += '</div>';
        });
        html += '</div>';
        showResult(el, html);
    } catch (e) {
        showError(el, e.message);
    }
}

async function approveSend(emailId, idx) {
    const textarea = document.getElementById('batch-text-' + idx);
    const body = textarea ? textarea.value.trim() : '';
    if (!body) { showToast('Reply is empty'); return; }

    const status = document.getElementById('batch-status-' + idx);
    status.innerHTML = '<div class="flex items-center gap-2 text-cyan-400 text-xs"><div class="spinner" style="width:12px;height:12px;border-width:2px;"></div> Sending...</div>';
    status.classList.remove('hidden');

    try {
        const data = await api('/api/send-reply', {
            method: 'POST',
            body: JSON.stringify({ email_id: emailId, body: body }),
        });
        const card = document.getElementById('batch-draft-' + idx);
        card.innerHTML = '<div class="flex items-center gap-2 text-green-400 text-sm"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg> Sent to ' + esc(data.to) + '</div>';
    } catch (e) {
        status.innerHTML = '<div class="text-red-400 text-xs">' + esc(e.message) + '</div>';
    }
}

function skipDraft(idx) {
    const card = document.getElementById('batch-draft-' + idx);
    if (card) card.innerHTML = '<div class="text-gray-500 text-xs italic">Skipped</div>';
}

// ── Search emails from a sender ───────────────────────────

async function searchEmailsFrom(sender) {
    // Extract email address from "Name <email>" format
    const match = sender.match(/[\w.+-]+@[\w-]+\.[\w.-]+/);
    const addr = match ? match[0] : sender;
    switchTab('emails');
    const el = document.getElementById('emails-list');
    showLoading(el);
    try {
        const data = await api('/api/emails?per_page=30&q=' + encodeURIComponent('from:' + addr + ' is:unread in:inbox'));
        if (!data.emails || !data.emails.length) {
            el.innerHTML = '<div class="text-center text-gray-400 py-8">No unread emails from ' + esc(addr) + '</div>';
            return;
        }
        el.innerHTML = '<div class="text-cyan-400 text-sm mb-2">Emails from ' + esc(addr) + '</div>' + renderEmailCards(data.emails, true);
    } catch (e) {
        showError(el, e.message);
    }
}

// ── Expandable Panels ─────────────────────────────────────

let panelCache = {};

function togglePanel(id) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!el.classList.contains('hidden')) {
        el.classList.add('hidden');
        return;
    }
    el.classList.remove('hidden');
    if (!panelCache[id]) {
        loadPanel(id);
    }
}

async function loadPanel(id) {
    const el = document.getElementById(id);
    showLoading(el);
    try {
        if (id === 'panel-unread') {
            const data = await api('/api/emails?per_page=30');
            if (!data.emails || !data.emails.length) {
                el.innerHTML = '<div class="bg-gray-800 rounded-xl p-4 text-gray-400 text-sm text-center">No unread emails</div>';
            } else {
                el.innerHTML = '<div class="space-y-2">' + renderEmailCards(data.emails, true) + '</div>';
            }
        } else if (id === 'panel-vip-emails') {
            const data = await api('/api/vip');
            if (!data.emails || !data.emails.length) {
                el.innerHTML = '<div class="bg-gray-800 rounded-xl p-4 text-gray-400 text-sm text-center">No unread VIP emails</div>';
            } else {
                let html = '<div class="space-y-2">';
                data.emails.forEach(function(e) {
                    html += '<div class="bg-gray-800 rounded-xl p-3 border-l-4 border-yellow-500 fade-in">';
                    html += '<div class="font-semibold text-sm truncate">' + esc(e.from) + '</div>';
                    html += '<div class="text-sm text-gray-200 truncate">' + esc(e.subject) + '</div>';
                    html += '<div class="text-xs text-gray-500 truncate mt-1">' + esc(e.snippet || '') + '</div>';
                    html += '</div>';
                });
                html += '</div>';
                showResult(el, html);
            }
        } else if (id === 'panel-vip-contacts') {
            const data = await api('/api/vip/contacts');
            if (!data.contacts || !data.contacts.length) {
                el.innerHTML = '<div class="bg-gray-800 rounded-xl p-4 text-gray-400 text-sm text-center">No VIP contacts detected</div>';
            } else {
                let html = '<div class="bg-gray-800 rounded-xl p-4 space-y-1">';
                html += '<div class="text-green-400 text-xs font-semibold uppercase mb-2">' + data.count + ' VIP Contacts (auto-detected)</div>';
                data.contacts.forEach(function(c) {
                    html += '<div class="flex items-center justify-between py-1 text-sm border-b border-gray-700">';
                    html += '<span class="text-gray-200">' + esc(c.email) + '</span>';
                    html += '<span class="text-green-500 text-xs">score: ' + c.score + '</span>';
                    html += '</div>';
                });
                html += '</div>';
                showResult(el, html);
            }
        } else if (id === 'panel-vip-domains') {
            // Load domains AND the actual people emailing from those domains
            const [domData, pplData] = await Promise.all([
                api('/api/domains'),
                api('/api/vip/domain-people'),
            ]);
            let html = '';
            // Show people first
            if (pplData.people && pplData.people.length) {
                html += '<div class="bg-gray-800 rounded-xl p-4 mb-3">';
                html += '<div class="text-yellow-400 text-xs font-semibold uppercase mb-2">' + pplData.people.length + ' People from VIP Domains (' + pplData.total + ' emails)</div>';
                pplData.people.forEach(function(p) {
                    const sender = esc(p.from || '');
                    html += '<div class="py-2 border-b border-gray-700 cursor-pointer hover:bg-gray-750" onclick="searchEmailsFrom(\'' + sender.replace(/'/g, "\\'") + '\')">';
                    html += '<div class="text-sm text-gray-200">' + sender + '</div>';
                    html += '<div class="flex items-center gap-2 text-xs text-gray-500 mt-0.5">';
                    html += '<span>' + p.count + ' unread</span>';
                    html += '<span class="truncate">' + esc(p.latest_subject) + '</span>';
                    html += '</div></div>';
                });
                html += '</div>';
            }
            // Then show domain list
            if (domData.domains && domData.domains.length) {
                html += '<div class="bg-gray-800 rounded-xl p-4 space-y-1">';
                html += '<div class="text-purple-400 text-xs font-semibold uppercase mb-2">' + domData.count + ' VIP Domains</div>';
                domData.domains.forEach(function(d) {
                    html += '<div class="flex items-center justify-between py-1 text-sm border-b border-gray-700">';
                    html += '<span class="text-cyan-400">@' + esc(d.domain) + '</span>';
                    html += '<span class="text-gray-400 text-xs">' + esc(d.company || '') + '</span>';
                    html += '</div>';
                });
                html += '</div>';
            }
            if (!html) {
                el.innerHTML = '<div class="bg-gray-800 rounded-xl p-4 text-gray-400 text-sm text-center">No VIP domains</div>';
            } else {
                showResult(el, html);
            }
        }
        panelCache[id] = true;
    } catch (e) {
        showError(el, e.message);
    }
}

async function getBriefing() {
    const el = document.getElementById('briefing-result');
    showLoading(el);
    try {
        const data = await api('/api/briefing');
        let html = '<div class="bg-gray-800 rounded-xl p-4 space-y-3">';
        html += '<div class="text-cyan-400 font-semibold">' + esc(data.email_count || 0) + ' emails analyzed</div>';
        html += '<p class="text-sm">' + esc(data.summary || 'No summary available.') + '</p>';

        if (data.action_items && data.action_items.length) {
            html += '<div class="mt-2"><div class="text-red-400 text-xs font-semibold uppercase mb-1">Action Items</div>';
            data.action_items.forEach(function(item) {
                html += '<div class="text-sm text-gray-300 pl-2 border-l-2 border-red-500 mb-1">' + esc(item) + '</div>';
            });
            html += '</div>';
        }
        if (data.fyi && data.fyi.length) {
            html += '<div class="mt-2"><div class="text-blue-400 text-xs font-semibold uppercase mb-1">FYI</div>';
            data.fyi.forEach(function(item) {
                html += '<div class="text-sm text-gray-300 pl-2 border-l-2 border-blue-500 mb-1">' + esc(item) + '</div>';
            });
            html += '</div>';
        }
        html += '</div>';
        showResult(el, html);
    } catch (e) {
        showError(el, e.message);
    }
}

// ── Priority ──────────────────────────────────────────────

async function getPriority() {
    const el = document.getElementById('priority-result');
    showLoading(el);
    try {
        const data = await api('/api/priority');
        if (!data.classifications || data.classifications.length === 0) {
            showResult(el, '<div class="bg-gray-800 rounded-xl p-4 text-center text-gray-400">No unread emails to classify</div>');
            return;
        }
        let html = '<div class="text-sm text-gray-400 mb-2">' + data.email_count + ' emails scanned</div>';
        data.classifications.forEach(function(c) {
            const p = c.priority || 'low';
            html += '<div class="bg-gray-800 rounded-xl p-3 mb-2 priority-' + p + ' fade-in">';
            html += '<div class="font-semibold text-sm">' + esc(c.subject || '(no subject)') + '</div>';
            html += '<div class="text-gray-400 text-xs mt-1">' + esc(c.from || '') + '</div>';
            html += '<div class="flex items-center gap-2 mt-1">';
            const colors = { high: 'text-red-400', medium: 'text-yellow-400', low: 'text-gray-500' };
            html += '<span class="text-xs font-semibold uppercase ' + (colors[p] || 'text-gray-500') + '">' + p + '</span>';
            html += '<span class="text-xs text-gray-500">' + esc(c.reason || '') + '</span>';
            html += '</div></div>';
        });
        showResult(el, html);
    } catch (e) {
        showError(el, e.message);
    }
}

// ── Actions ───────────────────────────────────────────────

async function runCleanup() {
    if (!confirm('Run newsletter cleanup? This will archive/delete promotional emails.')) return;
    const el = document.getElementById('action-result');
    showLoading(el);
    try {
        const data = await api('/api/cleanup', { method: 'POST' });
        showResult(el, '<div class="bg-gray-800 rounded-xl p-4 text-sm space-y-1">' +
            '<div class="text-cyan-400 font-semibold">Cleanup Complete</div>' +
            '<div>' + data.email_count + ' emails scanned</div>' +
            '<div class="text-green-400">' + data.archived + ' archived</div>' +
            '<div class="text-red-400">' + data.deleted + ' deleted</div>' +
            '<div class="text-gray-400">' + data.kept + ' kept</div>' +
            '</div>');
        loadStats();
    } catch (e) {
        showError(el, e.message);
    }
}

async function runInboxZero() {
    if (!confirm('Process inbox emails? This will archive/trash low-priority emails.')) return;
    const el = document.getElementById('action-result');
    showLoading(el);
    try {
        const data = await api('/api/inbox-zero', { method: 'POST' });
        let msg = data.inbox_zero ? 'Inbox zero achieved!' : data.unread_remaining + ' unread remaining';
        showResult(el, '<div class="bg-gray-800 rounded-xl p-4 text-sm space-y-1">' +
            '<div class="text-cyan-400 font-semibold">Inbox Zero</div>' +
            '<div>' + data.email_count + ' emails processed</div>' +
            '<div class="text-green-400">' + data.archived + ' archived</div>' +
            '<div class="text-red-400">' + data.trashed + ' trashed</div>' +
            '<div class="text-blue-400">' + data.kept_for_action + ' kept for action</div>' +
            '<div class="text-gray-400 mt-1">' + esc(msg) + '</div>' +
            '</div>');
        loadStats();
    } catch (e) {
        showError(el, e.message);
    }
}

async function getVipAlerts() {
    const el = document.getElementById('action-result');
    showLoading(el);
    try {
        const data = await api('/api/vip');
        if (data.email_count === 0) {
            showResult(el, '<div class="bg-gray-800 rounded-xl p-4 text-center text-gray-400">No unread VIP emails</div>');
            return;
        }
        let html = '<div class="bg-gray-800 rounded-xl p-4"><div class="text-yellow-400 font-semibold mb-2">' + data.email_count + ' VIP emails</div>';
        data.emails.forEach(function(e) {
            html += '<div class="border-l-2 border-yellow-500 pl-3 py-1 mb-2">';
            html += '<div class="text-sm font-medium">' + esc(e.subject) + '</div>';
            html += '<div class="text-xs text-gray-400">' + esc(e.from) + '</div>';
            html += '</div>';
        });
        html += '</div>';
        showResult(el, html);
    } catch (e) {
        showError(el, e.message);
    }
}

// ── Chat ──────────────────────────────────────────────────

let chatHistory;
try { chatHistory = JSON.parse(localStorage.getItem('hermes_chat') || '[]'); }
catch(e) { chatHistory = []; }

function renderChatHistory() {
    const el = document.getElementById('chat-messages');
    // Keep the welcome message
    const welcome = el.children[0];
    el.innerHTML = '';
    el.appendChild(welcome);

    chatHistory.forEach(function(m) {
        addChatBubble(m.role, m.content, false);
    });
    el.scrollTop = el.scrollHeight;
}

function addChatBubble(role, text, scroll) {
    const el = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'flex ' + (role === 'user' ? 'justify-end' : 'justify-start');

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble rounded-2xl px-4 py-3 text-sm fade-in ' +
        (role === 'user' ? 'bg-cyan-700 rounded-tr-sm' : 'bg-gray-800 rounded-tl-sm');
    bubble.textContent = text;

    div.appendChild(bubble);
    el.appendChild(div);
    if (scroll !== false) el.scrollTop = el.scrollHeight;
}

function addTypingIndicator() {
    const el = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.id = 'typing';
    div.className = 'flex justify-start';
    div.innerHTML = '<div class="chat-bubble bg-gray-800 rounded-2xl rounded-tl-sm px-4 py-3"><div class="spinner" style="width:18px;height:18px;border-width:2px;"></div></div>';
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
}

function removeTypingIndicator() {
    const t = document.getElementById('typing');
    if (t) t.remove();
}

document.getElementById('chat-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    const input = document.getElementById('chat-input');
    const text = input.value.trim();
    if (!text) return;

    input.value = '';
    addChatBubble('user', text);
    chatHistory.push({ role: 'user', content: text });
    addTypingIndicator();

    try {
        const data = await api('/api/chat', {
            method: 'POST',
            body: JSON.stringify({ messages: chatHistory }),
        });
        removeTypingIndicator();
        const response = data.response || 'No response.';
        addChatBubble('assistant', response);
        chatHistory.push({ role: 'assistant', content: response });
        localStorage.setItem('hermes_chat', JSON.stringify(chatHistory));
    } catch (err) {
        removeTypingIndicator();
        addChatBubble('assistant', 'Error: ' + err.message);
    }
});

// ── Emails ────────────────────────────────────────────────

async function loadEmails() {
    const el = document.getElementById('emails-list');
    showLoading(el);
    try {
        const data = await api('/api/emails?per_page=20');
        if (!data.emails || data.emails.length === 0) {
            el.innerHTML = '<div class="text-center text-gray-400 py-8">No unread emails</div>';
            return;
        }
        let html = '';
        data.emails.forEach(function(e) {
            const from = esc(e.from || '');
            const subj = esc(e.subject || '(no subject)');
            const snippet = esc(e.snippet || '');
            const date = esc(e.date || '');
            // Parse just time/date from email date
            let shortDate = '';
            try {
                const d = new Date(date);
                shortDate = d.toLocaleDateString(undefined, {month:'short', day:'numeric'}) + ' ' + d.toLocaleTimeString(undefined, {hour:'numeric', minute:'2-digit'});
            } catch(ex) { shortDate = date; }

            html += '<div class="bg-gray-800 rounded-xl p-3 fade-in" data-id="' + esc(e.id) + '">';
            html += '<div class="flex items-start justify-between gap-2">';
            html += '<div class="flex-1 min-w-0">';
            html += '<div class="font-semibold text-sm truncate">' + from + '</div>';
            html += '<div class="text-sm text-gray-200 truncate">' + subj + '</div>';
            html += '<div class="text-xs text-gray-500 truncate mt-1">' + snippet + '</div>';
            html += '</div>';
            html += '<div class="text-right flex-shrink-0">';
            html += '<div class="text-xs text-gray-500 whitespace-nowrap">' + shortDate + '</div>';
            html += '<button onclick="draftReply(\'' + esc(e.id) + '\', this)" class="mt-2 bg-cyan-700 hover:bg-cyan-600 text-white text-xs rounded-lg px-2 py-1 transition">Reply</button>';
            html += '</div></div>';
            html += '<div id="draft-' + e.id + '" class="hidden mt-2"></div>';
            html += '</div>';
        });
        el.innerHTML = html;
    } catch (e) {
        el.innerHTML = '<div class="bg-red-900 text-red-200 text-sm rounded-xl p-4">' + esc(e.message) + '</div>';
    }
}

async function draftReply(emailId, btn) {
    const el = document.getElementById('draft-' + emailId);
    if (!el) return;
    btn.disabled = true;
    btn.textContent = '...';
    el.innerHTML = '<div class="flex items-center gap-2 text-xs text-gray-400"><div class="spinner" style="width:14px;height:14px;border-width:2px;"></div> Drafting reply...</div>';
    el.classList.remove('hidden');
    try {
        const data = await api('/api/draft-reply', {
            method: 'POST',
            body: JSON.stringify({ email_id: emailId }),
        });
        if (data.needs_reply && data.draft) {
            el.innerHTML = '<div class="bg-gray-700 rounded-lg p-3 text-sm fade-in">' +
                '<div class="text-cyan-400 text-xs font-semibold mb-1">DRAFT REPLY</div>' +
                '<div class="text-gray-200 whitespace-pre-wrap">' + esc(data.draft) + '</div>' +
                '</div>';
        } else {
            el.innerHTML = '<div class="text-xs text-gray-500 italic fade-in">No reply needed</div>';
        }
        btn.textContent = 'Done';
    } catch (e) {
        el.innerHTML = '<div class="text-xs text-red-400 fade-in">' + esc(e.message) + '</div>';
        btn.textContent = 'Retry';
        btn.disabled = false;
    }
}

async function draftAllReplies() {
    const el = document.getElementById('draft-results');
    showLoading(el);
    try {
        const data = await api('/api/draft-replies-batch', {
            method: 'POST',
            body: JSON.stringify({ count: 10 }),
        });
        if (!data.drafts || data.drafts.length === 0) {
            showResult(el, '<div class="bg-gray-800 rounded-xl p-4 text-center text-gray-400">No emails to process</div>');
            return;
        }
        let html = '<div class="space-y-3">';
        html += '<div class="text-cyan-400 font-semibold">' + data.needs_reply + ' of ' + data.count + ' emails need replies</div>';
        data.drafts.forEach(function(d) {
            html += '<div class="bg-gray-800 rounded-xl p-3 fade-in">';
            html += '<div class="flex items-center gap-2 mb-1">';
            if (d.needs_reply) {
                html += '<span class="w-2 h-2 bg-cyan-400 rounded-full flex-shrink-0"></span>';
            } else {
                html += '<span class="w-2 h-2 bg-gray-600 rounded-full flex-shrink-0"></span>';
            }
            html += '<div class="font-semibold text-sm truncate">' + esc(d.subject) + '</div>';
            html += '</div>';
            html += '<div class="text-xs text-gray-400 mb-1">' + esc(d.from) + '</div>';
            if (d.needs_reply && d.draft) {
                html += '<div class="bg-gray-700 rounded-lg p-3 text-sm mt-2">';
                html += '<div class="text-cyan-400 text-xs font-semibold mb-1">DRAFT REPLY</div>';
                html += '<div class="text-gray-200 whitespace-pre-wrap">' + esc(d.draft) + '</div>';
                html += '</div>';
            } else {
                html += '<div class="text-xs text-gray-500 italic">No reply needed</div>';
            }
            html += '</div>';
        });
        html += '</div>';
        showResult(el, html);
    } catch (e) {
        showError(el, e.message);
    }
}

// ── Settings ──────────────────────────────────────────────

async function loadDomains() {
    const el = document.getElementById('domains-list');
    try {
        const data = await api('/api/domains');
        if (!data.domains || data.domains.length === 0) {
            el.innerHTML = '<div class="text-gray-500">No VIP domains configured.</div>';
            return;
        }
        let html = '';
        data.domains.forEach(function(d) {
            html += '<div class="flex items-center justify-between py-1">';
            html += '<div><span class="text-cyan-400">@' + esc(d.domain) + '</span>';
            html += '<span class="text-gray-500 ml-2 text-xs">' + esc(d.company || '') + '</span></div>';
            html += '<span class="text-xs text-gray-600">' + esc(d.category || '') + '</span>';
            html += '</div>';
        });
        el.innerHTML = html;
    } catch (e) {
        el.innerHTML = '<div class="text-red-400 text-sm">' + esc(e.message) + '</div>';
    }
}

async function getDigest() {
    const el = document.getElementById('digest-result');
    showLoading(el);
    try {
        const data = await api('/api/digest');
        let html = '<div class="bg-gray-800 rounded-xl p-4 space-y-2 mt-2">';
        html += '<div class="text-cyan-400 font-semibold">Weekly Digest</div>';
        html += '<div class="grid grid-cols-2 gap-2 text-sm">';
        html += '<div>Received: <span class="text-white font-semibold">' + data.received + '</span></div>';
        html += '<div>Sent: <span class="text-white font-semibold">' + data.sent + '</span></div>';
        html += '<div>Busiest: <span class="text-white font-semibold">' + esc(data.busiest_day) + '</span></div>';
        html += '<div>Unread: <span class="text-white font-semibold">' + data.unread_count + '</span></div>';
        html += '</div>';
        if (data.top_senders && data.top_senders.length) {
            html += '<div class="text-xs text-gray-400 mt-1">Top senders: ' + data.top_senders.map(esc).join(', ') + '</div>';
        }
        if (data.narrative) {
            html += '<div class="text-sm text-gray-300 mt-2 italic">' + esc(data.narrative) + '</div>';
        }
        html += '</div>';
        showResult(el, html);
    } catch (e) {
        showError(el, e.message);
    }
}


function renderEmailList(container, emails) {
    if (!emails || emails.length === 0) {
        container.innerHTML = '<div class="text-center text-gray-400 py-8">No emails found</div>';
        return;
    }
    var html = '';
    emails.forEach(function(e) {
        var from = esc(e.from || '');
        var subj = esc(e.subject || '(no subject)');
        var snippet = esc(e.snippet || '');
        var shortDate = '';
        try {
            var d = new Date(e.date);
            shortDate = d.toLocaleDateString(undefined, {month:'short', day:'numeric'}) + ' ' + d.toLocaleTimeString(undefined, {hour:'numeric', minute:'2-digit'});
        } catch(ex) { shortDate = ''; }

        html += '<div class="bg-gray-800 rounded-xl p-3 fade-in cursor-pointer hover:bg-gray-750 transition" onclick="openEmail(\'' + esc(e.id) + '\')">';
        html += '<div class="flex items-start justify-between gap-2">';
        html += '<div class="flex-1 min-w-0">';
        html += '<div class="font-semibold text-sm truncate">' + from + '</div>';
        html += '<div class="text-sm text-gray-200 truncate">' + subj + '</div>';
        html += '<div class="text-xs text-gray-500 truncate mt-1">' + snippet + '</div>';
        html += '</div>';
        html += '<div class="text-right flex-shrink-0">';
        html += '<div class="text-xs text-gray-500 whitespace-nowrap">' + shortDate + '</div>';
        html += '<button onclick="event.stopPropagation(); draftReply(\'' + esc(e.id) + '\', this)" class="mt-2 bg-cyan-700 hover:bg-cyan-600 text-white text-xs rounded-lg px-2 py-1 transition">Reply</button>';
        html += '</div></div>';
        html += '<div id="draft-' + e.id + '" class="hidden mt-2"></div>';
        html += '</div>';
    });
    container.innerHTML = html;
}

async function searchEmails(q) {
    if (!q.trim()) { loadEmails(); return; }
    var el = document.getElementById('emails-list');
    if (!el) return;
    showLoading(el);
    try {
        var data = await api('/api/emails?q=' + encodeURIComponent(q));
        renderEmailList(el, data.emails || []);
    } catch(e) { showToast('Search failed: ' + e.message); }
}


function debounce(fn, ms) {
    ms = ms || 1000;
    var timer;
    return function() {
        var args = arguments;
        var self = this;
        clearTimeout(timer);
        timer = setTimeout(function() { fn.apply(self, args); }, ms);
    };
}

// ── Voice ─────────────────────────────────────────────────

var voiceState = 'idle'; // idle | listening | processing
var recognition = null;
var voiceOutputEnabled = true;

function initVoice() {
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return; // browser doesn't support it

    var micBtn = document.getElementById('mic-btn');
    micBtn.classList.remove('hidden');

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onresult = function(event) {
        var transcript = '';
        var isFinal = false;
        for (var i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
            if (event.results[i].isFinal) isFinal = true;
        }
        document.getElementById('chat-input').value = transcript;
        if (isFinal) {
            setVoiceState('processing');
            sendVoiceMessage(transcript.trim());
        }
    };

    recognition.onerror = function(event) {
        if (event.error === 'not-allowed') {
            showToast('Mic permission denied — check browser settings');
        } else if (event.error === 'no-speech') {
            showToast('No speech detected', 'error');
        }
        // aborted is user-initiated cancel, no toast needed
        setVoiceState('idle');
    };

    recognition.onend = function() {
        if (voiceState === 'listening') setVoiceState('idle');
    };

    // Restore voice output preference
    var saved = localStorage.getItem('hermes_voice_output');
    if (saved !== null) {
        voiceOutputEnabled = saved === 'true';
        var cb = document.getElementById('voice-output-cb');
        if (cb) cb.checked = voiceOutputEnabled;
    }
}

function toggleVoice() {
    if (voiceState === 'listening') {
        recognition.abort();
        setVoiceState('idle');
        return;
    }
    // Cancel any ongoing speech
    window.speechSynthesis.cancel();
    setVoiceState('listening');
    try {
        recognition.start();
    } catch (e) {
        // Already started
        setVoiceState('idle');
    }
    // Show voice output toggle after first use
    document.getElementById('voice-output-toggle').classList.remove('hidden');
}

function setVoiceState(state) {
    voiceState = state;
    var micBtn = document.getElementById('mic-btn');
    var indicator = document.getElementById('voice-indicator');
    var statusText = document.getElementById('voice-status-text');

    micBtn.classList.remove('listening', 'processing');
    indicator.classList.add('hidden');

    if (state === 'listening') {
        micBtn.classList.add('listening');
        indicator.classList.remove('hidden');
        statusText.textContent = 'Listening...';
    } else if (state === 'processing') {
        micBtn.classList.add('processing');
        indicator.classList.remove('hidden');
        statusText.textContent = 'Processing...';
    }
}

async function sendVoiceMessage(text) {
    if (!text) { setVoiceState('idle'); return; }

    var input = document.getElementById('chat-input');
    input.value = '';
    addChatBubble('user', text);
    chatHistory.push({ role: 'user', content: text });
    addTypingIndicator();

    try {
        var data = await api('/api/chat', {
            method: 'POST',
            body: JSON.stringify({ messages: chatHistory, voice_mode: true }),
        });
        removeTypingIndicator();
        var response = data.response || 'No response.';
        addChatBubble('assistant', response);
        chatHistory.push({ role: 'assistant', content: response });
        localStorage.setItem('hermes_chat', JSON.stringify(chatHistory));
        if (voiceOutputEnabled) speakText(response);
    } catch (err) {
        removeTypingIndicator();
        addChatBubble('assistant', 'Error: ' + err.message);
    }
    setVoiceState('idle');
}

function speakText(text) {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();

    // Strip markdown artifacts
    text = text.replace(/[*_`#]/g, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');

    // Split into chunks at sentence boundaries (~200 chars) for iOS Safari
    var chunks = [];
    var sentences = text.match(/[^.!?]+[.!?]+\s*/g) || [text];
    var current = '';
    for (var i = 0; i < sentences.length; i++) {
        if (current.length + sentences[i].length > 200 && current.length > 0) {
            chunks.push(current.trim());
            current = '';
        }
        current += sentences[i];
    }
    if (current.trim()) chunks.push(current.trim());

    // Pick a good voice
    var voices = window.speechSynthesis.getVoices();
    var voice = null;
    // Prefer Samantha (iOS) or any local English voice
    for (var j = 0; j < voices.length; j++) {
        if (voices[j].name === 'Samantha') { voice = voices[j]; break; }
    }
    if (!voice) {
        for (var k = 0; k < voices.length; k++) {
            if (voices[k].lang.startsWith('en') && voices[k].localService) { voice = voices[k]; break; }
        }
    }

    chunks.forEach(function(chunk) {
        var utter = new SpeechSynthesisUtterance(chunk);
        if (voice) utter.voice = voice;
        utter.rate = 1.0;
        utter.pitch = 1.0;
        window.speechSynthesis.speak(utter);
    });
}

function toggleVoiceOutput(enabled) {
    voiceOutputEnabled = enabled;
    localStorage.setItem('hermes_voice_output', String(enabled));
    if (!enabled) window.speechSynthesis.cancel();
}

// ── Agents ────────────────────────────────────────────────

async function loadAgents() {
    var listEl = document.getElementById('agents-list');
    var logsEl = document.getElementById('agents-logs');
    var auditEl = document.getElementById('agents-audit');
    var schedEl = document.getElementById('scheduler-status');
    if (!listEl) return;
    showLoading(listEl);
    try {
        var data = await api('/api/agents');
        var sched = await api('/api/agents/scheduler');
        schedEl.textContent = sched.running ? 'Scheduler: ON (' + sched.scheduled_jobs.length + ' jobs)' : 'Scheduler: OFF';
        if (!data.agents || !data.agents.length) {
            listEl.innerHTML = '<div class="text-gray-400 text-sm text-center py-4">No agents configured</div>';
            return;
        }
        var html = '';
        data.agents.forEach(function(a) {
            var enabled = a.enabled;
            var badge = enabled ? '<span class="text-xs bg-green-700 text-green-200 px-2 py-0.5 rounded-full">ON</span>' : '<span class="text-xs bg-gray-700 text-gray-400 px-2 py-0.5 rounded-full">OFF</span>';
            var lastRun = a.last_run ? new Date(a.last_run * 1000).toLocaleString() : 'Never';
            var lastStatus = a.last_success === true ? '<span class="text-green-400 text-xs">OK</span>' : a.last_success === false ? '<span class="text-red-400 text-xs">FAIL</span>' : '';
            var sched = a.schedule || {};
            var schedStr = '';
            if (sched.type === 'interval') schedStr = 'Every ' + (sched.minutes || '?') + ' min';
            else if (sched.type === 'cron') { schedStr = sched.hour + ':' + String(sched.minute || 0).padStart(2, '0'); if (sched.day_of_week) schedStr += ' (' + sched.day_of_week + ')'; }
            else schedStr = sched.type || 'manual';

            html += '<div class="bg-gray-800 rounded-xl p-3 fade-in">';
            html += '<div class="flex items-center justify-between">';
            html += '<div class="flex items-center gap-2">' + badge + ' <span class="font-semibold text-sm">' + esc(a.display_name) + '</span></div>';
            html += '<div class="flex items-center gap-2">';
            html += '<button onclick="triggerAgent(\'' + esc(a.agent_id) + '\')" class="bg-cyan-700 hover:bg-cyan-600 text-white text-xs rounded-lg px-2 py-1 transition">Run</button>';
            html += '<button onclick="toggleAgent(\'' + esc(a.agent_id) + '\', ' + !enabled + ')" class="bg-gray-700 hover:bg-gray-600 text-white text-xs rounded-lg px-2 py-1 transition">' + (enabled ? 'Disable' : 'Enable') + '</button>';
            html += '</div></div>';
            html += '<div class="flex items-center gap-3 mt-1 text-xs text-gray-500">';
            html += '<span>' + schedStr + '</span>';
            html += '<span>Last: ' + lastRun + '</span>';
            html += lastStatus;
            if (a.last_execution_ms) html += '<span>' + a.last_execution_ms + 'ms</span>';
            html += '</div></div>';
        });
        listEl.innerHTML = html;
        loadAgentLogs();
        loadAgentAudit();
    } catch (e) {
        showError(listEl, e.message);
    }
}

async function triggerAgent(agentId) {
    showToast('Running ' + agentId + '...', 'success');
    try {
        var data = await api('/api/agents/' + agentId + '/trigger', { method: 'POST' });
        if (data.result && data.result.success) {
            showToast(agentId + ' completed (' + (data.result.emails_processed || 0) + ' emails)', 'success');
        } else {
            showToast(agentId + ' failed: ' + (data.result && data.result.error || 'unknown'), 'error');
        }
        loadAgents();
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

async function toggleAgent(agentId, enabled) {
    try {
        await api('/api/agents/' + agentId + '/enable', {
            method: 'POST',
            body: JSON.stringify({ enabled: enabled }),
        });
        loadAgents();
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

async function loadAgentLogs() {
    var el = document.getElementById('agents-logs');
    if (!el) return;
    try {
        var data = await api('/api/agents/logs?limit=10');
        if (!data.logs || !data.logs.length) {
            el.innerHTML = '<div class="text-gray-500 text-xs text-center">No activity yet</div>';
            return;
        }
        var html = '';
        data.logs.forEach(function(l) {
            var ok = l.success ? '<span class="text-green-400">OK</span>' : '<span class="text-red-400">FAIL</span>';
            var ts = '';
            try { ts = new Date(l.timestamp).toLocaleString(); } catch(e) { ts = l.timestamp || ''; }
            html += '<div class="bg-gray-800 rounded-lg p-2 text-xs flex items-center justify-between gap-2">';
            html += '<div class="flex items-center gap-2">' + ok + ' <span class="text-gray-300 font-medium">' + esc(l.agent_id) + '</span></div>';
            html += '<div class="flex items-center gap-2 text-gray-500">';
            html += '<span>' + (l.emails_processed || 0) + ' emails</span>';
            html += '<span>' + (l.execution_time_ms || 0) + 'ms</span>';
            html += '<span>' + ts + '</span>';
            html += '<button onclick="agentFeedback(\'' + esc(l.agent_id) + '\', ' + l.id + ', \'thumbs_up\')" class="hover:text-green-400" title="Good">+</button>';
            html += '<button onclick="agentFeedback(\'' + esc(l.agent_id) + '\', ' + l.id + ', \'thumbs_down\')" class="hover:text-red-400" title="Bad">-</button>';
            html += '</div></div>';
        });
        el.innerHTML = html;
    } catch (e) {
        el.innerHTML = '<div class="text-red-400 text-xs">' + esc(e.message) + '</div>';
    }
}

async function loadAgentAudit() {
    var el = document.getElementById('agents-audit');
    if (!el) return;
    try {
        var data = await api('/api/agents/audit?limit=10');
        if (!data.audit || !data.audit.length) {
            el.innerHTML = '<div class="text-gray-500 text-xs text-center">No config changes yet</div>';
            return;
        }
        var html = '';
        data.audit.forEach(function(a) {
            var approved = a.approved ? '<span class="text-green-400 text-xs">APPROVED</span>' : '<span class="text-red-400 text-xs">REJECTED</span>';
            var ts = '';
            try { ts = new Date(a.timestamp).toLocaleString(); } catch(e) { ts = a.timestamp || ''; }
            html += '<div class="bg-gray-800 rounded-lg p-2 text-xs">';
            html += '<div class="flex items-center justify-between">';
            html += '<span class="text-gray-300 font-medium">' + esc(a.agent_id) + '</span>';
            html += '<span>' + approved + '</span>';
            html += '</div>';
            html += '<div class="text-gray-500 mt-1">v' + (a.version_before || '?') + ' &rarr; v' + (a.version_after || '?') + ' &middot; ' + esc(a.field_changed || '') + ' &middot; by ' + esc(a.proposed_by || '') + '</div>';
            if (a.reason) html += '<div class="text-gray-400 mt-0.5">' + esc(a.reason) + '</div>';
            html += '<div class="text-gray-600 mt-0.5">' + ts + '</div>';
            html += '</div>';
        });
        el.innerHTML = html;
    } catch (e) {
        el.innerHTML = '<div class="text-red-400 text-xs">' + esc(e.message) + '</div>';
    }
}

async function agentFeedback(agentId, executionId, type) {
    try {
        await api('/api/agents/' + agentId + '/feedback', {
            method: 'POST',
            body: JSON.stringify({ type: type, execution_id: executionId }),
        });
        showToast('Feedback recorded', 'success');
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

// ── Init ──────────────────────────────────────────────────

renderChatHistory();
loadStats();
loadHomeEmails();
initVoice();

// Voices may load async — re-init voice list when available
if (window.speechSynthesis) {
    window.speechSynthesis.onvoiceschanged = function() {};
}

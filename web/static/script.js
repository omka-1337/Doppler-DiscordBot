// ---------------------------------------------------------------------
// LAYOUT BUILDER (Components V2): several independent cards (each its own
// Container: own accent color, own ordered text/image blocks), all sent
// together as ONE Discord message. No lines between cards, just spacing.

const elFileName = document.getElementById('fileName');
const cardsContainer = document.getElementById('cardsContainer');
const cardsEmptyHint = document.getElementById('cardsEmptyHint');
const previewCards = document.getElementById('previewCards');

let cardCounter = 0;
let blockCounter = 0;

function updateCardsEmptyHint() {
    if (cardsEmptyHint) {
        cardsEmptyHint.classList.toggle('hidden', cardsContainer.children.length > 0);
    }
}

function moveElement(el, direction) {
    const sibling = direction === 'up' ? el.previousElementSibling : el.nextElementSibling;
    if (!sibling) return;
    if (direction === 'up') {
        el.parentElement.insertBefore(el, sibling);
    } else {
        el.parentElement.insertBefore(sibling, el);
    }
    updatePreview();
}

// Shared move-up/move-down/remove button group used by both card and block rows.
function createControlButtons(row, onRemove) {
    const wrap = document.createElement('div');
    wrap.className = 'flex items-center gap-1';

    const upBtn = document.createElement('button');
    upBtn.type = 'button';
    upBtn.className = 'text-gray-400 hover:text-white text-xs px-1';
    upBtn.title = 'Move up';
    upBtn.textContent = '▲';
    upBtn.addEventListener('click', () => moveElement(row, 'up'));

    const downBtn = document.createElement('button');
    downBtn.type = 'button';
    downBtn.className = 'text-gray-400 hover:text-white text-xs px-1';
    downBtn.title = 'Move down';
    downBtn.textContent = '▼';
    downBtn.addEventListener('click', () => moveElement(row, 'down'));

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'text-red-400 hover:text-red-300 text-xs px-1';
    removeBtn.title = 'Remove';
    removeBtn.textContent = '✕';
    removeBtn.addEventListener('click', () => {
        row.remove();
        if (onRemove) onRemove();
        updatePreview();
    });

    wrap.appendChild(upBtn);
    wrap.appendChild(downBtn);
    wrap.appendChild(removeBtn);
    return wrap;
}

// ---------------------------------------------------------------------
// CARDS

function addCard() {
    const row = document.createElement('div');
    row.className = 'card-row bg-[#1e1f22] border border-[#3f4147] rounded-lg p-3';
    row.id = `card-${cardCounter++}`;

    const header = document.createElement('div');
    header.className = 'flex items-center justify-between mb-2';

    const labelWrap = document.createElement('div');
    labelWrap.className = 'flex items-center gap-2';

    const labelEl = document.createElement('span');
    labelEl.className = 'text-xs font-bold text-gray-300';
    labelEl.textContent = '🗂️ Card';

    const colorInput = document.createElement('input');
    colorInput.type = 'color';
    colorInput.className = 'card-color w-8 h-6 rounded cursor-pointer border border-[#3f4147]';
    colorInput.value = '#5865f2';
    colorInput.title = 'Card accent color';
    colorInput.addEventListener('input', updatePreview);

    labelWrap.appendChild(labelEl);
    labelWrap.appendChild(colorInput);

    header.appendChild(labelWrap);
    header.appendChild(createControlButtons(row, updateCardsEmptyHint));
    row.appendChild(header);

    const blocksDiv = document.createElement('div');
    blocksDiv.className = 'card-blocks space-y-2';
    row.appendChild(blocksDiv);

    const addButtonsWrap = document.createElement('div');
    addButtonsWrap.className = 'flex gap-3 mt-2';

    const addTextBtn = document.createElement('button');
    addTextBtn.type = 'button';
    addTextBtn.className = 'text-[11px] text-indigo-400 hover:text-indigo-300 font-semibold';
    addTextBtn.textContent = '📝 Add text';
    addTextBtn.addEventListener('click', () => addTextBlock(blocksDiv));

    const addImageBtn = document.createElement('button');
    addImageBtn.type = 'button';
    addImageBtn.className = 'text-[11px] text-indigo-400 hover:text-indigo-300 font-semibold';
    addImageBtn.textContent = '🖼️ Add image';
    addImageBtn.addEventListener('click', () => addImageBlock(blocksDiv));

    const addThumbBtn = document.createElement('button');
    addThumbBtn.type = 'button';
    addThumbBtn.className = 'text-[11px] text-indigo-400 hover:text-indigo-300 font-semibold';
    addThumbBtn.textContent = '🏞️ Add thumbnail';
    addThumbBtn.addEventListener('click', () => addThumbnailBlock(blocksDiv));

    const addLinksBtn = document.createElement('button');
    addLinksBtn.type = 'button';
    addLinksBtn.className = 'text-[11px] text-indigo-400 hover:text-indigo-300 font-semibold';
    addLinksBtn.textContent = '🔗 Add buttons';
    addLinksBtn.addEventListener('click', () => addButtonsBlock(blocksDiv));

    addButtonsWrap.appendChild(addTextBtn);
    addButtonsWrap.appendChild(addImageBtn);
    addButtonsWrap.appendChild(addThumbBtn);
    addButtonsWrap.appendChild(addLinksBtn);
    row.appendChild(addButtonsWrap);

    cardsContainer.appendChild(row);
    updateCardsEmptyHint();
    updatePreview();
}

// ---------------------------------------------------------------------
// BLOCKS (live inside a single card's .card-blocks container)

function addBlockShell(row, icon, label) {
    const header = document.createElement('div');
    header.className = 'flex items-center justify-between mb-1';

    const labelEl = document.createElement('span');
    labelEl.className = 'text-[10px] font-bold text-gray-400 uppercase';
    labelEl.textContent = `${icon} ${label}`;

    header.appendChild(labelEl);
    header.appendChild(createControlButtons(row));
    row.appendChild(header);
}

function addTextBlock(blocksDiv) {
    const row = document.createElement('div');
    row.className = 'block-row bg-[#2b2d31] border border-[#3f4147] rounded p-2';
    row.dataset.type = 'text';
    row.id = `block-${blockCounter++}`;
    addBlockShell(row, '📝', 'Text');

    const textarea = document.createElement('textarea');
    textarea.rows = 3;
    textarea.className = 'block-text-content w-full bg-[#1e1f22] border border-[#3f4147] rounded p-1.5 text-white text-xs focus:outline-none focus:border-indigo-500 transition';
    textarea.placeholder = 'Text content (Markdown supported)';
    textarea.addEventListener('input', updatePreview);
    row.appendChild(textarea);

    blocksDiv.appendChild(row);
    updatePreview();
}

// Shared by the image and thumbnail blocks: a URL field plus an upload, either
// of which supplies the block's media. Typing a URL clears a previous upload,
// and uploading clears the URL, so a block never carries both.
function addMediaInputs(row) {
    const urlInput = document.createElement('input');
    urlInput.type = 'text';
    urlInput.className = 'block-media-url w-full bg-[#1e1f22] border border-[#3f4147] rounded p-1.5 text-white text-xs focus:outline-none focus:border-indigo-500 transition';
    urlInput.placeholder = 'https://example.com/image.png';
    urlInput.addEventListener('input', () => {
        delete row.dataset.attachment;
        updatePreview();
    });
    row.appendChild(urlInput);

    const uploadWrap = document.createElement('div');
    uploadWrap.className = 'flex items-center gap-2 mt-1.5';

    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.png,.jpg,.jpeg';
    fileInput.className = 'flex-1 text-[11px] text-gray-400 file:mr-2 file:py-1 file:px-2 file:rounded file:border-0 file:bg-[#3f4147] file:text-white file:text-[11px]';

    const uploadBtn = document.createElement('button');
    uploadBtn.type = 'button';
    uploadBtn.className = 'bg-[#3f4147] hover:bg-[#4a4d53] text-white text-[11px] px-2.5 py-1.5 rounded font-semibold transition flex-shrink-0';
    uploadBtn.textContent = '⬆️ Upload';

    uploadWrap.appendChild(fileInput);
    uploadWrap.appendChild(uploadBtn);
    row.appendChild(uploadWrap);

    const status = document.createElement('p');
    status.className = 'text-[11px] mt-1';
    row.appendChild(status);

    uploadBtn.addEventListener('click', async () => {
        const file = fileInput.files[0];
        if (!file) {
            alert('Please choose an image file first');
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch('/api/upload-embed-image', { method: 'POST', body: formData });
            const data = await res.json();

            if (res.ok && data.status === 'ok') {
                row.dataset.attachment = data.filename;
                urlInput.value = '';
                status.textContent = `✅ Uploaded: ${file.name}`;
                status.className = 'text-[11px] mt-1 text-green-400';
                updatePreview();
            } else {
                status.textContent = `❌ ${data.detail || 'Upload failed'}`;
                status.className = 'text-[11px] mt-1 text-red-400';
            }
        } catch (err) {
            status.textContent = '❌ Error connecting to the server';
            status.className = 'text-[11px] mt-1 text-red-400';
        }
    });
}

function addImageBlock(blocksDiv) {
    const row = document.createElement('div');
    row.className = 'block-row bg-[#2b2d31] border border-[#3f4147] rounded p-2';
    row.dataset.type = 'image';
    row.id = `block-${blockCounter++}`;
    addBlockShell(row, '🖼️', 'Image');

    addMediaInputs(row);

    blocksDiv.appendChild(row);
    updatePreview();
}

// A thumbnail is not a standalone component in Discord: it is an accessory on a
// section of text, so this block asks for both.
function addThumbnailBlock(blocksDiv) {
    const row = document.createElement('div');
    row.className = 'block-row bg-[#2b2d31] border border-[#3f4147] rounded p-2';
    row.dataset.type = 'thumbnail';
    row.id = `block-${blockCounter++}`;
    addBlockShell(row, '🏞️', 'Thumbnail + text');

    const textarea = document.createElement('textarea');
    textarea.rows = 2;
    textarea.className = 'block-text-content w-full bg-[#1e1f22] border border-[#3f4147] rounded p-1.5 text-white text-xs focus:outline-none focus:border-indigo-500 transition mb-1.5';
    textarea.placeholder = 'Text shown beside the thumbnail (Markdown supported)';
    textarea.addEventListener('input', updatePreview);
    row.appendChild(textarea);

    addMediaInputs(row);

    blocksDiv.appendChild(row);
    updatePreview();
}

// Link buttons only. Coloured styles need something to answer the click, and a
// saved template has nobody to do that once the bot has restarted.
function addButtonsBlock(blocksDiv) {
    const row = document.createElement('div');
    row.className = 'block-row bg-[#2b2d31] border border-[#3f4147] rounded p-2';
    row.dataset.type = 'buttons';
    row.id = `block-${blockCounter++}`;
    addBlockShell(row, '🔗', 'Link buttons');

    const list = document.createElement('div');
    list.className = 'button-list space-y-1.5';
    row.appendChild(list);

    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'text-[11px] text-indigo-400 hover:text-indigo-300 font-semibold mt-1.5';
    addBtn.textContent = '＋ Add button';

    const addButtonRow = () => {
        if (list.children.length >= 5) return;   // Discord's limit for one row

        const item = document.createElement('div');
        item.className = 'button-item flex gap-1.5 items-center';

        const label = document.createElement('input');
        label.type = 'text';
        label.className = 'button-label w-1/3 bg-[#1e1f22] border border-[#3f4147] rounded p-1.5 text-white text-xs focus:outline-none focus:border-indigo-500 transition';
        label.placeholder = 'Label';
        label.addEventListener('input', updatePreview);

        const url = document.createElement('input');
        url.type = 'text';
        url.className = 'button-url flex-1 bg-[#1e1f22] border border-[#3f4147] rounded p-1.5 text-white text-xs focus:outline-none focus:border-indigo-500 transition';
        url.placeholder = 'https://example.com';
        url.addEventListener('input', updatePreview);

        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'text-gray-500 hover:text-red-400 transition text-xs px-1';
        remove.textContent = '✕';
        remove.addEventListener('click', () => {
            item.remove();
            addBtn.disabled = false;
            addBtn.classList.remove('opacity-40');
            updatePreview();
        });

        item.appendChild(label);
        item.appendChild(url);
        item.appendChild(remove);
        list.appendChild(item);

        if (list.children.length >= 5) {
            addBtn.disabled = true;
            addBtn.classList.add('opacity-40');
        }
        updatePreview();
    };

    addBtn.addEventListener('click', addButtonRow);
    row.appendChild(addBtn);
    addButtonRow();

    blocksDiv.appendChild(row);
    updatePreview();
}

// ---------------------------------------------------------------------
// COLLECT + PREVIEW + SAVE

// Reads the ordered block list straight out of one card's block container.
function collectBlocksFrom(blocksDiv) {
    const rows = blocksDiv.querySelectorAll('.block-row');
    const blocks = [];

    rows.forEach(row => {
        const type = row.dataset.type;

        if (type === 'text') {
            const content = row.querySelector('.block-text-content').value.trim();
            if (content) blocks.push({ type: 'text', content });

        } else if (type === 'image' || type === 'thumbnail') {
            const attachment = row.dataset.attachment;
            const url = row.querySelector('.block-media-url').value.trim();
            const media = attachment ? { attachment } : (url ? { url } : null);
            if (!media) return;

            if (type === 'image') {
                blocks.push({ type: 'image', ...media });
            } else {
                // A thumbnail without text has nothing to sit beside, and
                // Discord will not render the section at all.
                const content = row.querySelector('.block-text-content').value.trim();
                if (content) blocks.push({ type: 'thumbnail', content, ...media });
            }

        } else if (type === 'buttons') {
            const buttons = [];
            row.querySelectorAll('.button-item').forEach(item => {
                const label = item.querySelector('.button-label').value.trim();
                const url = item.querySelector('.button-url').value.trim();
                if (label && url) buttons.push({ label, url });
            });
            if (buttons.length) blocks.push({ type: 'buttons', buttons });
        }
    });

    return blocks;
}

// Reads all cards (in display order), each with its color + its blocks.
// Cards with no content are skipped.
function collectCards() {
    const cardRows = cardsContainer.querySelectorAll('.card-row');
    const cards = [];

    cardRows.forEach(cardRow => {
        const colorHex = cardRow.querySelector('.card-color').value;
        const accentColor = parseInt(colorHex.replace('#', ''), 16);
        const blocks = collectBlocksFrom(cardRow.querySelector('.card-blocks'));

        if (blocks.length) {
            cards.push({ accent_color: accentColor, blocks });
        }
    });

    return cards;
}

// On-the-fly preview: rebuilds each card as its own bordered box, stacked
// with a gap (no divider line) — matching how Components V2 renders them.
function updatePreview() {
    if (!previewCards) return;
    previewCards.innerHTML = '';

    const cards = collectCards();

    if (!cards.length) {
        const hint = document.createElement('p');
        hint.className = 'text-gray-500 text-sm italic';
        hint.textContent = 'Add a card to see a preview...';
        previewCards.appendChild(hint);
        return;
    }

    cards.forEach(card => {
        const cardEl = document.createElement('div');
        cardEl.className = 'bg-[#2b2d31] rounded-lg p-4 border-l-4';
        cardEl.style.borderColor = `#${card.accent_color.toString(16).padStart(6, '0')}`;

        card.blocks.forEach(block => {
            if (block.type === 'text') {
                const p = document.createElement('p');
                p.className = 'text-gray-300 text-sm whitespace-pre-line break-words mb-2 last:mb-0';
                p.textContent = block.content;
                cardEl.appendChild(p);

            } else if (block.type === 'image') {
                const src = block.attachment ? `/embed-images/${block.attachment}` : block.url;
                if (src) {
                    const img = document.createElement('img');
                    img.src = src;
                    img.alt = '';
                    img.className = 'rounded max-w-full max-h-64 object-cover mb-2 last:mb-0';
                    cardEl.appendChild(img);
                }

            } else if (block.type === 'thumbnail') {
                // Discord puts the thumbnail to the right of its text.
                const wrap = document.createElement('div');
                wrap.className = 'flex gap-3 items-start mb-2 last:mb-0';

                const p = document.createElement('p');
                p.className = 'text-gray-300 text-sm whitespace-pre-line break-words flex-1';
                p.textContent = block.content;
                wrap.appendChild(p);

                const src = block.attachment ? `/embed-images/${block.attachment}` : block.url;
                if (src) {
                    const img = document.createElement('img');
                    img.src = src;
                    img.alt = '';
                    img.className = 'rounded w-20 h-20 object-cover flex-shrink-0';
                    wrap.appendChild(img);
                }
                cardEl.appendChild(wrap);

            } else if (block.type === 'buttons') {
                const rowEl = document.createElement('div');
                rowEl.className = 'flex flex-wrap gap-2 mb-2 last:mb-0';
                block.buttons.forEach(b => {
                    const btn = document.createElement('span');
                    btn.className = 'bg-[#4e5058] text-white text-xs font-medium px-3 py-1.5 rounded flex items-center gap-1';
                    btn.textContent = b.label;
                    const icon = document.createElement('span');
                    icon.className = 'text-[10px] opacity-70';
                    icon.textContent = '↗';
                    btn.appendChild(icon);
                    rowEl.appendChild(btn);
                });
                cardEl.appendChild(rowEl);
            }
        });

        previewCards.appendChild(cardEl);
    });
}

// Sending JSON to FastAPI
async function saveEmbed() {
    const fileName = elFileName.value.trim();
    const statusMsg = document.getElementById('statusMsg');

    if (!fileName) {
        alert('Please enter the file name');
        return;
    }

    const cards = collectCards();
    if (!cards.length) {
        alert('Add at least one card with content before saving');
        return;
    }

    const embedPayload = {
        filename: fileName,
        embed: { cards }
    };

    try {
        const res = await fetch('/api/save-embed', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(embedPayload)
        });

        const data = await res.json();

        if (res.ok) {
            statusMsg.textContent = `✅ ${data.message}`;
            statusMsg.className = 'text-sm text-center font-semibold mt-2 text-green-400';
        } else {
            statusMsg.textContent = `❌ ${data.detail}`;
            statusMsg.className = 'text-sm text-center font-semibold mt-2 text-red-400';
        }
    } catch (err) {
        statusMsg.textContent = '❌ Error connecting to the server';
        statusMsg.className = 'text-sm text-center font-semibold mt-2 text-red-400';
    }
    statusMsg.classList.remove('hidden');
}

// ---------------------------------------------------------------------

// Save settings via API
async function saveSettings(event, category) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);

    // Choose active status element based on visible tab
    const isCogTab = !document.getElementById('tab-music').classList.contains('hidden');
    const statusMsg = isCogTab
        ? document.getElementById('moduleStatusMsg')
        : document.getElementById('settingsStatusMsg');

    const settingsPayload = {
        category: category,
        settings: {}
    };

    formData.forEach((value, key) => {
        settingsPayload.settings[key] = value;
    });

    try {
        const res = await fetch('/api/save-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settingsPayload)
        });

        const data = await res.json();

        if (res.ok) {
            statusMsg.textContent = `✅ ${data.message || 'The settings have been successfully saved'}`;
            statusMsg.className = 'text-sm font-semibold p-3 rounded bg-[#2b2d31] border border-green-500/50 text-green-400 text-center';
        } else {
            statusMsg.textContent = `❌ ${data.detail || 'Error saving'}`;
            statusMsg.className = 'text-sm font-semibold p-3 rounded bg-[#2b2d31] border border-red-500/50 text-red-400 text-center';
        }
    } catch (err) {
        statusMsg.textContent = '❌ Error connecting to the server';
        statusMsg.className = 'text-sm font-semibold p-3 rounded bg-[#2b2d31] border border-red-500/50 text-red-400 text-center';
    }

    statusMsg.classList.remove('hidden');
    setTimeout(() => {
        statusMsg.classList.add('hidden');
    }, 4000);
}

// ---------------------------------------------------------------------

// Loading settings from the database
async function loadSystemSettings() {
    try {
        const response = await fetch('/api/settings/system');
        if (!response.ok) throw new Error("Unable to load settings");

        const data = await response.json();

        const tokenInput = document.getElementById('set_discord_bot_token');
        const clientSecretInput = document.getElementById('set_discord_client_secret');

        if (tokenInput) tokenInput.value = data.discord_bot_token || '';
        if (clientSecretInput) clientSecretInput.value = data.discord_client_secret || '';

    } catch (error) {
        console.error("Error loading settings:", error);
    }
}

// ---------------------------------------------------------------------

async function loadYouTubeOAuthStatus() {
    const statusEl = document.getElementById('youtube-oauth-status');
    if (!statusEl) return;

    try {
        const res = await fetch('/api/music/youtube-oauth-status');
        const data = await res.json();

        if (res.ok && data.status == 'ok') {
            statusEl.textContent = data.configured ? '✅ Configured' : '⚠️ Not configured';
            statusEl.className = data.configured
                ? 'text-[10px] text-green-400'
                : 'text-[10px] text-amber-400';
        } else {
            statusEl.textContent = '❌ Unable to reach Lavalink';
            statusEl.className = 'text-[10px] text-red-400';
        }

    } catch (err) {
        console.error('Error loading YouTube OAuth status:', err);
        statusEl.textContent = '❌ Error connecting to server';
        statusEl.className = 'text-[10px] text-red-400';
    }
}

async function saveYouTubeOAuthToken() {
    const tokenInput = document.getElementById('youtube-refresh-token');
    if (!tokenInput) return;

    const token = tokenInput.value.trim();
    if (!token) {
        alert('Please enter a refresh token.');
        return;
    }

    try {
        const res = await fetch('/api/music/youtube-oauth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: token })
        });
        const data = await res.json();

        if (res.ok && data.status === 'ok') {
            alert('YouTube OAuth token saved successfully!');
            tokenInput.value = '';
            await loadYouTubeOAuthStatus();
        } else {
            alert('Failed to save token: ' + (data.message || 'unknown error'));
        }
    } catch (err) {
        console.error('Error saving YouTube OAuth token:', err);
        alert('Error connecting to the server.');
    }
}

// ---------------------------------------------------------------------

// ---------------------------------------------------------------------
// DASHBOARD STATS (uptime / CPU / RAM)

function formatUptime(totalSeconds) {
    const s = Math.floor(totalSeconds);
    const days = Math.floor(s / 86400);
    const hours = Math.floor((s % 86400) / 3600);
    const minutes = Math.floor((s % 3600) / 60);
    const seconds = s % 60;

    const parts = [];
    if (days) parts.push(`${days}d`);
    if (hours || days) parts.push(`${hours}h`);
    if (minutes || hours || days) parts.push(`${minutes}m`);
    parts.push(`${seconds}s`);
    return parts.join(' ');
}

async function refreshStats() {
    try {
        const res = await fetch('/api/stats');
        if (!res.ok) throw new Error('Failed to fetch stats');
        const data = await res.json();

        const cpuValue = document.getElementById('statCpuValue');
        const cpuBar = document.getElementById('statCpuBar');
        if (cpuValue && cpuBar) {
            cpuValue.textContent = `${data.cpu_percent.toFixed(1)}%`;
            cpuBar.style.width = `${Math.min(data.cpu_percent, 100)}%`;
        }

        const ramValue = document.getElementById('statRamValue');
        const ramBar = document.getElementById('statRamBar');
        if (ramValue && ramBar) {
            ramValue.textContent = `${data.memory_used_mb} / ${data.memory_total_mb} MB (${data.memory_percent.toFixed(1)}%)`;
            ramBar.style.width = `${Math.min(data.memory_percent, 100)}%`;
        }

        const statusDot = document.getElementById('statStatusDot');
        const statusText = document.getElementById('statStatus');
        const uptimeEl = document.getElementById('statUptime');
        const pluginsEl = document.getElementById('statPlugins');
        const latencyEl = document.getElementById('statLatency');

        if (data.bot) {
            const online = data.bot.connected;
            if (statusDot) statusDot.className = `w-2.5 h-2.5 rounded-full ${online ? 'bg-green-500' : 'bg-red-500'}`;
            if (statusText) statusText.textContent = online ? 'Online' : 'Offline';
            if (uptimeEl) uptimeEl.textContent = formatUptime(data.bot.uptime_seconds);
            if (pluginsEl) pluginsEl.textContent = data.bot.plugins_running;
            if (latencyEl) latencyEl.textContent = data.bot.latency_ms !== null ? `${data.bot.latency_ms} ms` : '—';
        } else {
            if (statusDot) statusDot.className = 'w-2.5 h-2.5 rounded-full bg-red-500';
            if (statusText) statusText.textContent = 'Unreachable';
            if (uptimeEl) uptimeEl.textContent = '—';
            if (pluginsEl) pluginsEl.textContent = '—';
            if (latencyEl) latencyEl.textContent = '—';
        }
    } catch (err) {
        console.error('Error fetching stats:', err);
    }
}

function initStats() {
    if (!document.getElementById('statCpuValue')) return;
    refreshStats();
    setInterval(refreshStats, 3000);
}

// ---------------------------------------------------------------------
// LIVE LOGS (WebSocket; auto-follows the tail unless the user scrolled up)

const LOG_LEVEL_COLORS = {
    ERROR: 'text-red-400',
    WARNING: 'text-yellow-400',
    INFO: 'text-gray-300',
};

function appendLogLine(panel, line) {
    const div = document.createElement('div');

    let colorClass = 'text-gray-300';
    for (const [level, cls] of Object.entries(LOG_LEVEL_COLORS)) {
        if (line.includes(`[${level}]`)) {
            colorClass = cls;
            break;
        }
    }
    div.className = colorClass;
    div.textContent = line;
    panel.appendChild(div);

    // Cap the number of rendered lines so the DOM doesn't grow forever.
    while (panel.children.length > 500) {
        panel.removeChild(panel.firstChild);
    }
}

function connectLogsWebSocket() {
    const panel = document.getElementById('logsPanel');
    const dot = document.getElementById('logsConnDot');
    const label = document.getElementById('logsConnLabel');
    if (!panel) return;

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/ws/logs`);

    ws.onopen = () => {
        if (dot) dot.className = 'w-2 h-2 rounded-full bg-green-500';
        if (label) label.textContent = 'Live';
    };

    ws.onmessage = (event) => {
        // Near-bottom scroll means "follow the tail"; otherwise leave the user's scroll position alone.
        const wasNearBottom = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 40;

        event.data.split('\n').forEach(line => {
            if (line) appendLogLine(panel, line);
        });

        if (wasNearBottom) {
            panel.scrollTop = panel.scrollHeight;
        }
    };

    ws.onclose = () => {
        if (dot) dot.className = 'w-2 h-2 rounded-full bg-red-500';
        if (label) label.textContent = 'Disconnected — retrying...';
        setTimeout(connectLogsWebSocket, 3000);
    };

    ws.onerror = () => {
        ws.close();
    };
}

// ---------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    loadSystemSettings();
    loadMusicBots();
    loadYouTubeOAuthStatus();
    initStats();
    connectLogsWebSocket();
    loadPluginPages();

});

async function saveSystemSettings(event) {
    event.preventDefault();

    const confirmed = confirm(
        "Are you sure you want to save the new keys?\n\n" +
        "If you change your Discord token, the bot will restart. Please wait a few seconds after saving."
    );

    if (!confirmed) return;

    const formData = new FormData(event.target);

    try {
        const response = await fetch('/api/settings/system', {
            method: 'POST',
            body: formData
        });

        const res = await response.json();

        if (res.status === 'restarting') {
            alert('Keys saved. The bot is restarting... The page will refresh in 5 seconds.');
            setTimeout(() => window.location.reload(), 5000);
        } else {
            alert('The keys have been successfully saved.');
        }
    } catch (e) {
        alert('A save error occurred, or the bot is restarting.');
    }
}

// Switch sub-categories inside Settings tab
function switchSettingsCategory(catName) {
    document.querySelectorAll('.settings-form').forEach(form => {
        form.classList.add('hidden');
    });

    document.querySelectorAll('.settings-cat-btn').forEach(btn => {
        btn.className = 'settings-cat-btn px-3 py-1.5 rounded text-xs font-semibold transition text-gray-400 hover:bg-[#35373c]';
    });

    const activeForm = document.getElementById(`form-settings-${catName}`);
    if (activeForm) {
        activeForm.classList.remove('hidden');
    }

    if (catName === 'AI') loadProviders();

    const activeBtn = document.getElementById(`cat-btn-${catName}`);
    if (activeBtn) {
        activeBtn.className = 'settings-cat-btn px-3 py-1.5 rounded text-xs font-semibold transition bg-indigo-600 text-white';
    }
}

// Tab Switcher
function switchTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.add('hidden');
    });

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.className = 'tab-btn px-4 py-2 rounded text-sm font-semibold transition text-gray-400 hover:bg-[#35373c]';
    });

    const activeTab = document.getElementById(`tab-${tabName}`);
    if (activeTab) {
        activeTab.classList.remove('hidden');
    }

    const activeBtn = document.getElementById(`btn-${tabName}`);
    if (activeBtn) {
        activeBtn.className = 'tab-btn px-4 py-2 rounded text-sm font-semibold transition bg-indigo-600 text-white';
    }

    if (tabName === 'plugins') {
        loadPlugins();
    }
    if (tabName.startsWith('plugin-')) {
        openPluginPage(tabName);
    }
}

// ---------------------------- MUSIC BOTS LOGIC ----------------------------

// Fetch and display all music bots on load
async function loadMusicBots() {
    try {
        const res = await fetch('/api/music/bots');
        if (!res.ok) throw new Error('Failed to fetch music bots');

        const data = await res.json();
        const container = document.getElementById('music-bots-container');
        if (!container) return;

        container.innerHTML = '';
        const bots = data.bots || [];

        bots.forEach(bot => {
            const rowElement = createMusicBotRow(bot);
            container.appendChild(rowElement);
        });
    } catch (err) {
        console.error('Error loading music bots:', err);
    }
}

// Generate single Music Bot DOM row
function createMusicBotRow(bot) {
    const botRowId = bot.id !== undefined ? bot.id : (bot.bot_rowid !== undefined ? bot.bot_rowid : bot[0]);
    const token = bot.bot_token !== undefined ? bot.bot_token : (bot.token || bot[1] || '');
    const isActive = bot.bot_status === 1 || bot.is_active === true || bot[3] === 1;

    const row = document.createElement('div');
    row.id = `music-bot-row-${botRowId}`;
    row.className = 'bg-[#1e1f22] p-3 rounded-lg border border-[#3f4147] flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3';

    row.innerHTML = `
        <div class="flex-1 flex items-center gap-2">
            <input type="password" id="music-token-${botRowId}" value="${token}" placeholder="Enter Bot Token..."
                class="w-full bg-[#2b2d31] border border-[#3f4147] rounded p-2 text-white text-xs font-mono focus:outline-none focus:border-indigo-500 transition">
            <button type="button" onclick="saveMusicBotToken(${botRowId})" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs px-3 py-2 rounded font-semibold transition flex-shrink-0">
                Save
            </button>
        </div>
        <div class="flex items-center justify-between sm:justify-end gap-4">
            <label class="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" id="music-active-${botRowId}" ${isActive ? 'checked' : ''} onchange="toggleMusicBotActive(${botRowId}, this.checked)" class="sr-only peer">
                <div class="w-9 h-5 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600"></div>
            </label>
            <button type="button" onclick="removeMusicBot(${botRowId})" class="bg-red-600/80 hover:bg-red-600 text-white text-xs px-2.5 py-1.5 rounded transition font-semibold flex-shrink-0">
                Delete
            </button>
        </div>
    `;

    return row;
}

// Add a new music bot instance
async function addMusicBot() {
    try {
        const res = await fetch('/api/music/add-bot', { method: 'POST' });
        const data = await res.json();

        if (res.ok && data.status === 'ok') {
            const container = document.getElementById('music-bots-container');
            const newRow = createMusicBotRow({ bot_rowid: data.bot_rowid, bot_token: '', is_active: false });
            container.appendChild(newRow);
        } else {
            alert('Failed to add new music bot.');
        }
    } catch (err) {
        console.error('Error adding music bot:', err);
        alert('Error connecting to the server.');
    }
}

// Save specific music bot token
async function saveMusicBotToken(botRowId) {
    const tokenInput = document.getElementById(`music-token-${botRowId}`);
    if (!tokenInput) return;

    const botToken = tokenInput.value.trim();

    try {
        const res = await fetch('/api/music/save-token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bot_rowid: botRowId, bot_token: botToken })
        });
        const data = await res.json();

        if (res.ok && data.status === 'ok') {
            alert('Music bot token saved successfully!');
        } else {
            alert('Failed to save token.');
        }
    } catch (err) {
        console.error('Error saving bot token:', err);
        alert('Error connecting to the server.');
    }
}

// Toggle active state (0 / 1)
async function toggleMusicBotActive(botRowId, isActive) {
    try {
        const res = await fetch('/api/music/toggle-active', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bot_rowid: botRowId, is_active: isActive })
        });
        const data = await res.json();

        if (!res.ok || data.status !== 'ok') {
            alert('Failed to toggle bot active state.');
            // Revert checkbox if request failed
            const chk = document.getElementById(`music-active-${botRowId}`);
            if (chk) chk.checked = !isActive;
        }
    } catch (err) {
        console.error('Error toggling bot state:', err);
        alert('Error connecting to the server.');
    }
}

// Remove music bot instance
async function removeMusicBot(botRowId) {
    if (!confirm('Are you sure you want to remove this music bot?')) return;

    try {
        const res = await fetch('/api/music/remove-bot', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bot_rowid: botRowId })
        });
        const data = await res.json();

        if (res.ok && data.status === 'ok') {
            const row = document.getElementById(`music-bot-row-${botRowId}`);
            if (row) row.remove();
        } else {
            alert('Failed to remove music bot.');
        }
    } catch (err) {
        console.error('Error removing music bot:', err);
        alert('Error connecting to the server.');
    }
}

async function handleToggle(event, botId) {
    event.preventDefault();

    await fetch('/api/music/toggle-active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bot_rowid: botId })
    });
}
// ---------------------------------------------------------------------
// PLUGINS
//
// Nothing here knows about any particular plugin: each one declares its
// settings in its own Python code, the bot serves that schema, and the cards
// and forms below are generated from it.

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

// One form row, rendered according to the field's declared type.
function renderPluginField(pluginId, field, value) {
    const inputId = `plg_${pluginId}_${field.key}`;
    const base = 'w-full bg-[#1e1f22] border border-[#3f4147] rounded p-2 text-white text-sm focus:outline-none focus:border-indigo-500 transition';
    const label = `<label class="block text-xs font-bold text-gray-400 uppercase mb-1">${escapeHtml(field.label)}</label>`;
    const hint = field.description
        ? `<p class="text-[11px] text-gray-400 mt-1">${escapeHtml(field.description)}</p>`
        : '';

    let input;
    switch (field.type) {
        case 'bool':
            return `
                <div class="flex items-center justify-between bg-[#1e1f22] p-3 rounded-lg border border-[#3f4147]">
                    <div>
                        <span class="block text-xs font-bold text-gray-300 uppercase">${escapeHtml(field.label)}</span>
                        ${field.description ? `<span class="text-[10px] text-gray-400">${escapeHtml(field.description)}</span>` : ''}
                    </div>
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" id="${inputId}" data-key="${escapeHtml(field.key)}" data-type="bool"
                            ${value === true || value === 'true' ? 'checked' : ''} class="sr-only peer">
                        <div class="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-600"></div>
                    </label>
                </div>`;

        case 'select':
            input = `<select id="${inputId}" data-key="${escapeHtml(field.key)}" data-type="select" class="${base}">
                ${field.choices.map(c =>
                    `<option value="${escapeHtml(c.value)}" ${String(value) === c.value ? 'selected' : ''}>${escapeHtml(c.label)}</option>`
                ).join('')}
            </select>`;
            break;

        case 'text':
            input = `<textarea id="${inputId}" data-key="${escapeHtml(field.key)}" data-type="text" rows="4" class="${base}">${escapeHtml(value)}</textarea>`;
            break;

        case 'secret':
            // Same reveal-on-hover treatment the other API key fields use.
            input = `<input type="password" id="${inputId}" data-key="${escapeHtml(field.key)}" data-type="secret"
                value="${escapeHtml(value)}" autocomplete="off"
                onmouseenter="this.type='text'" onmouseleave="this.type='password'"
                class="${base} font-mono">`;
            break;

        case 'slider':
            input = `<div class="flex items-center gap-3">
                <input type="range" id="${inputId}" data-key="${escapeHtml(field.key)}" data-type="slider"
                    min="${field.min}" max="${field.max}" step="${field.step ?? 0.1}" value="${escapeHtml(value)}"
                    oninput="document.getElementById('${inputId}_out').textContent = this.value"
                    class="flex-1 accent-indigo-600">
                <span id="${inputId}_out" class="text-xs text-gray-300 font-mono w-10 text-right">${escapeHtml(value)}</span>
            </div>`;
            break;

        case 'int':
        case 'float':
        case 'channel':
        case 'role':
            input = `<input type="number" id="${inputId}" data-key="${escapeHtml(field.key)}" data-type="${field.type}"
                value="${escapeHtml(value)}" ${field.type === 'float' ? 'step="any"' : ''}
                ${field.min !== null && field.min !== undefined ? `min="${field.min}"` : ''}
                ${field.max !== null && field.max !== undefined ? `max="${field.max}"` : ''}
                class="${base} font-mono">`;
            break;

        default:
            input = `<input type="text" id="${inputId}" data-key="${escapeHtml(field.key)}" data-type="string"
                value="${escapeHtml(value)}" class="${base}">`;
    }

    return `<div>${label}${input}${hint}</div>`;
}

// Which cards are open. Kept across re-renders so toggling or reloading a
// plugin doesn't collapse everything the user had expanded.
const expandedPlugins = new Set();

function togglePluginCard(pluginId) {
    const body = document.getElementById(`plugin-body-${pluginId}`);
    if (!body) return;

    const opening = body.classList.contains('hidden');
    body.classList.toggle('hidden', !opening);
    if (opening) {
        expandedPlugins.add(pluginId);
    } else {
        expandedPlugins.delete(pluginId);
    }

    const chevron = document.getElementById(`plugin-chevron-${pluginId}`);
    if (chevron) chevron.classList.toggle('rotate-90', opening);
}

function renderPluginCard(plugin) {
    const values = plugin.values || {};
    const statusText = plugin.running
        ? '<span class="text-[10px] text-green-400 font-semibold">● RUNNING</span>'
        : (plugin.enabled
            ? '<span class="text-[10px] text-red-400 font-semibold">● FAILED</span>'
            : '<span class="text-[10px] text-gray-500 font-semibold">● DISABLED</span>');

    // Shown outside the collapsible body: a plugin that failed to load should
    // say so without the user having to open it first.
    const error = plugin.error
        ? `<p class="text-[11px] text-red-400 bg-red-500/10 border border-red-500/30 rounded p-2 font-mono mx-5 mb-4">${escapeHtml(plugin.error)}</p>`
        : '';

    // Settings are only readable while the plugin is running, since the schema
    // lives in the plugin's own code.
    const fields = (plugin.settings_schema || [])
        .map(f => renderPluginField(plugin.id, f, values[f.key]))
        .join('');

    const expandable = plugin.running && fields;
    const isOpen = expandable && expandedPlugins.has(plugin.id);

    const chevron = expandable
        ? `<span id="plugin-chevron-${plugin.id}"
               class="text-gray-500 text-xs mt-1.5 transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}">▶</span>`
        : '<span class="w-2"></span>';

    // A plugin with nothing to configure shouldn't look clickable.
    const hint = plugin.running && !fields
        ? '<span class="text-[10px] text-gray-600">· no settings</span>'
        : '';

    const header = expandable
        ? `class="flex items-start justify-between gap-4 p-5 cursor-pointer hover:bg-[#313338] transition rounded-lg"
           onclick="togglePluginCard('${plugin.id}')"`
        : 'class="flex items-start justify-between gap-4 p-5"';

    const body = expandable
        ? `<div id="plugin-body-${plugin.id}" class="${isOpen ? '' : 'hidden'} px-5 pb-5 space-y-4 border-t border-[#3f4147] pt-4">
               ${fields}
               <button onclick="savePluginSettings('${plugin.id}')"
                   class="bg-indigo-600 hover:bg-indigo-500 text-white font-bold px-6 py-2 rounded transition shadow-md text-sm">
                   💾 Save settings
               </button>
           </div>`
        : '';

    return `
    <div class="bg-[#2b2d31] rounded-lg border border-[#3f4147] shadow-lg">
        <div ${header}>
            <div class="flex items-start gap-3">
                ${chevron}
                <span class="text-2xl leading-none">${escapeHtml(plugin.icon)}</span>
                <div>
                    <h3 class="text-white font-bold flex items-center gap-2">
                        ${escapeHtml(plugin.name)}
                        <span class="text-[10px] text-gray-500 font-mono">v${escapeHtml(plugin.version)}</span>
                        ${statusText}
                    </h3>
                    <p class="text-xs text-gray-400 mt-1">${escapeHtml(plugin.description)}</p>
                    <p class="text-[10px] text-gray-500 mt-1 font-mono">
                        ${escapeHtml(plugin.id)}${plugin.author ? ' · ' + escapeHtml(plugin.author) : ''} · ${escapeHtml(plugin.installed_from)} ${hint}
                    </p>
                </div>
            </div>
            <!-- The controls sit inside the clickable header, so their clicks
                 must not also open or close the card. -->
            <div class="flex items-center gap-3 shrink-0" onclick="event.stopPropagation()">
                ${plugin.installed_from !== 'local' ? `
                <button onclick="uninstallPlugin('${plugin.id}')" title="Remove this plugin's files"
                    class="bg-[#1e1f22] hover:bg-red-600/80 border border-[#3f4147] text-gray-300 hover:text-white px-3 py-1.5 rounded transition text-xs font-semibold">
                    🗑
                </button>` : ''}
                <button onclick="reloadPlugin('${plugin.id}')" title="Reload this plugin's code without restarting the bot"
                    class="bg-[#1e1f22] hover:bg-[#35373c] border border-[#3f4147] text-gray-300 px-3 py-1.5 rounded transition text-xs font-semibold">
                    ♻️ Reload
                </button>
                <label class="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" ${plugin.enabled ? 'checked' : ''}
                        onchange="togglePlugin('${plugin.id}', this.checked)" class="sr-only peer">
                    <div class="w-11 h-6 bg-gray-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-600"></div>
                </label>
            </div>
        </div>
        ${error}
        ${body}
    </div>`;
}

async function loadPlugins() {
    const list = document.getElementById('pluginsList');
    if (!list) return;

    try {
        const res = await fetch('/api/plugins');
        const data = await res.json();

        if (!res.ok) {
            list.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(data.detail || 'Could not reach the bot.')}</p>`;
            return;
        }

        const plugins = data.plugins || [];
        list.innerHTML = plugins.length
            ? plugins.map(renderPluginCard).join('')
            : '<p class="text-xs text-gray-400">No plugins installed yet.</p>';
    } catch (e) {
        list.innerHTML = '<p class="text-xs text-red-400">Error connecting to the server.</p>';
    }
}

async function rescanPlugins() {
    try {
        await fetch('/api/plugins/rescan', { method: 'POST' });
    } catch (e) {
        // loadPlugins() reports the failure to the user.
    }
    loadPlugins();
}

async function togglePlugin(pluginId, enabled) {
    try {
        const res = await fetch('/api/plugins/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plugin: pluginId, enabled })
        });
        if (!res.ok) {
            const data = await res.json();
            alert(`Failed to ${enabled ? 'enable' : 'disable'} ${pluginId}: ${data.detail || 'unknown error'}`);
        }
    } catch (e) {
        alert('Error connecting to the server.');
    }
    loadPlugins();
}

async function reloadPlugin(pluginId) {
    try {
        const res = await fetch('/api/plugins/reload', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plugin: pluginId })
        });
        const data = await res.json();
        alert(res.ok ? `${pluginId} reloaded.` : `Reload failed: ${data.detail || 'unknown error'}`);
    } catch (e) {
        alert('Error connecting to the server.');
    }
    loadPlugins();
}

async function savePluginSettings(pluginId) {
    const values = {};
    document.querySelectorAll(`[id^="plg_${pluginId}_"]`).forEach(el => {
        const key = el.dataset.key;
        if (!key) return;
        values[key] = el.dataset.type === 'bool' ? el.checked : el.value;
    });

    try {
        const res = await fetch('/api/plugins/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plugin: pluginId, values })
        });
        const data = await res.json();
        alert(res.ok ? 'Settings saved.' : `Save failed: ${data.detail || 'unknown error'}`);
    } catch (e) {
        alert('Error connecting to the server.');
    }
}

// ---------------------------------------------------------------------
// PLUGIN BROWSER
//
// The bot cannot install anything itself: the plugins directory and the trust
// configuration are read-only in its container. Everything here goes through
// the bot to the broker, which is the only component allowed to write them.

function switchPluginView(view) {
    document.querySelectorAll('.plugin-view').forEach(pane => pane.classList.add('hidden'));
    document.querySelectorAll('.plugin-view-btn').forEach(btn => {
        btn.className = 'plugin-view-btn px-3 py-1.5 rounded text-xs font-semibold transition text-gray-400 hover:bg-[#35373c]';
    });

    const paneId = { installed: 'pluginInstalled', browse: 'pluginBrowse', sources: 'pluginSources' }[view];
    const pane = document.getElementById(paneId);
    if (pane) pane.classList.remove('hidden');

    const btn = document.getElementById(`plgview-btn-${view}`);
    if (btn) btn.className = 'plugin-view-btn px-3 py-1.5 rounded text-xs font-semibold transition bg-indigo-600 text-white';

    if (view === 'browse') loadCatalog();
    if (view === 'sources') loadPluginSources();
    if (view === 'installed') loadPlugins();
}

function trustBadge(trusted) {
    return trusted
        ? '<span class="text-[10px] text-green-400 font-semibold">✓ TRUSTED</span>'
        : '<span class="text-[10px] text-amber-400 font-semibold">⚠ UNTRUSTED</span>';
}

function renderCatalogEntry(entry) {
    const services = (entry.services || []).length
        ? `<span class="text-[10px] text-amber-400" title="This plugin runs a container of its own">📦 runs ${escapeHtml((entry.services || []).join(', '))}</span>`
        : '';

    const action = entry.installed
        ? `<button onclick="installPlugin('${entry.source}', '${entry.id}')"
               class="bg-[#1e1f22] hover:bg-[#35373c] border border-[#3f4147] text-gray-300 px-3 py-1.5 rounded transition text-xs font-semibold">
               ⬆ Reinstall
           </button>
           <button onclick="uninstallPlugin('${entry.id}')"
               class="bg-red-600/80 hover:bg-red-600 text-white px-3 py-1.5 rounded transition text-xs font-semibold">
               🗑 Uninstall
           </button>`
        : `<button onclick="installPlugin('${entry.source}', '${entry.id}')"
               class="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-1.5 rounded transition text-xs font-bold">
               ⬇ Install
           </button>`;

    const installedNote = entry.installed
        ? `<span class="text-[10px] text-gray-500">installed v${escapeHtml(entry.installed_version || '?')}</span>`
        : '';

    return `
    <div class="bg-[#2b2d31] p-5 rounded-lg border border-[#3f4147] shadow-lg flex items-start justify-between gap-4">
        <div class="flex items-start gap-3">
            <span class="text-2xl leading-none">${escapeHtml(entry.icon || '🧩')}</span>
            <div>
                <h3 class="text-white font-bold flex items-center gap-2 flex-wrap">
                    ${escapeHtml(entry.name || entry.id)}
                    <span class="text-[10px] text-gray-500 font-mono">v${escapeHtml(entry.version || '?')}</span>
                    ${trustBadge(entry.trusted)}
                    ${installedNote}
                </h3>
                <p class="text-xs text-gray-400 mt-1">${escapeHtml(entry.description || '')}</p>
                <p class="text-[10px] text-gray-500 mt-1 font-mono">
                    ${escapeHtml(entry.id)}${entry.author ? ' · ' + escapeHtml(entry.author) : ''} · from ${escapeHtml(entry.source_label || entry.source)}
                    ${services}
                </p>
            </div>
        </div>
        <div class="flex items-center gap-2 shrink-0">${action}</div>
    </div>`;
}

async function loadCatalog() {
    const list = document.getElementById('pluginCatalog');
    if (!list) return;
    list.innerHTML = '<p class="text-xs text-gray-400">Loading catalogue...</p>';

    try {
        const res = await fetch('/api/plugins/catalog');
        const data = await res.json();
        if (!res.ok) {
            list.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(data.detail || 'Could not reach the broker.')}</p>`;
            return;
        }

        // A source that cannot be reached is reported rather than silently
        // dropped, so a typo in a repo name is visible.
        const errors = Object.entries(data.errors || {})
            .map(([name, message]) =>
                `<p class="text-[11px] text-red-400 bg-red-500/10 border border-red-500/30 rounded p-2 font-mono">${escapeHtml(name)}: ${escapeHtml(message)}</p>`)
            .join('');

        const entries = (data.plugins || []).map(renderCatalogEntry).join('');
        list.innerHTML = errors + (entries || '<p class="text-xs text-gray-400">No plugins offered by the configured sources.</p>');
    } catch (e) {
        list.innerHTML = '<p class="text-xs text-red-400">Error connecting to the server.</p>';
    }
}

async function installPlugin(source, pluginId) {
    if (!confirm(`Install "${pluginId}" from "${source}"?\n\nThis runs someone else's code inside your bot.`)) return;

    try {
        const res = await fetch('/api/plugins/install', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source, plugin: pluginId })
        });
        const data = await res.json();
        if (!res.ok) {
            alert(`Install failed: ${data.detail || 'unknown error'}`);
        } else if (data.error) {
            alert(`${pluginId} was installed but failed to load:\n\n${data.error}`);
        } else {
            alert(`${pluginId} installed${data.running ? ' and running' : ''}.`);
        }
    } catch (e) {
        alert('Error connecting to the server.');
    }
    loadCatalog();
}

async function uninstallPlugin(pluginId) {
    if (!confirm(`Uninstall "${pluginId}"?\n\nIts files and any containers it started are removed. Its saved settings are kept.`)) return;

    try {
        const res = await fetch('/api/plugins/uninstall', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ plugin: pluginId })
        });
        const data = await res.json();
        if (!res.ok) alert(`Uninstall failed: ${data.detail || 'unknown error'}`);
    } catch (e) {
        alert('Error connecting to the server.');
    }
    // Called from both the catalogue and the installed list, so refresh
    // whichever pane is actually on screen.
    if (!document.getElementById('pluginBrowse').classList.contains('hidden')) {
        loadCatalog();
    } else {
        loadPlugins();
    }
}

function renderSourceRow(source, installedCount) {
    return `
    <div class="bg-[#2b2d31] p-4 rounded-lg border border-[#3f4147] flex items-center justify-between gap-4">
        <div>
            <h4 class="text-white font-bold text-sm flex items-center gap-2">
                ${escapeHtml(source.label || source.name)} ${trustBadge(source.trusted)}
            </h4>
            <p class="text-[11px] text-gray-400 mt-1 font-mono">
                ${escapeHtml(source.repo)} · ${escapeHtml(source.branch)}
                ${installedCount ? `· ${installedCount} installed` : ''}
            </p>
        </div>
        <div class="flex items-center gap-3 shrink-0">
            <label class="flex items-center gap-2 cursor-pointer" title="Trusted sources may run sidecar containers">
                <span class="text-[10px] text-gray-400 uppercase font-bold">Trusted</span>
                <span class="relative inline-flex items-center">
                    <input type="checkbox" ${source.trusted ? 'checked' : ''}
                        onchange="setSourceTrust('${source.name}', this.checked)" class="sr-only peer">
                    <span class="w-11 h-6 bg-gray-700 rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-green-600"></span>
                </span>
            </label>
            <button onclick="removePluginSource('${source.name}')"
                class="bg-[#1e1f22] hover:bg-red-600/80 border border-[#3f4147] text-gray-300 hover:text-white px-3 py-1.5 rounded transition text-xs font-semibold">
                Remove
            </button>
        </div>
    </div>`;
}

async function loadPluginSources() {
    const list = document.getElementById('sourcesList');
    if (!list) return;

    try {
        const res = await fetch('/api/plugins/sources');
        const data = await res.json();
        if (!res.ok) {
            list.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(data.detail || 'Could not reach the broker.')}</p>`;
            return;
        }

        const installed = data.installed || {};
        const counts = {};
        Object.values(installed).forEach(entry => {
            counts[entry.source] = (counts[entry.source] || 0) + 1;
        });

        const rows = (data.sources || []).map(s => renderSourceRow(s, counts[s.name] || 0)).join('');
        list.innerHTML = rows || '<p class="text-xs text-gray-400">No sources configured.</p>';
    } catch (e) {
        list.innerHTML = '<p class="text-xs text-red-400">Error connecting to the server.</p>';
    }
}

async function addPluginSource() {
    const name = document.getElementById('source-name').value.trim();
    const repo = document.getElementById('source-repo').value.trim();
    const branch = document.getElementById('source-branch').value.trim() || 'main';

    if (!name || !repo) {
        alert('A short name and an owner/repository are both required.');
        return;
    }

    try {
        const res = await fetch('/api/plugins/sources/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, repo, branch, label: name })
        });
        const data = await res.json();
        if (!res.ok) {
            alert(`Could not add the source: ${data.detail || 'unknown error'}`);
        } else {
            document.getElementById('source-name').value = '';
            document.getElementById('source-repo').value = '';
        }
    } catch (e) {
        alert('Error connecting to the server.');
    }
    loadPluginSources();
}

async function setSourceTrust(name, trusted) {
    if (trusted && !confirm(
        `Mark "${name}" as trusted?\n\nPlugins from a trusted source are allowed to start containers of their own.`
    )) {
        loadPluginSources();
        return;
    }

    try {
        await fetch('/api/plugins/sources/trust', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, trusted })
        });
    } catch (e) {
        alert('Error connecting to the server.');
    }
    loadPluginSources();
}

async function removePluginSource(name) {
    if (!confirm(`Remove the source "${name}"?\n\nPlugins already installed from it stay, but stop being trusted.`)) return;

    try {
        await fetch('/api/plugins/sources/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, trusted: false })
        });
    } catch (e) {
        alert('Error connecting to the server.');
    }
    loadPluginSources();
}

// ---------------------------------------------------------------------
// PROVIDERS (AI)
//
// The broker holds these keys in a volume the bot container cannot see, and
// never returns their values — only whether each one is set. So this form is
// built from that metadata, and an untouched field means "leave as is".
//
// Only credentials live here. A plugin that can pick between backends declares
// that choice as its own setting instead — the translator's free-or-AI switch,
// for one.

const PROVIDER_SECTIONS = [
    {
        section: 'ai',
        title: 'AI chat',
        choices: [['gemini', 'Google Gemini'], ['deepseek', 'DeepSeek'], ['chatgpt', 'ChatGPT']],
        keys: [
            ['gemini_api_key', 'Gemini API key'],
            ['deepseek_api_key', 'DeepSeek API key'],
            ['chatgpt_api_key', 'ChatGPT API key'],
        ],
    },
];

function renderProviderSection(spec, state) {
    const configured = (state && state.configured) || {};
    const current = (state && state.provider) || spec.choices[0][0];

    const options = spec.choices
        .map(([v, label]) => `<option value="${v}" ${current === v ? 'selected' : ''}>${escapeHtml(label)}</option>`)
        .join('');

    const keys = spec.keys.map(([key, label]) => `
        <div>
            <label class="block text-xs font-bold text-gray-400 uppercase mb-1.5">
                ${escapeHtml(label)}
                ${configured[key]
                    ? '<span class="text-[10px] text-green-400 font-semibold ml-1">✓ set</span>'
                    : '<span class="text-[10px] text-gray-500 font-semibold ml-1">not set</span>'}
            </label>
            <input type="password" id="prov_${spec.section}_${key}" autocomplete="off"
                placeholder="${configured[key] ? 'Saved — type to replace' : 'Not set'}"
                class="w-full bg-[#1e1f22] border border-[#3f4147] rounded-lg p-2.5 text-white font-mono text-sm focus:outline-none focus:border-indigo-500 transition">
        </div>`).join('');

    return `
    <div class="space-y-4 pb-5 border-b border-[#3f4147] last:border-0">
        <h4 class="text-sm font-bold text-white">${escapeHtml(spec.title)}</h4>
        <div>
            <label class="block text-xs font-bold text-gray-400 uppercase mb-1.5">Provider</label>
            <select id="prov_${spec.section}_provider"
                class="w-full bg-[#1e1f22] border border-[#3f4147] rounded-lg p-2.5 text-white text-sm focus:outline-none focus:border-indigo-500 transition">
                ${options}
            </select>
            ${spec.hint ? `<p class="text-[11px] text-gray-400 mt-1">${escapeHtml(spec.hint)}</p>` : ''}
        </div>
        ${keys}
        <button onclick="saveProviders('${spec.section}')"
            class="bg-indigo-600 hover:bg-indigo-500 text-white font-bold px-6 py-2 rounded transition shadow-md text-sm">
            💾 Save
        </button>
    </div>`;
}

async function loadProviders() {
    const host = document.getElementById('providersForm');
    if (!host) return;

    try {
        const res = await fetch('/api/providers');
        const data = await res.json();
        if (!res.ok) {
            host.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(data.detail || 'Could not reach the broker.')}</p>`;
            return;
        }
        host.innerHTML = PROVIDER_SECTIONS
            .map(spec => renderProviderSection(spec, (data.providers || {})[spec.section]))
            .join('');
    } catch (e) {
        host.innerHTML = '<p class="text-xs text-red-400">Error connecting to the server.</p>';
    }
}

async function saveProviders(section) {
    const spec = PROVIDER_SECTIONS.find(s => s.section === section);
    if (!spec) return;

    const values = { provider: document.getElementById(`prov_${section}_provider`).value };
    // An empty field means "keep whatever is stored", so a saved key survives
    // saving the form without retyping it.
    spec.keys.forEach(([key]) => {
        const el = document.getElementById(`prov_${section}_${key}`);
        if (el && el.value.trim()) values[key] = el.value.trim();
    });

    try {
        const res = await fetch('/api/providers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ section, values })
        });
        const data = await res.json();
        alert(res.ok ? 'Provider settings saved.' : `Save failed: ${data.detail || 'unknown error'}`);
    } catch (e) {
        alert('Error connecting to the server.');
    }
    loadProviders();
}

// ---------------------------------------------------------------------
// USER MENU

function toggleUserMenu(event) {
    event.stopPropagation();
    const menu = document.getElementById('userMenu');
    if (!menu) return;

    const opening = menu.classList.contains('hidden');
    menu.classList.toggle('hidden', !opening);

    const chevron = document.getElementById('userMenuChevron');
    if (chevron) chevron.classList.toggle('rotate-180', opening);
}

function closeUserMenu() {
    const menu = document.getElementById('userMenu');
    if (menu) menu.classList.add('hidden');
    const chevron = document.getElementById('userMenuChevron');
    if (chevron) chevron.classList.remove('rotate-180');
}

// A menu that only closes by clicking the button again is a nuisance.
document.addEventListener('click', closeUserMenu);
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeUserMenu();
});

// ---------------------------------------------------------------------
// PLUGIN PAGES
//
// A plugin's own page runs in an iframe with sandbox="allow-scripts" and,
// deliberately, no allow-same-origin. The frame therefore gets an opaque
// origin: it cannot read the dashboard's DOM, cannot send its cookies, and
// cannot call the dashboard's API on the operator's behalf. Without that, a
// plugin's page could simply POST to /api/plugins/sources/trust and mark its
// own source trusted — defeating the one boundary that actually holds.
//
// Everything it needs goes through postMessage to the shim below, which only
// ever forwards to that plugin's own endpoints.

const pluginFrames = new Map();   // iframe element -> plugin id

// Injected ahead of the plugin's own HTML.
const PLUGIN_PAGE_SHIM = `<script>
(function () {
    let seq = 0;
    const pending = new Map();

    window.addEventListener('message', function (event) {
        const msg = event.data;
        if (!msg || msg.__doppler !== 'reply') return;
        const entry = pending.get(msg.id);
        if (!entry) return;
        pending.delete(msg.id);
        if (msg.error) entry.reject(new Error(msg.error));
        else entry.resolve(msg.result);
    });

    window.doppler = {
        // Call one of this plugin's own declared endpoints.
        call: function (method, path, body) {
            const id = ++seq;
            return new Promise(function (resolve, reject) {
                pending.set(id, { resolve: resolve, reject: reject });
                parent.postMessage({ __doppler: 'call', id: id, method: method, path: path, body: body }, '*');
            });
        }
    };
})();
<\/script>`;

window.addEventListener('message', async event => {
    const msg = event.data;
    if (!msg || msg.__doppler !== 'call') return;

    // A sandboxed frame's origin is the string "null", so it proves nothing.
    // Identify the sender by its window instead: that cannot be forged.
    let pluginId = null;
    for (const [frame, id] of pluginFrames) {
        if (frame.contentWindow === event.source) { pluginId = id; break; }
    }
    if (!pluginId) return;

    const reply = (result, error) =>
        event.source.postMessage({ __doppler: 'reply', id: msg.id, result, error }, '*');

    const path = typeof msg.path === 'string' ? msg.path : '';
    if (!path.startsWith('/') || path.includes('..')) {
        reply(null, 'Invalid path');
        return;
    }

    try {
        // Confined to this plugin's own endpoints — the frame cannot name
        // another plugin, let alone a dashboard route.
        const res = await fetch(`/api/plugin/${pluginId}${path}`, {
            method: (msg.method || 'GET').toUpperCase(),
            headers: msg.body === undefined ? {} : { 'Content-Type': 'application/json' },
            body: msg.body === undefined ? undefined : JSON.stringify(msg.body),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) reply(null, data.detail || data.message || `HTTP ${res.status}`);
        else reply(data);
    } catch (e) {
        reply(null, String(e));
    }
});

async function loadPluginPages() {
    let pages;
    try {
        const res = await fetch('/api/plugin-pages');
        if (!res.ok) return;
        pages = (await res.json()).pages || [];
    } catch (e) {
        return;
    }

    const settingsBtn = document.getElementById('btn-settings');
    const navBar = settingsBtn ? settingsBtn.parentElement : null;
    const main = document.querySelector('main');
    if (!navBar || !main) return;

    pages.forEach(page => {
        const tabName = `plugin-${page.plugin}`;
        if (document.getElementById(`tab-${tabName}`)) return;

        const btn = document.createElement('button');
        btn.id = `btn-${tabName}`;
        btn.className = 'tab-btn px-4 py-2 rounded text-sm font-semibold transition text-gray-400 hover:bg-[#35373c]';
        btn.textContent = `${page.icon} ${page.title}`;
        btn.addEventListener('click', () => switchTab(tabName));
        navBar.insertBefore(btn, settingsBtn);

        const pane = document.createElement('div');
        pane.id = `tab-${tabName}`;
        pane.className = 'tab-content hidden';
        pane.dataset.plugin = page.plugin;
        pane.innerHTML = '<p class="text-xs text-gray-400">Loading...</p>';
        main.appendChild(pane);
    });
}

// Loaded on first open rather than up front: a page nobody visits should not
// cost a request, and its scripts should not be running in the background.
async function openPluginPage(tabName) {
    const pane = document.getElementById(`tab-${tabName}`);
    if (!pane || pane.dataset.loaded) return;

    const pluginId = pane.dataset.plugin;
    try {
        const res = await fetch(`/api/plugin-page/${pluginId}`);
        const data = await res.json();
        if (!res.ok) {
            pane.innerHTML = `<p class="text-xs text-red-400">${escapeHtml(data.detail || 'Could not load the page.')}</p>`;
            return;
        }

        const frame = document.createElement('iframe');
        frame.className = 'w-full rounded-lg border border-[#3f4147] bg-[#2b2d31]';
        frame.style.height = '78vh';
        frame.setAttribute('sandbox', 'allow-scripts');
        frame.srcdoc = PLUGIN_PAGE_SHIM + data.html;

        pane.innerHTML = '';
        pane.appendChild(frame);
        pluginFrames.set(frame, pluginId);
        pane.dataset.loaded = '1';
    } catch (e) {
        pane.innerHTML = '<p class="text-xs text-red-400">Error connecting to the server.</p>';
    }
}

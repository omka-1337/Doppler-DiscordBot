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

    addButtonsWrap.appendChild(addTextBtn);
    addButtonsWrap.appendChild(addImageBtn);
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

function addImageBlock(blocksDiv) {
    const row = document.createElement('div');
    row.className = 'block-row bg-[#2b2d31] border border-[#3f4147] rounded p-2';
    row.dataset.type = 'image';
    row.id = `block-${blockCounter++}`;
    addBlockShell(row, '🖼️', 'Image');

    const urlInput = document.createElement('input');
    urlInput.type = 'text';
    urlInput.className = 'block-image-url w-full bg-[#1e1f22] border border-[#3f4147] rounded p-1.5 text-white text-xs focus:outline-none focus:border-indigo-500 transition';
    urlInput.placeholder = 'https://example.com/image.png';
    urlInput.addEventListener('input', () => {
        // Typing a URL by hand supersedes a previously uploaded file for this block.
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

        } else if (type === 'image') {
            const attachment = row.dataset.attachment;
            const url = row.querySelector('.block-image-url').value.trim();
            if (attachment) {
                blocks.push({ type: 'image', attachment });
            } else if (url) {
                blocks.push({ type: 'image', url });
            }
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
    const isCogTab = !document.getElementById('tab-cogs').classList.contains('hidden');
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

    // Explicitly set boolean toggle states for specific module categories
    if (category === 'AI') {
        const aiChk = document.getElementById('chk_ai_enabled');
        const forceLangChk = document.getElementById('chk_ai_force_language');
        if (forceLangChk) settingsPayload.settings['ai_force_language'] = forceLangChk.checked ? 'true' : 'false';
    }

    if (category === 'Moderation') {
        const modLogChk = document.getElementById('chk_mod_log_enabled');
        if (modLogChk) settingsPayload.settings['mod_log_enabled'] = modLogChk.checked ? 'true' : 'false';
    }

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

async function toggleModule(moduleName, enabled) {
    try {
        const res = await fetch('/api/toggle-module', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ module: moduleName, enabled })
        });
        const data = await res.json();
        if (!res.ok || data.status !== 'ok') {
            alert('Failed to toggle module.');
        }
    } catch (err) {
        console.error('Error toggling module:', err);
        alert('Error connecting to the server.')
    }
}

// ---------------------------------------------------------------------

// Loading settings from the database
async function loadSystemSettings() {
    try {
        const response = await fetch('/api/settings/system');
        if (!response.ok) throw new Error("Unable to load settings");

        const data = await response.json();

        const apiKeyInput = document.getElementById('set_gemini_api_key');
        const tokenInput = document.getElementById('set_discord_bot_token');

        if (apiKeyInput) apiKeyInput.value = data.gemini_api_key || '';
        if (tokenInput) tokenInput.value = data.discord_bot_token || '';

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

// Call the function as soon as the page loads
// Show only the API key field relevant to the currently selected Translator provider
function toggleTranslatorProviderFields() {
    const select = document.getElementById('set_translator_provider');
    const deeplBlock = document.getElementById('translator-deepl-key-block');
    const googleBlock = document.getElementById('translator-google-key-block');
    if (!select || !deeplBlock || !googleBlock) return;

    const isDeepl = select.value === 'deepl';
    deeplBlock.classList.toggle('hidden', !isDeepl);
    googleBlock.classList.toggle('hidden', isDeepl);
}

// ---------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    loadSystemSettings();
    loadMusicBots();
    toggleTranslatorProviderFields();
    loadYouTubeOAuthStatus();

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

// Switch sub-categories inside Modules tab
function switchModuleCategory(catName) {
    document.querySelectorAll('.module-form').forEach(form => {
        form.classList.add('hidden');
    });

    document.querySelectorAll('.module-cat-btn').forEach(btn => {
        btn.className = 'module-cat-btn px-3 py-1.5 rounded text-xs font-semibold transition text-gray-400 hover:bg-[#35373c]';
    });

    const activeForm = document.getElementById(`form-module-${catName}`);
    if (activeForm) {
        activeForm.classList.remove('hidden');
    }

    const activeBtn = document.getElementById(`mod-btn-${catName}`);
    if (activeBtn) {
        activeBtn.className = 'module-cat-btn px-3 py-1.5 rounded text-xs font-semibold transition bg-indigo-600 text-white';
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
}

// Add handler for 'Music' module in saveSettings function
const originalSaveSettings = window.saveSettings;
window.saveSettings = async function (event, category) {
    if (category === 'Music') {
        const musicChk = document.getElementById('chk_music_enabled');
        if (musicChk) {
            // Include music module toggle into generic settings payload
            const isCogTab = !document.getElementById('tab-cogs').classList.contains('hidden');
            const statusMsg = isCogTab
                ? document.getElementById('moduleStatusMsg')
                : document.getElementById('settingsStatusMsg');

            const settingsPayload = {
                category: 'Modules',
                settings: {
                    music_enabled: musicChk.checked ? 'true' : 'false'
                }
            };

            try {
                const res = await fetch('/api/save-settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settingsPayload)
                });
                const data = await res.json();
                if (res.ok) {
                    statusMsg.textContent = `✅ ${data.message || 'Music module settings saved'}`;
                    statusMsg.className = 'text-sm font-semibold p-3 rounded bg-[#2b2d31] border border-green-500/50 text-green-400 text-center';
                } else {
                    statusMsg.textContent = `❌ ${data.detail || 'Error saving settings'}`;
                    statusMsg.className = 'text-sm font-semibold p-3 rounded bg-[#2b2d31] border border-red-500/50 text-red-400 text-center';
                }
            } catch (err) {
                statusMsg.textContent = '❌ Error connecting to server';
                statusMsg.className = 'text-sm font-semibold p-3 rounded bg-[#2b2d31] border border-red-500/50 text-red-400 text-center';
            }
            statusMsg.classList.remove('hidden');
            setTimeout(() => statusMsg.classList.add('hidden'), 4000);
            event.preventDefault();
            return;
        }
    }
    return originalSaveSettings(event, category);
};

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
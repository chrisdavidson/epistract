// chat.js - Chat panel: messages, SSE streaming, markdown rendering

let chatHistory = [];  // D-08: session-only
let callbacks = {};
let template = {};

export function initChat(opts) {
    callbacks = opts || {};
    template = opts.template || {};
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');

    // Handle form submit
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        const question = input.value.trim();
        if (!question) return;
        sendMessage(question);
        input.value = '';
        input.style.height = 'auto';
    });

    // Auto-resize textarea
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    // Enter to send (Shift+Enter for newline)
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            form.dispatchEvent(new Event('submit'));
        }
    });

    // Starter prompts (D-10)
    document.querySelectorAll('.starter-card').forEach(card => {
        card.addEventListener('click', () => {
            const question = card.textContent.trim();
            sendMessage(question);
        });
    });

    // Listen for "ask question" events from graph panel (D-16 "Ask about this")
    window.addEventListener('ask-question', (e) => {
        const question = e.detail.question;
        input.value = question;
        input.focus();
    });
}

async function sendMessage(question) {
    const messages = document.getElementById('messages');
    const welcome = document.getElementById('welcome');

    // Hide welcome on first message
    if (welcome) welcome.style.display = 'none';

    // Add user message
    const userDiv = document.createElement('div');
    userDiv.className = 'chat-msg chat-msg--user';
    userDiv.textContent = question;
    messages.appendChild(userDiv);

    // Add assistant message placeholder
    const assistantDiv = document.createElement('div');
    assistantDiv.className = 'chat-msg chat-msg--assistant';
    assistantDiv.innerHTML = '<span class="loading-dots">' + (template.loading_message || 'Analyzing') + '</span>';
    messages.appendChild(assistantDiv);
    messages.scrollTop = messages.scrollHeight;

    // Add to history
    chatHistory.push({ role: 'user', content: question });

    // Stream response via SSE (D-09)
    let fullResponse = '';
    try {
        const selectedModel = document.getElementById('model-select')?.value || null;
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, history: chatHistory.slice(0, -1), model: selectedModel }),
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.type === 'text') {
                            fullResponse += data.content;
                            // Render markdown incrementally (D-11)
                            assistantDiv.innerHTML = renderMarkdown(fullResponse);
                            messages.scrollTop = messages.scrollHeight;
                        } else if (data.type === 'error') {
                            const errEl = document.createElement('div');
                            errEl.className = 'error-msg';
                            errEl.textContent = data.content;
                            assistantDiv.replaceChildren(errEl);
                        } else if (data.type === 'done') {
                            if (!fullResponse) {
                                assistantDiv.innerHTML = '<div class="error-msg">No response received. The model may be rate-limited, unavailable, or the request exceeded its context limit. Try a different model or a shorter question.</div>';
                            } else {
                                assistantDiv.innerHTML = linkifyCitations(renderMarkdown(fullResponse));
                            }
                        }
                    } catch (e) {
                        console.warn('SSE parse error:', line, e);
                    }
                }
            }
        }
    } catch (error) {
        assistantDiv.innerHTML = '<div class="error-msg">Could not reach the analysis engine. Check that the server is running and ANTHROPIC_API_KEY is set.</div>';
    }

    // Add response to history (D-08)
    if (fullResponse) {
        chatHistory.push({ role: 'assistant', content: fullResponse });
    }
}

function renderMarkdown(text) {
    // Use marked.js (loaded via CDN) for markdown rendering (D-11)
    if (typeof marked !== 'undefined') {
        const raw = marked.parse(text);
        // Sanitize with DOMPurify when available (marked v5+ removed built-in sanitizer)
        return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(raw) : raw;
    }
    // Fallback: basic HTML escaping
    return text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
}

function linkifyCitations(html) {
    // Post-process rendered HTML to convert [Contract Name] to clickable links (D-19)
    // Match [text] that wasn't already converted to <a> by markdown
    return html.replace(/\[([^\]]+)\](?!\()/g, (match, name) => {
        // Skip markdown checkbox patterns
        if (name === 'x' || name === ' ') return match;
        // Convert contract name to doc_id format
        const docId = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
        return `<a href="#" class="citation-link" data-doc="${docId}" data-section="${escapeAttr(name)}" onclick="event.preventDefault(); window.dispatchEvent(new CustomEvent('navigate-source', {detail: {docId: '${docId}', section: '${escapeAttr(name)}'}})); return false;">${match}</a>`;
    });
}

function escapeAttr(str) {
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------------------
// Model selector (populated from /api/models)
// ---------------------------------------------------------------------------

const CATEGORY_ORDER = [
    "Claude (Anthropic)",
    "GPT / O-series (OpenAI)",
    "Qwen (Alibaba)",
    "Gemini / Gemma (Google)",
    "Mistral",
    "Llama (Meta)",
    "DeepSeek",
    "Grok (xAI)",
    "Nvidia",
    "Amazon",
    "Perplexity",
    "Cohere",
    "Other",
];

function buildGroupedOptions(models, select) {
    select.innerHTML = '';
    const grouped = {};
    for (const m of models) {
        const g = m.group || 'Other';
        if (!grouped[g]) grouped[g] = [];
        grouped[g].push(m);
    }
    for (const group of CATEGORY_ORDER) {
        const members = grouped[group];
        if (!members || members.length === 0) continue;
        const og = document.createElement('optgroup');
        og.label = group;
        for (const m of members) {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.label;
            og.appendChild(opt);
        }
        select.appendChild(og);
    }
}

function buildCostSortedOptions(models, select) {
    select.innerHTML = '';
    const sorted = [...models].sort((a, b) => (a.prompt_cost || 0) - (b.prompt_cost || 0));
    for (const m of sorted) {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.label;
        select.appendChild(opt);
    }
}

export async function loadModelSelector() {
    const select = document.getElementById('model-select');
    const sortBtn = document.getElementById('model-sort-btn');
    if (!select || !sortBtn) return;

    let resp;
    try {
        resp = await fetch('/api/models');
    } catch (e) {
        select.style.display = 'none';
        sortBtn.style.display = 'none';
        return;
    }
    if (!resp.ok) {
        select.style.display = 'none';
        sortBtn.style.display = 'none';
        return;
    }

    let data;
    try {
        data = await resp.json();
    } catch (e) {
        select.style.display = 'none';
        sortBtn.style.display = 'none';
        return;
    }

    const models = Array.isArray(data.models) ? data.models : [];
    if (models.length <= 1) {
        select.style.display = 'none';
        sortBtn.style.display = 'none';
        return;
    }

    const hasGroups = models.some(m => m && typeof m.group === 'string' && m.group.length > 0);
    let sortByCost = localStorage.getItem('epistract_model_sort') === 'cost';

    function render() {
        if (hasGroups && !sortByCost) {
            buildGroupedOptions(models, select);
        } else {
            buildCostSortedOptions(models, select);
        }
    }

    render();
    select.style.display = '';

    // Restore last-used model only if it still exists in the catalog (stale-value guard).
    const stored = localStorage.getItem('epistract_model');
    if (stored && models.some(m => m.id === stored)) {
        select.value = stored;
    }

    select.addEventListener('change', () => {
        localStorage.setItem('epistract_model', select.value);
    });

    if (hasGroups) {
        sortBtn.style.display = '';
        const updateSortBtnLabel = () => {
            if (sortByCost) {
                sortBtn.innerHTML = '&#9636;';  // ▤
                sortBtn.title = 'Group by provider';
            } else {
                sortBtn.innerHTML = '$&uarr;';  // $↑
                sortBtn.title = 'Sort by cost (cheapest first)';
            }
        };
        updateSortBtnLabel();
        sortBtn.addEventListener('click', () => {
            sortByCost = !sortByCost;
            localStorage.setItem('epistract_model_sort', sortByCost ? 'cost' : 'group');
            render();
            updateSortBtnLabel();
            // Re-restore selection if it still exists.
            const cur = localStorage.getItem('epistract_model');
            if (cur && models.some(m => m.id === cur)) {
                select.value = cur;
            }
        });
    } else {
        sortBtn.style.display = 'none';
    }
}

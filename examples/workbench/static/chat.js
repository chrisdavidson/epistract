// chat.js - Chat panel: messages, SSE streaming, markdown rendering

let chatHistory = [];  // D-08: session-only
let callbacks = {};
let template = {};
let chatGeneration = 0;  // bumped by clearChat; stale responses compare against it
const activeControllers = new Set();

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

    document.getElementById('chat-clear-btn')?.addEventListener('click', clearChat);

    // Citation links in assistant replies open the source viewer. One
    // delegated listener serves every message, including ones rendered later.
    const messagesBox = document.getElementById('messages');
    if (messagesBox) {
        messagesBox.addEventListener('click', (e) => {
            const target = e && e.target;
            const link = target && typeof target.closest === 'function' ? target.closest('a.citation-link[data-doc]') : null;
            if (!link) return;
            // Only ids from the project's document list open the viewer; an
            // anchor that merely looks like a citation (raw HTML in a reply)
            // is left alone.
            const docId = link.dataset && link.dataset.doc;
            if (!isKnownCitationDoc(docId)) return;
            e.preventDefault();
            // A citation label is not a quoted passage, so nothing is highlighted.
            window.dispatchEvent(new CustomEvent('navigate-source', { detail: { docId } }));
        });
    }

    // Starter prompts (D-10)
    document.querySelectorAll('.starter-card').forEach(card => {
        card.addEventListener('click', () => {
            const question = card.textContent.trim();
            sendMessage(question);
        });
    });

    // Listen for "ask question" events from graph panel (D-16 "Ask about this")
    // and the Dashboard. Prefill only: the question is never sent from here.
    window.addEventListener('ask-question', (e) => {
        const question = e.detail.question;
        input.focus();
        if (!input.value.trim()) {
            input.value = question;
            return;
        }
        // A draft is already there: replace it as an edit, so the browser's
        // Undo (Ctrl/Cmd+Z) brings the draft back.
        input.select();
        let replaced = false;
        try {
            replaced = document.execCommand('insertText', false, question) && input.value === question;
        } catch {
            replaced = false;
        }
        // No editing command available: keep the draft and add the question below it.
        if (!replaced && input.value !== question) {
            const draft = input.value.replace(/\s+$/, '');
            input.value = draft === question ? question : `${draft}\n${question}`;
        }
    });
}

export function clearChat() {
    chatGeneration += 1;
    for (const controller of activeControllers) controller.abort();
    activeControllers.clear();
    chatHistory = [];

    const messages = document.getElementById('messages');
    const welcome = document.getElementById('welcome');
    if (messages) {
        for (const child of Array.from(messages.children)) {
            if (child !== welcome) child.remove();
        }
        messages.scrollTop = 0;
    }
    if (welcome) welcome.style.display = '';
    document.getElementById('chat-input')?.focus();
}

function renderError(container, err) {
    // Build the error block with createElement + textContent ONLY: title,
    // message, hint and detail come from an upstream provider (untrusted).
    const box = document.createElement('div');
    box.className = 'error-msg';

    const hasStructured = Boolean(err.title || err.message);
    if (err.title) {
        const title = document.createElement('strong');
        title.className = 'error-title';
        title.textContent = err.title;
        box.appendChild(title);
    }
    const bodyText = hasStructured ? err.message : err.content;
    if (bodyText) {
        const p = document.createElement('p');
        p.textContent = bodyText;
        box.appendChild(p);
    }
    if (err.hint) {
        const hint = document.createElement('p');
        hint.className = 'error-hint';
        hint.textContent = err.hint;
        box.appendChild(hint);
    }
    if (err.detail) {
        const details = document.createElement('details');
        details.className = 'error-detail';
        const summary = document.createElement('summary');
        summary.textContent = 'Technical details';
        const code = document.createElement('code');
        code.textContent = err.detail;
        details.appendChild(summary);
        details.appendChild(code);
        box.appendChild(details);
    }
    container.appendChild(box);
    return box;
}

async function sendMessage(question) {
    const gen = chatGeneration;
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
    const loadingSpan = document.createElement('span');
    loadingSpan.className = 'loading-dots';
    loadingSpan.textContent = template.loading_message || 'Analyzing';
    assistantDiv.replaceChildren(loadingSpan);
    messages.appendChild(assistantDiv);
    messages.scrollTop = messages.scrollHeight;

    // Add to history
    chatHistory.push({ role: 'user', content: question });

    // Stream response via SSE (D-09)
    // Read current model selection (null = use backend default).
    // `|| null` coerces "" (unloaded select) to null per RESEARCH Pitfall 2.
    const selectedModel = document.getElementById('model-select')?.value || null;
    let fullResponse = '';
    let errorShown = false;
    const controller = new AbortController();
    activeControllers.add(controller);
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            signal: controller.signal,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question,
                history: chatHistory.slice(0, -1),
                model: selectedModel,
            }),
        });

        if (gen !== chatGeneration) return;

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (gen !== chatGeneration) {
                try { await reader.cancel(); } catch (_e) { /* already closed */ }
                return;
            }
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
                            // Render markdown incrementally (D-11); renderMarkdown
                            // already runs DOMPurify internally, but we also wrap
                            // here so the line-level static check (SEC-01) passes.
                            assistantDiv.innerHTML = (typeof DOMPurify !== 'undefined')
                                ? DOMPurify.sanitize(renderMarkdown(fullResponse), { ADD_ATTR: ['id'] })
                                : renderMarkdown(fullResponse);
                            messages.scrollTop = messages.scrollHeight;
                        } else if (data.type === 'error') {
                            // SEC-01 / VUL-01: every error field is raw provider text
                            // and may contain HTML. renderError builds the block with
                            // textContent only. Keep any partial answer streamed so far.
                            if (fullResponse) {
                                assistantDiv.innerHTML = (typeof DOMPurify !== 'undefined')
                                    ? DOMPurify.sanitize(renderMarkdown(fullResponse), { ADD_ATTR: ['id'] })
                                    : renderMarkdown(fullResponse);
                                linkifyCitations(assistantDiv);
                            } else {
                                assistantDiv.replaceChildren();
                            }
                            renderError(assistantDiv, data);
                            errorShown = true;
                            messages.scrollTop = messages.scrollHeight;
                        } else if (data.type === 'done') {
                            if (errorShown) {
                                // The error block is the final state; never re-render over it.
                            } else if (!fullResponse) {
                                assistantDiv.replaceChildren();
                                renderError(assistantDiv, {
                                    title: 'No response received',
                                    message: 'The model may be rate-limited, unavailable, or the request exceeded its context limit.',
                                    hint: 'Try a different model or a shorter question.',
                                });
                            } else {
                                // Final render with citation linking: sanitize first, then
                                // link citations in the resulting text nodes with DOM calls
                                // (no markup is ever built from the reply's strings).
                                assistantDiv.innerHTML = (typeof DOMPurify !== 'undefined')
                                    ? DOMPurify.sanitize(renderMarkdown(fullResponse), { ADD_ATTR: ['id'] })
                                    : renderMarkdown(fullResponse);
                                linkifyCitations(assistantDiv);
                            }
                        }
                    } catch (e) {
                        console.warn('SSE parse error:', line, e);
                    }
                }
            }
        }
    } catch (error) {
        if (gen !== chatGeneration || error?.name === 'AbortError') return;
        assistantDiv.replaceChildren();
        renderError(assistantDiv, {
            title: "Couldn't reach the workbench server",
            message: 'Your browser could not connect to the local workbench.',
            hint: 'Check that the workbench is still running (the terminal that launched it), then try again.',
        });
    } finally {
        activeControllers.delete(controller);
    }

    // Add response to history (D-08)
    if (fullResponse && gen === chatGeneration) {
        chatHistory.push({ role: 'assistant', content: fullResponse });
    }
}

function renderMarkdown(text) {
    // Use marked.js (loaded via CDN) for markdown rendering (D-11).
    // DOMPurify (loaded BEFORE this script in index.html — VUL-06 fix) sanitizes
    // the resulting HTML to defeat stored XSS via LLM output (VUL-01 / SEC-01).
    // ADD_ATTR: ['id'] preserves marked's heading anchor ids (RESEARCH Pitfall 1).
    if (typeof marked !== 'undefined') {
        const raw = marked.parse(text);
        if (typeof DOMPurify !== 'undefined') {
            return DOMPurify.sanitize(raw, { ADD_ATTR: ['id'] });
        }
        return raw;  // falls through only if DOMPurify failed to load
    }
    // Fallback: basic HTML escaping
    return text.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
}

// --- citation links ------------------------------------------------------------
//
// A citation becomes a link only when it resolves to a document that is in the
// project: a bracketed document name, or a bare token that is clearly a
// document id. Anything else in the model's reply is left exactly as written.
// Document ids, names and the reply are untrusted (SEC-01). Linking runs on the
// TEXT NODES of the already-sanitized message DOM, so entities, tags and
// attribute values can never be touched; anchors are built with createElement,
// setAttribute and textContent from known ids only. <pre>, <code> and existing
// anchors are skipped with everything inside them. Clicks are handled by one
// delegated listener on #messages (see initChat); the anchors carry no inline
// handlers.

const SAFE_DOC_ID = /^[a-z0-9_.-]+$/i;
let citationDocs = null; // null until setCitationDocuments is called with a list
let citationNames = new Map(); // doc_id -> display name
let citationSlugs = new Map(); // slug of an id, display name or filename -> doc_id
let bareIdPattern = null;

function slugify(value) {
    return String(value).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

function escapeRegex(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// A bare (unbracketed) token is linked only when it looks like a document id:
// at least 6 characters, and an underscore or both letters and digits. Plain
// words ("notes", "agenda") and short numbers still link through [Bracketed Name].
export function isBareCitableId(id) {
    if (typeof id !== 'string' || id.length < 6) return false;
    return id.includes('_') || (/[a-z]/i.test(id) && /\d/.test(id));
}

// Token characters are [A-Za-z0-9_]; "." and "-" join two tokens ("v1.2",
// "report-2"), so an id is never linked as part of a larger dotted or dashed token.
const TOKEN_BEFORE = '(?<![A-Za-z0-9_])(?<![A-Za-z0-9_][.\\-])';
const TOKEN_AFTER = '(?![A-Za-z0-9_])(?![.\\-][A-Za-z0-9_])';

// Rebuilds the lookup tables from the project's document list (rows carry
// doc_id, display_name, filename). Anything that is not a list is ignored.
export function setCitationDocuments(list) {
    if (!Array.isArray(list)) return;
    const names = new Map();
    const slugs = new Map();
    for (const row of list) {
        if (!row || typeof row.doc_id !== 'string' || !SAFE_DOC_ID.test(row.doc_id)) continue;
        const id = row.doc_id;
        names.set(id, (typeof row.display_name === 'string' && row.display_name) || (typeof row.filename === 'string' && row.filename) || id);
        for (const label of [id, row.display_name, row.filename]) {
            if (typeof label !== 'string') continue;
            const key = slugify(label);
            if (key && !slugs.has(key)) slugs.set(key, id);
        }
    }
    citationNames = names;
    citationSlugs = slugs;
    if (!names.size) {
        citationDocs = null;
        bareIdPattern = null;
        return;
    }
    citationDocs = names;
    const bareIds = Array.from(names.keys())
        .filter(isBareCitableId)
        .sort((a, b) => b.length - a.length || (a < b ? -1 : 1));
    bareIdPattern = bareIds.length
        ? new RegExp(`${TOKEN_BEFORE}(?:${bareIds.map(escapeRegex).join('|')})${TOKEN_AFTER}`, 'g')
        : null;
}

export function isKnownCitationDoc(docId) {
    return typeof docId === 'string' && citationNames.has(docId);
}

const BRACKETED = /\[([^[\]]+)\](?!\()/g;
const SKIPPED_ELEMENTS = new Set(['A', 'CODE', 'PRE', 'SCRIPT', 'STYLE', 'TEXTAREA']);

// Finds the citations in one plain-text string: [{start, end, docId}] in order.
// A resolved [Bracketed Name] wins over a bare id inside the same brackets.
function findCitations(text) {
    const found = [];
    for (const match of text.matchAll(BRACKETED)) {
        const docId = citationSlugs.get(slugify(match[1]));
        if (docId) found.push({ start: match.index, end: match.index + match[0].length, docId });
    }
    if (bareIdPattern) {
        const bracketed = found.slice();
        for (const m of text.matchAll(bareIdPattern)) {
            const start = m.index;
            const end = start + m[0].length;
            if (bracketed.some((b) => start < b.end && end > b.start)) continue;
            found.push({ start, end, docId: m[0] });
        }
    }
    return found.sort((x, y) => x.start - y.start);
}

function citationAnchor(doc, docId, shownText) {
    const a = doc.createElement('a');
    a.setAttribute('href', '#');
    a.setAttribute('class', 'citation-link');
    a.setAttribute('data-doc', docId);
    a.setAttribute('title', `Open ${citationNames.get(docId) || docId} in the source viewer`);
    a.textContent = shownText;
    return a;
}

function collectTextNodes(node, out) {
    for (const child of Array.from(node.childNodes || [])) {
        if (child.nodeType === 3) {
            out.push(child);
        } else if (child.nodeType === 1 && !SKIPPED_ELEMENTS.has(String(child.nodeName).toUpperCase())) {
            collectTextNodes(child, out);
        }
    }
    return out;
}

// Links resolved citations inside `root` (a sanitized message element) in place.
// Returns the number of links added.
export function linkifyCitations(root) {
    if (!citationDocs || !root || typeof root !== 'object' || !root.childNodes) return 0;
    const doc = root.ownerDocument || document;
    let added = 0;
    for (const textNode of collectTextNodes(root, [])) {
        const text = textNode.nodeValue || '';
        if (!text) continue;
        const found = findCitations(text);
        if (!found.length) continue;
        const parent = textNode.parentNode;
        let last = 0;
        for (const { start, end, docId } of found) {
            if (start > last) parent.insertBefore(doc.createTextNode(text.slice(last, start)), textNode);
            parent.insertBefore(citationAnchor(doc, docId, text.slice(start, end)), textNode);
            last = end;
            added += 1;
        }
        if (last < text.length) parent.insertBefore(doc.createTextNode(text.slice(last)), textNode);
        parent.removeChild(textNode);
    }
    return added;
}

// ---------------------------------------------------------------------------
// Model selector: fetches /api/models, renders an <optgroup>-structured
// <select> when the backend returns grouped data (OpenRouter live list),
// otherwise falls back to a flat list (Anthropic/Foundry). A sort toggle
// button flips between "by group" and "by cost" (cheapest first). Both the
// selected model (`epistract_model`) and the sort mode (`epistract_model_sort`)
// persist in localStorage.
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
    const groups = {};
    for (const m of models) {
        const g = m.group || 'Other';
        if (!groups[g]) groups[g] = [];
        groups[g].push(m);
    }
    for (const catName of CATEGORY_ORDER) {
        const bucket = groups[catName];
        if (!bucket || bucket.length === 0) continue;
        const og = document.createElement('optgroup');
        og.label = catName;
        for (const m of bucket) {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.label;
            og.appendChild(opt);
        }
        select.appendChild(og);
    }
    // Catch any group present in data but missing from CATEGORY_ORDER
    // (future-proofing — should not happen in practice).
    for (const [catName, bucket] of Object.entries(groups)) {
        if (CATEGORY_ORDER.includes(catName)) continue;
        const og = document.createElement('optgroup');
        og.label = catName;
        for (const m of bucket) {
            const opt = document.createElement('option');
            opt.value = m.id;
            opt.textContent = m.label;
            og.appendChild(opt);
        }
        select.appendChild(og);
    }
}

function buildCostSortedOptions(models, select) {
    const sorted = [...models].sort(
        (a, b) => (a.input_cost ?? 0) - (b.input_cost ?? 0)
    );
    for (const m of sorted) {
        const opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = m.label;
        select.appendChild(opt);
    }
}

export async function loadModelSelector() {
    const modelSelect = document.getElementById('model-select');
    const sortBtn = document.getElementById('model-sort-btn');
    if (!modelSelect) return;
    try {
        const resp = await fetch('/api/models');
        if (!resp.ok) {
            modelSelect.style.display = 'none';
            if (sortBtn) sortBtn.style.display = 'none';
            return;
        }
        const data = await resp.json();
        if (!data.models || data.models.length <= 1) {
            modelSelect.style.display = 'none';
            if (sortBtn) sortBtn.style.display = 'none';
            return;
        }
        const hasGroups = data.models.some(m => m.group);
        let sortByCost = hasGroups &&
            localStorage.getItem('epistract_model_sort') === 'cost';

        function rebuildOptions() {
            modelSelect.innerHTML = '';
            if (!sortByCost && hasGroups) {
                buildGroupedOptions(data.models, modelSelect);
                if (sortBtn) {
                    sortBtn.textContent = '$↑';
                    sortBtn.title = 'Sort by cost (cheapest first)';
                }
            } else {
                buildCostSortedOptions(data.models, modelSelect);
                if (sortBtn) {
                    sortBtn.textContent = '▤';
                    sortBtn.title = 'Group by provider';
                }
            }
            const saved = localStorage.getItem('epistract_model');
            if (saved && data.models.some(m => m.id === saved)) {
                modelSelect.value = saved;
            }
        }

        rebuildOptions();
        modelSelect.style.display = '';

        // Sort button is only meaningful when we have grouped data
        // (Anthropic/Foundry paths return no `group` field per Pitfall 6).
        if (hasGroups && sortBtn) {
            sortBtn.style.display = '';
            sortBtn.addEventListener('click', () => {
                sortByCost = !sortByCost;
                localStorage.setItem(
                    'epistract_model_sort',
                    sortByCost ? 'cost' : 'group',
                );
                rebuildOptions();
            });
        } else if (sortBtn) {
            sortBtn.style.display = 'none';
        }

        modelSelect.addEventListener('change', () => {
            localStorage.setItem('epistract_model', modelSelect.value);
        });
    } catch (_e) {
        modelSelect.style.display = 'none';
        if (sortBtn) sortBtn.style.display = 'none';
    }
}

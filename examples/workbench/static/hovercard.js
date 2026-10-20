// hovercard.js - DOM builder and positioning for the node hover card.
// Exports: initHoverCard, showHoverCard, hideHoverCard, isHoverCardVisible
// SEC-01: every string from graph data is placed with textContent or setAttribute;
// class names are static and the swatch comes from display.js.
import { makeSwatch } from './display.js';
import { cardPosition, statusSuffix } from './graph_style.js';

const CARD_ID = 'graph-hover-card';
const FALLBACK_SIZE = { w: 300, h: 200 };

let card = null;

function div(className, text) {
    const el = document.createElement('div');
    el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
}

function plural(n, word) {
    return `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;
}

export function initHoverCard() {
    if (card) return card;
    card = document.createElement('div');
    card.id = CARD_ID;
    card.className = 'graph-hover-card';
    card.setAttribute('role', 'tooltip');
    card.hidden = true;
    document.body.appendChild(card);
    return card;
}

function buildRow(rel) {
    const row = div('graph-hover-card__row', rel.sentence);
    row.setAttribute('title', rel.title || rel.sentence);
    if (rel.status) {
        const status = document.createElement('span');
        status.className = 'graph-hover-card__status';
        status.textContent = statusSuffix(rel.status);
        row.appendChild(status);
    }
    return row;
}

// model comes from hoverCardModel(); clientPoint is {x, y} in viewport pixels.
export function showHoverCard(model, entityType, clientPoint) {
    const el = initHoverCard();
    const header = div('graph-hover-card__header');
    header.append(makeSwatch(entityType, 16), div('graph-hover-card__type', model.typeLabel));

    const parts = [plural(model.linkCount, 'link'), plural(model.sourceCount, 'source')];
    if (model.family) parts.push(model.family);

    const children = [header, div('graph-hover-card__name', model.name)];
    if (model.description) children.push(div('graph-hover-card__desc', model.description));
    children.push(div('graph-hover-card__meta', parts.join(' · ')));
    children.push(div('graph-hover-card__divider'));
    if (model.noLinks) {
        children.push(div('graph-hover-card__row', 'No links besides sources.'));
    } else {
        for (const rel of model.relations) children.push(buildRow(rel));
    }
    if (model.more > 0) {
        children.push(div('graph-hover-card__more', `+${model.more} more · click for details`));
    }
    el.replaceChildren(...children);
    el.hidden = false;

    const size = {
        w: el.offsetWidth || FALLBACK_SIZE.w,
        h: el.offsetHeight || FALLBACK_SIZE.h,
    };
    const pos = cardPosition(clientPoint, size, { w: window.innerWidth, h: window.innerHeight });
    el.style.left = `${pos.left}px`;
    el.style.top = `${pos.top}px`;
}

export function hideHoverCard() {
    if (card) card.hidden = true;
}

export function isHoverCardVisible() {
    return Boolean(card) && card.hidden === false;
}

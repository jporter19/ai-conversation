// frontend/js/model_tooltip.js
// Hover / focus tooltip for the selected model in the main model dropdown.

function ensureTooltipEl() {
    let el = document.getElementById('model-tooltip');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'model-tooltip';
    el.className = 'model-tooltip';
    el.setAttribute('role', 'tooltip');
    el.hidden = true;
    document.body.appendChild(el);
    return el;
}

function selectedModelTip(select) {
    if (!select || select.selectedIndex < 0) return '';
    const opt = select.options[select.selectedIndex];
    if (!opt || !opt.value) return '';
    return (
        opt.dataset.tooltip
        || opt.dataset.description
        || opt.title
        || ''
    ).trim();
}

function positionTooltip(el, anchorEl, clientX, clientY) {
    const pad = 12;
    let left;
    let top;
    if (typeof clientX === 'number' && typeof clientY === 'number') {
        left = clientX + 14;
        top = clientY + 14;
    } else if (anchorEl) {
        const r = anchorEl.getBoundingClientRect();
        left = r.left;
        top = r.bottom + 6;
    } else {
        return;
    }
    el.hidden = false;
    el.style.opacity = '1';
    // Measure after visible
    const tw = el.offsetWidth || 280;
    const th = el.offsetHeight || 60;
    const maxL = window.innerWidth - tw - pad;
    const maxT = window.innerHeight - th - pad;
    el.style.left = `${Math.max(pad, Math.min(left, maxL))}px`;
    el.style.top = `${Math.max(pad, Math.min(top, maxT))}px`;
}

function showForSelect(select, clientX, clientY) {
    const el = ensureTooltipEl();
    const text = selectedModelTip(select);
    if (!text) {
        hideTooltip();
        return;
    }
    el.textContent = text;
    // Keep native title in sync for accessibility
    select.title = text;
    positionTooltip(el, select, clientX, clientY);
}

function hideTooltip() {
    const el = document.getElementById('model-tooltip');
    if (!el) return;
    el.style.opacity = '0';
    el.hidden = true;
}

/**
 * Attach hover/focus/change listeners so the selected model's description
 * appears when the user mouses over or focuses the model dropdown.
 */
export function initModelTooltips() {
    const modelSelect = document.getElementById('model-select');
    if (!modelSelect || modelSelect.dataset.tooltipBound) return;
    modelSelect.dataset.tooltipBound = '1';

    ensureTooltipEl();

    const onMove = (e) => {
        if (selectedModelTip(modelSelect)) {
            showForSelect(modelSelect, e.clientX, e.clientY);
        }
    };

    modelSelect.addEventListener('mouseenter', onMove);
    modelSelect.addEventListener('mousemove', onMove);
    modelSelect.addEventListener('mouseleave', () => hideTooltip());
    modelSelect.addEventListener('focus', () => showForSelect(modelSelect));
    modelSelect.addEventListener('blur', () => hideTooltip());
    modelSelect.addEventListener('change', () => {
        // Update title immediately; show tip near the control
        showForSelect(modelSelect);
        // Brief show after selection, then hide on next leave
        const tip = selectedModelTip(modelSelect);
        if (tip) modelSelect.title = tip;
    });

    // When catalog repopulates options, refresh title for current selection
    const obs = new MutationObserver(() => {
        const tip = selectedModelTip(modelSelect);
        modelSelect.title = tip || '';
    });
    obs.observe(modelSelect, { childList: true });
}

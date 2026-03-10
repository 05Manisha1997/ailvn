/**
 * templates.js — Handles loading, displaying, adding and editing Response Templates
 */

document.addEventListener('DOMContentLoaded', () => {
    // Wait for the tab to be clicked to load the templates
    const navTemplates = document.getElementById('nav-templates');
    if (navTemplates) {
        navTemplates.addEventListener('click', loadTemplates);
    }
});

async function loadTemplates() {
    const tbody = document.getElementById('templates-tbody');
    if (!tbody) return;

    tbody.innerHTML = '<tr><td colspan="3" class="text-center">Loading templates...</td></tr>';

    const data = await api.get('/templates');
    if (!data) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-center" style="color:var(--danger)">Failed to load templates.</td></tr>';
        return;
    }

    renderTemplates(data);
}

function renderTemplates(templatesDict) {
    const tbody = document.getElementById('templates-tbody');
    tbody.innerHTML = '';

    const keys = Object.keys(templatesDict).sort();
    if (keys.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-center">No templates found.</td></tr>';
        return;
    }

    for (const key of keys) {
        const value = templatesDict[key];
        const tr = document.createElement('tr');

        const tdKey = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = 'badge active';
        badge.textContent = key;
        tdKey.appendChild(badge);

        const tdValue = document.createElement('td');
        tdValue.textContent = value;
        tdValue.title = value; // For overflow tooltip

        const tdAction = document.createElement('td');
        const editBtn = document.createElement('button');
        editBtn.className = 'btn btn-ghost btn-sm';
        editBtn.textContent = 'Edit';
        editBtn.onclick = () => editTemplate(key, value);
        tdAction.appendChild(editBtn);

        tr.appendChild(tdKey);
        tr.appendChild(tdValue);
        tr.appendChild(tdAction);

        tbody.appendChild(tr);
    }
}

function editTemplate(key, value) {
    document.getElementById('template-intent-input').value = key;
    document.getElementById('template-value-input').value = value;

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });

    const inputArea = document.getElementById('template-value-input');
    inputArea.focus();
    inputArea.select();
}

async function saveTemplate() {
    const intentInput = document.getElementById('template-intent-input');
    const valueInput = document.getElementById('template-value-input');
    const btnText = document.getElementById('save-template-text');
    const btn = document.getElementById('btn-save-template');

    const intentKey = intentInput.value.trim();
    const templateVal = valueInput.value.trim();

    if (!intentKey || !templateVal) {
        showToast('Please provide both an Intent Key and a Template String', 'error');
        return;
    }

    // Set loading state
    btn.disabled = true;
    const originalText = btnText.textContent;
    btnText.textContent = 'Verifying & Saving...';

    const payload = {
        intent_key: intentKey,
        template: templateVal
    };

    try {
        const result = await api.post('/templates', payload);
        if (result && result.status === 'success') {
            showToast('Template verified and saved successfully!');
            // Reset form
            intentInput.value = '';
            valueInput.value = '';
            // Reload table
            await loadTemplates();
        } else {
            showToast('Failed to save template. Check server logs.', 'error');
        }
    } catch (e) {
        showToast('Error communicating with server.', 'error');
    } finally {
        btn.disabled = false;
        btnText.textContent = originalText;
    }
}

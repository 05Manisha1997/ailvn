/**
 * policies.js — Handles policy document indexing and display
 */

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file) {
        updateUploadZone(file.name);
    }
}

function handleDrop(event) {
    event.preventDefault();
    const file = event.dataTransfer.files[0];
    if (file && file.type === 'application/pdf') {
        const input = document.getElementById('policy-file');
        input.files = event.dataTransfer.files;
        updateUploadZone(file.name);
    } else {
        showToast('Please upload a PDF file.', 'error');
    }
}

function updateUploadZone(fileName) {
    const zone = document.getElementById('upload-zone');
    zone.innerHTML = `
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <path d="M9 15l3 3 3-3" />
            <path d="M12 18V11" />
        </svg>
        <p style="color:var(--accent); font-weight:600">${fileName}</p>
        <button class="btn btn-link btn-sm" onclick="resetUploadZone()">Change File</button>
    `;
}

function resetUploadZone() {
    const zone = document.getElementById('upload-zone');
    zone.innerHTML = `
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
        <p>Drag & drop a PDF here</p>
        <span>or</span>
        <input type="file" id="policy-file" accept=".pdf" style="display:none" onchange="handleFileSelect(event)" />
        <button class="btn btn-ghost" onclick="document.getElementById('policy-file').click()">Browse File</button>
    `;
    document.getElementById('pol-id-input').value = '';
}

async function indexPolicy() {
    const fileInput = document.getElementById('policy-file');
    const idInput = document.getElementById('pol-id-input');
    const policyId = idInput.value.trim();

    if (!fileInput.files || fileInput.files.length === 0) {
        showToast('Please select a PDF file first.', 'error');
        return;
    }
    if (!policyId) {
        showToast('Please enter a Policy ID.', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('policy_id', policyId);

    // Show loading state
    const btn = event.currentTarget;
    const originalContent = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<div class="spinner"></div> Indexing...';

    try {
        const response = await fetch(`${API_BASE}/index-policy`, {
            method: 'POST',
            body: formData,
        });

        const result = await response.json();

        if (response.ok && result.status === 'success') {
            showToast(result.message || 'Policy indexed successfully!');
            resetUploadZone();
        } else {
            showToast(result.detail || 'Failed to index policy.', 'error');
        }
    } catch (error) {
        console.error('Indexing error:', error);
        showToast('Error communicating with server.', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalContent;
    }
}

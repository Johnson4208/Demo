const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
const statusBox = document.getElementById('adminStatus');

function showStatus(message, good = false) {
  statusBox.textContent = message;
  statusBox.className = `admin-alert ${good ? 'good' : 'bad'}`;
  statusBox.hidden = false;
  statusBox.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

async function api(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('X-CSRF-Token', csrf);
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(url, {...options, headers, credentials: 'same-origin'});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}

document.getElementById('createUserForm')?.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const values = Object.fromEntries(new FormData(form).entries());
    await api('/api/admin/users', {method: 'POST', body: JSON.stringify(values)});
    showStatus('Account created securely. Refreshing the directory…', true);
    setTimeout(() => location.reload(), 550);
  } catch (error) {
    showStatus(error.message);
    button.disabled = false;
  }
});

document.querySelectorAll('[data-access-request-id]').forEach(card => {
  const requestId = card.dataset.accessRequestId;
  card.querySelectorAll('[data-request-action]').forEach(button => button.addEventListener('click', async () => {
    const action = button.dataset.requestAction;
    const role = card.querySelector('.request-role select')?.value || 'viewer';
    const decisionNote = card.querySelector('.request-decision-note input')?.value.trim() || '';
    const label = card.querySelector('.request-identity b')?.textContent?.trim() || 'this person';
    const prompt = action === 'approve'
      ? `Approve ${label} as ${role}? They will be able to sign in immediately.`
      : `Reject the access request from ${label}?`;
    if (!confirm(prompt)) return;
    const buttons = [...card.querySelectorAll('[data-request-action]')];
    buttons.forEach(item => { item.disabled = true; });
    try {
      await api(`/api/admin/access-requests/${requestId}/action`, {
        method: 'POST',
        body: JSON.stringify({action, role, decision_note: decisionNote})
      });
      showStatus(
        action === 'approve'
          ? 'Access approved. The account can now sign in.'
          : 'Access request rejected and its temporary credential hash removed.',
        true
      );
      setTimeout(() => location.reload(), 550);
    } catch (error) {
      showStatus(error.message);
      buttons.forEach(item => { item.disabled = false; });
    }
  }));
});

document.querySelectorAll('tr[data-user-id]').forEach(row => {
  const userId = row.dataset.userId;
  row.querySelector('.role-select')?.addEventListener('change', async event => {
    event.target.disabled = true;
    try {
      await api(`/api/admin/users/${userId}/action`, {method: 'POST', body: JSON.stringify({action: 'set_role', role: event.target.value})});
      showStatus('Role updated. Existing sessions now use the new permission level.', true);
      setTimeout(() => location.reload(), 450);
    } catch (error) {
      showStatus(error.message);
      event.target.disabled = false;
    }
  });
  row.querySelectorAll('button[data-action]').forEach(button => button.addEventListener('click', async () => {
    const action = button.dataset.action;
    const destructive = ['deactivate', 'delete', 'require_password_reset', 'revoke_sessions'].includes(action);
    if (destructive && !confirm(`Confirm: ${button.textContent.trim()} this account?`)) return;
    button.disabled = true;
    try {
      if (action === 'delete') await api(`/api/admin/users/${userId}`, {method: 'DELETE'});
      else await api(`/api/admin/users/${userId}/action`, {method: 'POST', body: JSON.stringify({action})});
      showStatus('Account security change saved.', true);
      setTimeout(() => location.reload(), 450);
    } catch (error) {
      showStatus(error.message);
      button.disabled = false;
    }
  }));
});

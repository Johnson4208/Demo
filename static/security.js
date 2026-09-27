const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
const statusBox = document.getElementById('securityStatus');

function status(message, good = false) {
  statusBox.textContent = message;
  statusBox.className = `security-notice ${good ? 'good' : 'error'}`;
  statusBox.hidden = false;
}

async function requestJSON(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('X-CSRF-Token', csrf);
  if (options.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(url, {...options, headers, credentials: 'same-origin'});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}

document.getElementById('passwordForm')?.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  if (values.new_password !== values.confirm_password) {
    status('The new passwords do not match.');
    return;
  }
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const result = await requestJSON('/api/auth/password', {method: 'POST', body: JSON.stringify(values)});
    form.reset();
    status(result.message || 'Password updated.', true);
    setTimeout(() => location.reload(), 800);
  } catch (error) {
    status(error.message);
    button.disabled = false;
  }
});

document.querySelectorAll('[data-revoke-session]').forEach(button => button.addEventListener('click', async () => {
  const row = button.closest('[data-session-id]');
  if (!confirm('Sign out this device?')) return;
  button.disabled = true;
  try {
    await requestJSON(`/api/auth/sessions/${row.dataset.sessionId}`, {method: 'DELETE'});
    row.remove();
    status('The selected device was signed out.', true);
  } catch (error) {
    status(error.message);
    button.disabled = false;
  }
}));

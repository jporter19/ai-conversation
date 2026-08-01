// frontend/js/login.js — shared hub account login

(function () {
    const form = document.getElementById('login-form');
    const errEl = document.getElementById('login-error');
    const btn = document.getElementById('login-btn');

    async function alreadyIn() {
        try {
            const res = await fetch('/api/v1/auth/me', { credentials: 'same-origin' });
            if (!res.ok) return;
            const data = await res.json();
            if (data.authenticated) {
                window.location.replace('/');
            }
        } catch (_) { /* stay on login */ }
    }

    alreadyIn();

    form?.addEventListener('submit', async (e) => {
        e.preventDefault();
        errEl.textContent = '';
        const username = document.getElementById('username')?.value?.trim() || '';
        const password = document.getElementById('password')?.value || '';
        if (!username || !password) {
            errEl.textContent = 'Enter username and password.';
            return;
        }
        btn.disabled = true;
        try {
            const res = await fetch('/api/v1/auth/login', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                errEl.textContent = data.detail || 'Sign-in failed.';
                return;
            }
            window.location.replace('/');
        } catch (err) {
            errEl.textContent = 'Network error — try again.';
        } finally {
            btn.disabled = false;
        }
    });
})();

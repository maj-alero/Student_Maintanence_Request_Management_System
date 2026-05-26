/* smrms.js */

// ── THEME ──────────────────────────────────────────
const _html  = document.documentElement;
const _saved = localStorage.getItem('smrms-theme') || 'light';
_html.setAttribute('data-theme', _saved);
_syncThemeIcon(_saved);

function toggleTheme() {
    const next = _html.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    _html.setAttribute('data-theme', next);
    localStorage.setItem('smrms-theme', next);
    _syncThemeIcon(next);
}

function _syncThemeIcon(theme) {
    const icon = document.getElementById('themeIcon');
    if (icon) icon.className = theme === 'light' ? 'ti ti-moon' : 'ti ti-sun';
}

// ── SIDEBAR (mobile) ───────────────────────────────
function openSb() {
    document.getElementById('sidebar')?.classList.add('open');
    document.getElementById('sbOverlay')?.classList.add('open');
}
function closeSb() {
    document.getElementById('sidebar')?.classList.remove('open');
    document.getElementById('sbOverlay')?.classList.remove('open');
}

// ── ROLE TAB SWITCHER (register page) ─────────────
function switchRole(role) {
    document.querySelectorAll('.role-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.role-tab[data-role="${role}"]`)?.classList.add('active');
    const input = document.getElementById('role_type_input');
    if (input) input.value = role;
}

// ── AUTO-DISMISS ALERTS ────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.alert[data-autohide]').forEach(el => {
        setTimeout(() => {
            el.style.transition = 'opacity 0.4s ease';
            el.style.opacity = '0';
            setTimeout(() => el.remove(), 400);
        }, 4000);
    });
});

/**
 * Supabase Authentication & User Data Management (Browser Client + RLS)
 *
 * Uses ONLY the public Supabase URL and anon/publishable key.
 * Row Level Security (RLS) in PostgreSQL ensures users can only read/write
 * their own rows via auth.uid(). Never supplies or trusts client-side user_id.
 */
'use strict';

window.TithiAuth = (function () {
  let client = null;
  let currentSession = null;
  let currentUser = null;
  let authModalMode = 'login';
  let initialized = false;
  let deepLinkHandled = false;

  function esc(val) {
    return typeof window.escapeHtml === 'function' ? window.escapeHtml(val) : String(val ?? '');
  }

  function toastError(msg) {
    if (typeof window.showError === 'function') {
      window.showError(msg);
    } else {
      alert(msg);
    }
  }

  function toastSuccess(msg) {
    const alertEl = document.createElement('div');
    alertEl.className = 'alert alert-success alert-dismissible fade show position-fixed bottom-0 end-0 m-3 shadow';
    alertEl.style.zIndex = '10000';
    alertEl.innerHTML = `<i class="fas fa-check-circle me-2"></i><span>${esc(msg)}</span>
      <button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
    document.body.appendChild(alertEl);
    setTimeout(() => alertEl.remove(), 5000);
  }

  function isConfigured() {
    const cfg = window.SUPABASE_CONFIG || {};
    return Boolean(cfg.configured && cfg.url && cfg.anonKey && window.supabase && window.supabase.createClient);
  }

  function getClient() {
    if (client) return client;
    if (!isConfigured()) return null;
    const cfg = window.SUPABASE_CONFIG;
    client = window.supabase.createClient(cfg.url, cfg.anonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    });
    return client;
  }

  function showInlineAlert(elId, message, type) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (!message) {
      el.className = 'alert d-none';
      el.textContent = '';
      return;
    }
    el.className = `alert alert-${type}`;
    el.textContent = message;
  }

  function setButtonLoading(btn, loading, defaultHtml) {
    if (!btn) return;
    if (loading) {
      btn.dataset.origHtml = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Please wait…';
    } else {
      btn.disabled = false;
      btn.innerHTML = defaultHtml || btn.dataset.origHtml || btn.innerHTML;
    }
  }

  // ══════════════════════════════════════════════════════
  // Navbar & Auth Modal
  // ══════════════════════════════════════════════════════
  function updateAuthUI() {
    const loadingEl = document.getElementById('nav-auth-loading');
    const guestEl = document.getElementById('nav-auth-guest');
    const userEl = document.getElementById('nav-auth-user');
    const emailEl = document.getElementById('nav-user-email');

    if (loadingEl) loadingEl.style.display = 'none';

    if (currentUser) {
      if (guestEl) guestEl.style.setProperty('display', 'none', 'important');
      if (userEl) userEl.style.display = '';
      if (emailEl) emailEl.textContent = currentUser.email || 'My Account';
    } else {
      if (userEl) userEl.style.display = 'none';
      if (guestEl) guestEl.style.setProperty('display', 'flex', 'important');
    }

    // Re-render calculator results save bar if a result is currently displayed
    if (window.TithiCalculator && typeof window.TithiCalculator.refreshCloudSaveBar === 'function') {
      window.TithiCalculator.refreshCloudSaveBar();
    }

    // Update /account page if we are on it
    if (document.getElementById('account-dashboard')) {
      renderAccountPageState();
    }
  }

  function openAuthModal(mode) {
    if (!isConfigured()) {
      toastError('Supabase authentication is not configured yet. Please add SUPABASE_URL and SUPABASE_ANON_KEY to your .env file.');
      return;
    }
    switchAuthTab(mode || 'login');
    showInlineAlert('authModalAlert', '');
    const modalEl = document.getElementById('authModal');
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  }

  function switchAuthTab(mode) {
    authModalMode = mode === 'signup' ? 'signup' : 'login';
    const loginTab = document.getElementById('auth-tab-login');
    const signupTab = document.getElementById('auth-tab-signup');
    const loginForm = document.getElementById('loginForm');
    const signupForm = document.getElementById('signupForm');

    showInlineAlert('authModalAlert', '');
    if (authModalMode === 'signup') {
      loginTab?.classList.remove('active');
      signupTab?.classList.add('active');
      loginForm?.classList.add('d-none');
      signupForm?.classList.remove('d-none');
    } else {
      signupTab?.classList.remove('active');
      loginTab?.classList.add('active');
      signupForm?.classList.add('d-none');
      loginForm?.classList.remove('d-none');
    }
  }

  async function handleLoginSubmit(e) {
    e.preventDefault();
    const sb = getClient();
    if (!sb) {
      showInlineAlert('authModalAlert', 'Supabase is not configured on the server.', 'danger');
      return;
    }

    const email = (document.getElementById('loginEmail')?.value || '').trim();
    const password = document.getElementById('loginPassword')?.value || '';
    if (!email || !password) {
      showInlineAlert('authModalAlert', 'Please enter both email and password.', 'danger');
      return;
    }

    const btn = document.getElementById('btnLoginSubmit');
    setButtonLoading(btn, true);
    showInlineAlert('authModalAlert', '');

    try {
      const { data, error } = await sb.auth.signInWithPassword({ email, password });
      if (error) {
        const msg = /email not confirmed/i.test(error.message)
          ? 'Please confirm your email address using the link sent to your inbox before logging in.'
          : error.message;
        showInlineAlert('authModalAlert', msg, 'danger');
        return;
      }
      currentSession = data.session;
      currentUser = data.user;
      updateAuthUI();
      const modalEl = document.getElementById('authModal');
      if (modalEl && window.bootstrap) {
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      }
      document.getElementById('loginForm')?.reset();
      toastSuccess(`Welcome back, ${currentUser.email}!`);
    } catch (err) {
      showInlineAlert('authModalAlert', 'Network error while signing in. Please try again.', 'danger');
    } finally {
      setButtonLoading(btn, false);
    }
  }

  async function handleSignupSubmit(e) {
    e.preventDefault();
    const sb = getClient();
    if (!sb) {
      showInlineAlert('authModalAlert', 'Supabase is not configured on the server.', 'danger');
      return;
    }

    const email = (document.getElementById('signupEmail')?.value || '').trim();
    const password = document.getElementById('signupPassword')?.value || '';
    const confirm = document.getElementById('signupPasswordConfirm')?.value || '';

    if (!email || !email.includes('@')) {
      showInlineAlert('authModalAlert', 'Please enter a valid email address.', 'danger');
      return;
    }
    if (password.length < 6) {
      showInlineAlert('authModalAlert', 'Password must be at least 6 characters long.', 'danger');
      return;
    }
    if (password !== confirm) {
      showInlineAlert('authModalAlert', 'Passwords do not match.', 'danger');
      return;
    }

    const btn = document.getElementById('btnSignupSubmit');
    setButtonLoading(btn, true);
    showInlineAlert('authModalAlert', '');

    try {
      const { data, error } = await sb.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: window.location.origin + '/account' },
      });
      if (error) {
        showInlineAlert('authModalAlert', error.message, 'danger');
        return;
      }

      // Supabase returns empty identities if user already exists when email confirmation is on
      if (data.user && Array.isArray(data.user.identities) && data.user.identities.length === 0) {
        showInlineAlert('authModalAlert', 'An account with this email already exists. Please log in instead.', 'warning');
        return;
      }

      if (data.session) {
        currentSession = data.session;
        currentUser = data.user;
        updateAuthUI();
        const modalEl = document.getElementById('authModal');
        if (modalEl && window.bootstrap) {
          bootstrap.Modal.getOrCreateInstance(modalEl).hide();
        }
        document.getElementById('signupForm')?.reset();
        toastSuccess('Account created and signed in!');
      } else {
        document.getElementById('signupForm')?.reset();
        showInlineAlert(
          'authModalAlert',
          'Account created! Please check your email inbox and click the confirmation link before logging in.',
          'info'
        );
      }
    } catch (err) {
      showInlineAlert('authModalAlert', 'Network error while creating account. Please try again.', 'danger');
    } finally {
      setButtonLoading(btn, false);
    }
  }

  async function logout() {
    const sb = getClient();
    if (!sb) return;
    try {
      const { error } = await sb.auth.signOut();
      if (error) {
        toastError('Error signing out: ' + error.message);
        return;
      }
      currentSession = null;
      currentUser = null;
      if (window.TithiCalculator && typeof window.TithiCalculator.setActiveSavedProfileId === 'function') {
        window.TithiCalculator.setActiveSavedProfileId(null);
      }
      updateAuthUI();
      toastSuccess('You have been logged out.');
    } catch (err) {
      toastError('Network error while logging out.');
    }
  }

  async function ensureValidSession() {
    const sb = getClient();
    if (!sb) return null;
    const { data, error } = await sb.auth.getSession();
    if (error || !data || !data.session) {
      currentSession = null;
      currentUser = null;
      updateAuthUI();
      return null;
    }
    currentSession = data.session;
    currentUser = data.session.user;
    return data.session;
  }

  // ══════════════════════════════════════════════════════
  // Explicit Save Actions on Calculator Page
  // ══════════════════════════════════════════════════════
  function openSaveProfileModal() {
    if (!currentUser) {
      openAuthModal('login');
      return;
    }
    if (!window.TithiCalculator || !window.TithiCalculator.getLastCalculation()) {
      toastError('Please run a calculation first before saving a birth profile.');
      return;
    }
    showInlineAlert('saveProfileAlert', '');
    const labelInput = document.getElementById('profileLabelInput');
    if (labelInput) labelInput.value = '';
    const modalEl = document.getElementById('saveProfileModal');
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  }

  function buildProfileRowFromPayload(label, p) {
    return {
      label: label.trim(),
      birth_date: p.birth_date,
      birth_time_mode: p.birth_time_mode || 'unknown',
      birth_time: p.birth_time_mode === 'exact' ? (p.birth_time || null) : null,
      birth_time_start: p.birth_time_mode === 'approximate' ? (p.birth_time_start || null) : null,
      birth_time_end: p.birth_time_mode === 'approximate' ? (p.birth_time_end || null) : null,
      location_name: p.location_name || `${p.lat}, ${p.lon}`,
      latitude: Number(p.lat),
      longitude: Number(p.lon),
      timezone: p.timezone || 'UTC',
      ayanamsha: p.ayanamsha || 'lahiri',
      lunar_system: p.lunar_system || 'amanta',
      observance_method: p.observance_method || 'sunrise',
      adhika_rule: p.adhika_rule || 'nija',
      start_year: p.start_year ? Number(p.start_year) : null,
      end_year: p.end_year ? Number(p.end_year) : null,
    };
  }

  function stripInternalKeys(calcResult) {
    const clone = { ...calcResult };
    delete clone._payload;
    return clone;
  }

  async function handleSaveProfileSubmit(e) {
    e.preventDefault();
    const sb = getClient();
    const session = await ensureValidSession();
    if (!sb || !session) {
      showInlineAlert('saveProfileAlert', 'Your session expired. Please log in again.', 'warning');
      return;
    }

    const label = (document.getElementById('profileLabelInput')?.value || '').trim();
    if (!label || label.length > 80) {
      showInlineAlert('saveProfileAlert', 'Please enter a profile label (1–80 characters).', 'danger');
      return;
    }

    const lastCalc = window.TithiCalculator && window.TithiCalculator.getLastCalculation();
    if (!lastCalc || !lastCalc._payload) {
      showInlineAlert('saveProfileAlert', 'No active calculation found.', 'danger');
      return;
    }

    const alsoSaveHistory = Boolean(document.getElementById('alsoSaveHistoryCheck')?.checked);
    const btn = document.getElementById('btnSaveProfileConfirm');
    setButtonLoading(btn, true);
    showInlineAlert('saveProfileAlert', '');

    try {
      const profileRow = buildProfileRowFromPayload(label, lastCalc._payload);
      const { data: insertedProfile, error: profErr } = await sb
        .from('saved_birth_profiles')
        .insert(profileRow)
        .select('id, label')
        .single();

      if (profErr) {
        showInlineAlert('saveProfileAlert', 'Failed to save birth profile: ' + profErr.message, 'danger');
        return;
      }

      if (window.TithiCalculator && typeof window.TithiCalculator.setActiveSavedProfileId === 'function') {
        window.TithiCalculator.setActiveSavedProfileId(insertedProfile.id);
      }

      if (alsoSaveHistory) {
        const { error: histErr } = await sb.from('calculation_history').insert({
          saved_birth_profile_id: insertedProfile.id,
          input_data: lastCalc._payload,
          calculation_result: stripInternalKeys(lastCalc),
        });
        if (histErr) {
          toastError('Profile saved, but saving calculation history failed: ' + histErr.message);
        }
      }

      const modalEl = document.getElementById('saveProfileModal');
      if (modalEl && window.bootstrap) {
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      }
      toastSuccess(`Saved birth profile "${insertedProfile.label}".`);
    } catch (err) {
      showInlineAlert('saveProfileAlert', 'Unexpected error saving birth profile.', 'danger');
    } finally {
      setButtonLoading(btn, false);
    }
  }

  async function saveCalculationHistory() {
    const sb = getClient();
    const session = await ensureValidSession();
    if (!sb || !session) {
      openAuthModal('login');
      return;
    }
    const lastCalc = window.TithiCalculator && window.TithiCalculator.getLastCalculation();
    if (!lastCalc || !lastCalc._payload) {
      toastError('Please run a calculation first.');
      return;
    }

    const btn = document.getElementById('btn-save-history');
    setButtonLoading(btn, true);

    try {
      const profileId = window.TithiCalculator.getActiveSavedProfileId
        ? window.TithiCalculator.getActiveSavedProfileId()
        : null;

      const { error } = await sb.from('calculation_history').insert({
        saved_birth_profile_id: profileId || null,
        input_data: lastCalc._payload,
        calculation_result: stripInternalKeys(lastCalc),
      });
      if (error) {
        toastError('Failed to save calculation history: ' + error.message);
        setButtonLoading(btn, false);
        return;
      }
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-check me-1"></i>Saved to History';
      }
      toastSuccess('Calculation saved to your Calculation History.');
    } catch (err) {
      toastError('Network error saving calculation history.');
      setButtonLoading(btn, false);
    }
  }

  // ══════════════════════════════════════════════════════
  // My Account Dashboard (/account)
  // ══════════════════════════════════════════════════════
  function renderAccountPageState() {
    const loading = document.getElementById('account-loading');
    const unconf = document.getElementById('account-unconfigured');
    const guest = document.getElementById('account-guest');
    const dash = document.getElementById('account-dashboard');
    if (!loading || !dash) return;

    loading.style.display = 'none';
    if (!isConfigured()) {
      unconf.style.display = '';
      guest.style.display = 'none';
      dash.style.display = 'none';
      return;
    }
    unconf.style.display = 'none';

    if (!currentUser) {
      guest.style.display = '';
      dash.style.display = 'none';
      return;
    }

    guest.style.display = 'none';
    dash.style.display = '';

    const emailEl = document.getElementById('account-email');
    const createdEl = document.getElementById('account-created');
    if (emailEl) emailEl.textContent = currentUser.email || '—';
    if (createdEl) {
      createdEl.textContent = currentUser.created_at
        ? new Date(currentUser.created_at).toLocaleDateString()
        : '—';
    }

    loadAccountDashboard();
  }

  async function loadAccountDashboard() {
    const sb = getClient();
    const session = await ensureValidSession();
    if (!sb || !session) return;

    const profilesContainer = document.getElementById('saved-profiles-list');
    const historyContainer = document.getElementById('calculation-history-list');
    const countsEl = document.getElementById('account-counts');

    if (profilesContainer) {
      profilesContainer.innerHTML = '<div class="text-muted small"><i class="fas fa-spinner fa-spin me-2"></i>Loading saved profiles…</div>';
    }
    if (historyContainer) {
      historyContainer.innerHTML = '<div class="text-muted small"><i class="fas fa-spinner fa-spin me-2"></i>Loading calculation history…</div>';
    }

    try {
      const [profResp, histResp] = await Promise.all([
        sb
          .from('saved_birth_profiles')
          .select('*')
          .order('updated_at', { ascending: false }),
        sb
          .from('calculation_history')
          .select('id, saved_birth_profile_id, input_data, calculation_result, created_at')
          .order('created_at', { ascending: false }),
      ]);

      if (profResp.error) {
        if (profilesContainer) {
          profilesContainer.innerHTML = `<div class="alert alert-danger mb-0">${esc(profResp.error.message)}</div>`;
        }
      } else {
        renderSavedProfilesList(profResp.data || []);
      }

      if (histResp.error) {
        if (historyContainer) {
          historyContainer.innerHTML = `<div class="alert alert-danger mb-0">${esc(histResp.error.message)}</div>`;
        }
      } else {
        const profileMap = {};
        (profResp.data || []).forEach(p => { profileMap[p.id] = p.label; });
        renderCalculationHistoryList(histResp.data || [], profileMap);
      }

      if (countsEl) {
        const pCount = profResp.data ? profResp.data.length : 0;
        const hCount = histResp.data ? histResp.data.length : 0;
        countsEl.textContent = `${pCount} / ${hCount}`;
      }
    } catch (err) {
      toastError('Failed to load account data. Please refresh.');
    }
  }

  function renderSavedProfilesList(profiles) {
    const container = document.getElementById('saved-profiles-list');
    if (!container) return;

    if (!profiles.length) {
      container.innerHTML = `
        <div class="text-center py-4 text-muted">
          <p class="mb-2">You have not saved any birth profiles yet.</p>
          <a href="/#calculator" class="btn btn-sm btn-saffron">Calculate &amp; Save First Profile</a>
        </div>`;
      return;
    }

    let html = '<div class="row g-3">';
    profiles.forEach(p => {
      const timeDesc = p.birth_time_mode === 'exact'
        ? (p.birth_time || '').slice(0, 5)
        : (p.birth_time_mode === 'approximate'
            ? `${(p.birth_time_start || '').slice(0, 5)}–${(p.birth_time_end || '').slice(0, 5)}`
            : 'Unknown');
      html += `
        <div class="col-md-6">
          <div class="saved-item-card p-3 rounded border h-100 d-flex flex-column justify-content-between">
            <div>
              <div class="d-flex justify-content-between align-items-start gap-2 mb-2">
                <h5 class="mb-0 fw-bold text-navy">${esc(p.label)}</h5>
                <span class="badge bg-light text-dark border">${esc(p.lunar_system)}</span>
              </div>
              <div class="small text-muted mb-1">
                <i class="fas fa-calendar me-1 text-saffron"></i>${esc(p.birth_date)} ·
                <i class="fas fa-clock ms-1 me-1 text-saffron"></i>${esc(timeDesc)} (${esc(p.birth_time_mode)})
              </div>
              <div class="small text-muted mb-2">
                <i class="fas fa-map-marker-alt me-1 text-saffron"></i>${esc(p.location_name)}
              </div>
            </div>
            <div class="d-flex flex-wrap gap-2 mt-2 pt-2 border-top">
              <a href="/?profile_id=${encodeURIComponent(p.id)}#calculator" class="btn btn-sm btn-saffron">
                <i class="fas fa-play me-1"></i>Load &amp; Calculate
              </a>
              <button type="button" class="btn btn-sm btn-outline-secondary btn-edit-profile"
                      data-profile-id="${esc(p.id)}" data-profile-label="${esc(p.label)}">
                <i class="fas fa-edit me-1"></i>Edit Label
              </button>
              <button type="button" class="btn btn-sm btn-outline-danger ms-auto btn-delete-profile"
                      data-profile-id="${esc(p.id)}">
                <i class="fas fa-trash-alt"></i>
              </button>
            </div>
          </div>
        </div>`;
    });
    html += '</div>';
    container.innerHTML = html;
  }

  function renderCalculationHistoryList(rows, profileMap) {
    const container = document.getElementById('calculation-history-list');
    if (!container) return;

    if (!rows.length) {
      container.innerHTML = `
        <div class="text-center py-4 text-muted">
          <p class="mb-0">No saved calculations yet. After calculating on the home page, click <strong>Save to Calculation History</strong> to keep a record here.</p>
        </div>`;
      return;
    }

    let html = `
      <div class="table-responsive">
        <table class="table table-hover align-middle mb-0 small">
          <thead class="table-light">
            <tr>
              <th>Saved On</th>
              <th>Birth Date &amp; Place</th>
              <th>Calculated Panchang</th>
              <th>Profile</th>
              <th class="text-end">Actions</th>
            </tr>
          </thead>
          <tbody>`;

    rows.forEach(row => {
      const inp = row.input_data || {};
      const res = row.calculation_result || {};
      const p = res.panchang || {};
      const firstTithi = Array.isArray(p.tithis) && p.tithis.length ? p.tithis[0] : null;
      const tithiSummary = firstTithi
        ? `${firstTithi.paksha_en} ${firstTithi.name_en}${p.tithis.length > 1 ? ' (+more)' : ''}`
        : '—';
      const monthName = p.lunar_month ? p.lunar_month.name_en : '';
      const profLabel = row.saved_birth_profile_id ? (profileMap[row.saved_birth_profile_id] || 'Linked Profile') : '—';
      const createdDisp = row.created_at ? new Date(row.created_at).toLocaleString() : '—';

      html += `
        <tr>
          <td class="text-nowrap">${esc(createdDisp)}</td>
          <td>
            <strong>${esc(inp.birth_date || p.birth_date || '—')}</strong><br/>
            <span class="text-muted">${esc(inp.location_name || p.location_name || '—')}</span>
          </td>
          <td>
            <span class="fw-semibold">${esc(monthName)} ${esc(tithiSummary)}</span><br/>
            <span class="text-muted">${esc(res.start_year || '')}–${esc(res.end_year || '')}</span>
          </td>
          <td>${profLabel !== '—' ? `<span class="badge bg-light text-dark border">${esc(profLabel)}</span>` : '—'}</td>
          <td class="text-end text-nowrap">
            <a href="/?history_id=${encodeURIComponent(row.id)}#results-section" class="btn btn-sm btn-outline-primary me-1">
              <i class="fas fa-eye me-1"></i>Revisit
            </a>
            <a href="/?history_id=${encodeURIComponent(row.id)}&recalc=1#calculator" class="btn btn-sm btn-outline-secondary me-1" title="Recalculate live">
              <i class="fas fa-redo"></i>
            </a>
            <button type="button" class="btn btn-sm btn-outline-danger btn-delete-history"
                    data-history-id="${esc(row.id)}" title="Delete entry">
              <i class="fas fa-trash-alt"></i>
            </button>
          </td>
        </tr>`;
    });

    html += '</tbody></table></div>';
    container.innerHTML = html;
  }

  function openRenameModal(profileId, currentLabel) {
    document.getElementById('renameProfileId').value = profileId;
    document.getElementById('renameProfileLabelInput').value = currentLabel;
    showInlineAlert('renameProfileAlert', '');
    const modalEl = document.getElementById('renameProfileModal');
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  }

  async function handleRenameProfileSubmit(e) {
    e.preventDefault();
    const sb = getClient();
    const session = await ensureValidSession();
    if (!sb || !session) return;

    const id = document.getElementById('renameProfileId').value;
    const newLabel = (document.getElementById('renameProfileLabelInput').value || '').trim();
    if (!newLabel || newLabel.length > 80) {
      showInlineAlert('renameProfileAlert', 'Label must be 1–80 characters.', 'danger');
      return;
    }

    const btn = document.getElementById('btnRenameProfileSubmit');
    setButtonLoading(btn, true);

    try {
      const { error } = await sb
        .from('saved_birth_profiles')
        .update({ label: newLabel })
        .eq('id', id);

      if (error) {
        showInlineAlert('renameProfileAlert', error.message, 'danger');
        return;
      }
      const modalEl = document.getElementById('renameProfileModal');
      if (modalEl && window.bootstrap) {
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      }
      toastSuccess('Profile label updated.');
      loadAccountDashboard();
    } finally {
      setButtonLoading(btn, false);
    }
  }

  async function deleteProfile(id) {
    if (!confirm('Delete this saved birth profile? Any calculation history linked to it will be kept without the profile link.')) {
      return;
    }
    const sb = getClient();
    const session = await ensureValidSession();
    if (!sb || !session) return;

    const { error } = await sb.from('saved_birth_profiles').delete().eq('id', id);
    if (error) {
      toastError('Failed to delete profile: ' + error.message);
      return;
    }
    toastSuccess('Birth profile deleted.');
    loadAccountDashboard();
  }

  async function deleteHistory(id) {
    if (!confirm('Delete this saved calculation from your history?')) return;
    const sb = getClient();
    const session = await ensureValidSession();
    if (!sb || !session) return;

    const { error } = await sb.from('calculation_history').delete().eq('id', id);
    if (error) {
      toastError('Failed to delete calculation history: ' + error.message);
      return;
    }
    toastSuccess('Calculation history entry deleted.');
    loadAccountDashboard();
  }

  async function confirmDeleteAccount() {
    const confirmInput = document.getElementById('deleteConfirmInput');
    if (!confirmInput || confirmInput.value.trim().toUpperCase() !== 'DELETE') {
      showInlineAlert('deleteAccountAlert', 'Please type DELETE to confirm.', 'danger');
      return;
    }

    const session = await ensureValidSession();
    if (!session || !session.access_token) {
      showInlineAlert('deleteAccountAlert', 'Your session expired. Please log in again before deleting your account.', 'warning');
      return;
    }

    const btn = document.getElementById('btnConfirmDeleteAccount');
    setButtonLoading(btn, true);
    showInlineAlert('deleteAccountAlert', '');

    try {
      const resp = await fetch('/api/account/delete', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + session.access_token,
        },
        body: JSON.stringify({ confirm_text: 'DELETE' }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        showInlineAlert('deleteAccountAlert', data.error || 'Account deletion failed.', 'danger');
        return;
      }

      const sb = getClient();
      if (sb) {
        await sb.auth.signOut({ scope: 'local' });
      }
      currentSession = null;
      currentUser = null;
      const modalEl = document.getElementById('deleteAccountModal');
      if (modalEl && window.bootstrap) {
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      }
      alert(data.message || 'Your account has been permanently deleted.');
      window.location.href = '/';
    } catch (err) {
      showInlineAlert('deleteAccountAlert', 'Network error while deleting account. Please try again.', 'danger');
    } finally {
      setButtonLoading(btn, false);
    }
  }

  // ══════════════════════════════════════════════════════
  // Deep-link Loading on Calculator Page (/?profile_id= or /?history_id=)
  // ══════════════════════════════════════════════════════
  async function handleCalculatorDeepLinks() {
    if (deepLinkHandled || !window.TithiCalculator) return;
    const params = new URLSearchParams(window.location.search);
    const profileId = params.get('profile_id');
    const historyId = params.get('history_id');
    const recalc = params.get('recalc') === '1';

    if (!profileId && !historyId) return;
    deepLinkHandled = true;

    const sb = getClient();
    const session = await ensureValidSession();
    if (!sb || !session) {
      toastError('Please log in to load your saved profile or calculation history.');
      openAuthModal('login');
      return;
    }

    if (profileId) {
      const { data, error } = await sb
        .from('saved_birth_profiles')
        .select('*')
        .eq('id', profileId)
        .single();

      if (error || !data) {
        toastError('Could not load saved birth profile.');
        return;
      }

      const payload = {
        birth_date: data.birth_date,
        lat: data.latitude,
        lon: data.longitude,
        timezone: data.timezone,
        location_name: data.location_name,
        ayanamsha: data.ayanamsha,
        lunar_system: data.lunar_system,
        observance_method: data.observance_method,
        adhika_rule: data.adhika_rule,
        start_year: data.start_year,
        end_year: data.end_year,
        birth_time_mode: data.birth_time_mode,
        birth_time: data.birth_time ? String(data.birth_time).slice(0, 5) : '',
        birth_time_start: data.birth_time_start ? String(data.birth_time_start).slice(0, 5) : '',
        birth_time_end: data.birth_time_end ? String(data.birth_time_end).slice(0, 5) : '',
      };

      window.TithiCalculator.setActiveSavedProfileId(data.id);
      window.TithiCalculator.fillCalculatorForm(payload);
      await window.TithiCalculator.runCalculationFromForm();
      return;
    }

    if (historyId) {
      const { data, error } = await sb
        .from('calculation_history')
        .select('*')
        .eq('id', historyId)
        .single();

      if (error || !data) {
        toastError('Could not load saved calculation history entry.');
        return;
      }

      const inp = data.input_data || {};
      const res = data.calculation_result || null;

      window.TithiCalculator.setActiveSavedProfileId(data.saved_birth_profile_id || null);
      window.TithiCalculator.fillCalculatorForm(inp);

      if (recalc || !res || !res.panchang) {
        await window.TithiCalculator.runCalculationFromForm();
      } else {
        // Validate historical input_data server-side before enabling exports
        let validForExport = false;
        try {
          const valResp = await fetch('/api/validate-input', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(inp),
          });
          const valData = await valResp.json();
          validForExport = Boolean(valResp.ok && valData.valid);
          if (!validForExport) {
            toastError('Saved calculation inputs failed validation for export: ' + (valData.error || 'Invalid input'));
          }
        } catch (_) {
          validForExport = false;
        }
        window.TithiCalculator.displaySavedCalculation(res, validForExport ? inp : null);
      }
    }
  }

  // ══════════════════════════════════════════════════════
  // Initialization
  // ══════════════════════════════════════════════════════
  async function init() {
    if (initialized) return;
    initialized = true;

    document.getElementById('loginForm')?.addEventListener('submit', handleLoginSubmit);
    document.getElementById('signupForm')?.addEventListener('submit', handleSignupSubmit);
    document.getElementById('saveProfileForm')?.addEventListener('submit', handleSaveProfileSubmit);
    document.getElementById('renameProfileForm')?.addEventListener('submit', handleRenameProfileSubmit);

    // Delegated click handlers avoid inline-onclick quoting issues with apostrophes
    document.getElementById('saved-profiles-list')?.addEventListener('click', event => {
      const editBtn = event.target.closest('.btn-edit-profile');
      if (editBtn) {
        openRenameModal(editBtn.dataset.profileId || '', editBtn.dataset.profileLabel || '');
        return;
      }
      const delBtn = event.target.closest('.btn-delete-profile');
      if (delBtn && delBtn.dataset.profileId) {
        deleteProfile(delBtn.dataset.profileId);
      }
    });

    document.getElementById('calculation-history-list')?.addEventListener('click', event => {
      const delHistBtn = event.target.closest('.btn-delete-history');
      if (delHistBtn && delHistBtn.dataset.historyId) {
        deleteHistory(delHistBtn.dataset.historyId);
      }
    });

    const deleteInput = document.getElementById('deleteConfirmInput');
    const deleteBtn = document.getElementById('btnConfirmDeleteAccount');
    if (deleteInput && deleteBtn) {
      deleteInput.addEventListener('input', () => {
        deleteBtn.disabled = deleteInput.value.trim().toUpperCase() !== 'DELETE';
      });
    }

    if (!isConfigured()) {
      updateAuthUI();
      return;
    }

    const loadingEl = document.getElementById('nav-auth-loading');
    if (loadingEl) loadingEl.style.display = '';

    const sb = getClient();
    try {
      const { data } = await sb.auth.getSession();
      currentSession = data?.session || null;
      currentUser = currentSession?.user || null;
    } catch (_) {
      currentSession = null;
      currentUser = null;
    }

    updateAuthUI();

    sb.auth.onAuthStateChange((_event, session) => {
      currentSession = session || null;
      currentUser = currentSession?.user || null;
      updateAuthUI();
    });

    await handleCalculatorDeepLinks();
  }

  document.addEventListener('DOMContentLoaded', init);

  return {
    isConfigured,
    isAuthenticated: () => Boolean(currentUser),
    openAuthModal,
    switchAuthTab,
    logout,
    openSaveProfileModal,
    saveCalculationHistory,
    loadAccountDashboard,
    openRenameModal,
    deleteProfile,
    deleteHistory,
    confirmDeleteAccount,
  };
})();

/**
 * Supabase Authentication, Entitlements, Profile Quota & Google Calendar Sync UI
 *
 * Security notes:
 * - Uses ONLY public Supabase URL and anon key on the frontend.
 * - Plan limits, 14-day trial state, profile quotas, and all Google OAuth
 *   tokens/secrets live strictly on the backend server.
 * - Never trusts localStorage or browser state for entitlements or user identity.
 */
'use strict';

window.TithiAuth = (function () {
  let client = null;
  let currentSession = null;
  let currentUser = null;
  let authModalMode = 'login';
  let initialized = false;
  let deepLinkHandled = false;

  // Cached server-fetched dashboard state for live re-rendering / language switches
  let dashboardState = {
    entitlement: null,
    profiles: [],
    syncedCountsByProfile: {},
    historyRows: [],
    googleConfigured: false,
    connection: null,
    events: [],
    syncLogs: [],
  };

  let activePreviewRequest = null;
  let activePreviewResponse = null;
  let pendingDeleteEventAction = null;
  let syncInProgress = false;

  const ACC_I18N = {
    en: {
      planFree: 'FREE',
      planTrial: 'TITHI PLUS (TRIAL)',
      planPlus: 'TITHI PLUS',
      trialEligibleBadge: '14-Day Free Trial Available',
      trialActiveLabel: 'days remaining in trial',
      trialExpiredLabel: '14-Day Trial Expired',
      startTrialBtn: 'Start 14-Day Free Trial (Free)',
      trialBannerTitle: 'Unlock Unlimited Profiles & Full Google Calendar Sync',
      trialBannerDesc: 'Try Tithi Plus free for 14 days — no payment card required. Sync all family profiles, choose specific years or custom year ranges (1583–2500), and bulk-manage events. Automatically reverts to Free with zero automatic charge.',
      trialActiveTitle: 'Tithi Plus 14-Day Trial Active',
      trialActiveDesc: 'You have full Tithi Plus access including unlimited birth profiles, bulk multi-profile sync, historical year sync, custom year ranges, and ad-free usage.',
      trialExpiredTitle: 'Your 14-Day Tithi Plus Trial Has Ended',
      trialExpiredDesc: 'Your account has returned to the Free plan (max 3 new profiles, 1 synced profile, upcoming 12 months). All previously synchronized Google Calendar events stay in your calendar, and you can disconnect Google or delete Tithi events anytime.',
      upgradeBtn: 'Upgrade to Tithi Plus',
      overLimitWarn: 'You currently have {count} saved profiles from earlier usage. Your existing profiles stay safe and editable, while creating new profiles requires Tithi Plus or staying under 3 profiles.',
      googleNotConfigured: 'Google Calendar integration is not configured on this server yet.',
      googleConnected: 'Connected',
      googleDisconnected: 'Disconnected',
      googleRevoked: 'Re-authorization Required',
      connectGoogleBtn: 'Connect Google Calendar',
      reconnectGoogleBtn: 'Reconnect Google Calendar',
      disconnectGoogleBtn: 'Disconnect Google',
      connectedEmailLabel: 'Connected Google Account',
      lastSyncLabel: 'Last Synchronization',
      neverSynced: 'Not synchronized yet',
      syncConfigTitle: 'Synchronize Hindu Birthdays to Google Calendar',
      noProfilesToSync: 'Save at least one birth profile on the Calculator page first before synchronizing to Google Calendar.',
      goToCalcBtn: 'Go to Calculator',
      selectProfileLabel: 'Select Birth Profile',
      syncModeLabel: 'Synchronization Mode',
      modeFree12m: 'Upcoming 12 Months (Free Plan)',
      modeUpcomingYears: 'Mode A: Upcoming Birthdays (Next N Years)',
      modeSpecificYear: 'Mode B: Specific Year (1583–2500)',
      modeYearRange: 'Mode C: Custom Year Range (Max 120 Years)',
      bulkAllLabel: 'Bulk Sync All Saved Birth Profiles',
      yearsAheadLabel: 'Years Ahead (1–120)',
      specificYearLabel: 'Target Year (1583–2500)',
      fromYearLabel: 'Starting Year',
      toYearLabel: 'Ending Year',
      previewSyncBtn: 'Preview Synchronization',
      plusLockedHint: 'Multi-profile bulk sync, historical years, and custom ranges require Tithi Plus.',
      managedEventsTitle: 'Synced Google Calendar Events (Created by Tithi)',
      filterByProfile: 'Filter by Profile:',
      allProfilesOpt: 'All Profiles',
      noSyncedEvents: 'No active Google Calendar events synced by Tithi yet.',
      colProfile: 'Profile',
      colYear: 'Year',
      colGregDate: 'Gregorian Date',
      colTithiMonth: 'Lunar Month & Tithi',
      colSyncStatus: 'Status',
      colLastSynced: 'Last Synced',
      colActions: 'Actions',
      deleteSingleBtn: 'Delete',
      deleteProfileEventsBtn: 'Delete Events for Profile',
      deleteRangeEventsBtn: 'Delete Year Range (Plus)',
      deleteAllEventsBtn: 'Delete All Tithi Events',
      rangeDeleteStart: 'From Year',
      rangeDeleteEnd: 'To Year',
      syncLogsTitle: 'Synchronization History',
      noSyncLogs: 'No Google Calendar synchronization activity recorded yet.',
      colTime: 'Time',
      colAction: 'Action',
      colMode: 'Mode / Scope',
      colProfilesCount: 'Profiles',
      colYearsSpan: 'Years',
      colCounts: 'C / U / D / F',
      colError: 'Details / Error',
      loadCalcBtn: 'Load & Calculate',
      editLabelBtn: 'Edit Label',
      profileCountFree: '{n} / 3 (Free)',
      profileCountPlus: '{n} (Unlimited)',
      syncedEventsBadge: '{n} synced event(s)',
      previewProfiles: 'Profiles',
      previewCreate: 'To Create',
      previewUpdate: 'Existing to Update',
      previewSkipped: 'Outside Gregorian Year',
      previewDateRange: 'Date Range',
      previewCandidateLabel: 'Candidate Tithi Selection:',
      previewBulkConfirm: 'I confirm synchronizing {n} Hindu birthday event(s) across {p} profile(s) to my Google Calendar.',
      previewEmpty: 'No Hindu birthday dates fell inside the selected range.',
      reauthAlert: 'Google Calendar authorization expired or was revoked. Please click Reconnect Google Calendar.',
    },
    hi: {
      planFree: 'फ़्री (FREE)',
      planTrial: 'तिथि प्लस (ट्रायल)',
      planPlus: 'तिथि प्लस (PLUS)',
      trialEligibleBadge: '14-दिन का निःशुल्क ट्रायल उपलब्ध',
      trialActiveLabel: 'दिन ट्रायल में शेष',
      trialExpiredLabel: '14-दिन का ट्रायल समाप्त',
      startTrialBtn: '14-दिन का निःशुल्क ट्रायल शुरू करें',
      trialBannerTitle: 'असीमित प्रोफ़ाइल और पूर्ण Google कैलेंडर सिंक अनलॉक करें',
      trialBannerDesc: '14 दिनों के लिए तिथि प्लस निःशुल्क आज़माएं — किसी भुगतान कार्ड की आवश्यकता नहीं। सभी पारिवारिक प्रोफ़ाइल सिंक करें, विशिष्ट वर्ष या वर्ष सीमा चुनें। अवधि समाप्त होने पर बिना किसी शुल्क के स्वतः फ़्री प्लान पर वापस आ जाएगा।',
      trialActiveTitle: 'तिथि प्लस 14-दिन का ट्रायल सक्रिय है',
      trialActiveDesc: 'आपके पास असीमित जन्म प्रोफ़ाइल, बल्क सिंक, ऐतिहासिक वर्ष और कस्टम वर्ष सीमा सहित सभी प्लस सुविधाएँ सक्रिय हैं।',
      trialExpiredTitle: 'आपका 14-दिन का तिथि प्लस ट्रायल समाप्त हो गया है',
      trialExpiredDesc: 'आपका खाता फ़्री प्लान (अधिकतम 3 नई प्रोफ़ाइल, 1 सिंक प्रोफ़ाइल, आगामी 12 महीने) पर लौट आया है। पहले से सिंक किए गए Google कैलेंडर इवेंट्स सुरक्षित रहेंगे और आप कभी भी Google डिस्कनेक्ट कर सकते हैं या इवेंट्स हटा सकते हैं।',
      upgradeBtn: 'तिथि प्लस में अपग्रेड करें',
      overLimitWarn: 'आपके पास पहले से {count} सहेजी गई प्रोफ़ाइल हैं। आपकी मौजूदा प्रोफ़ाइल सुरक्षित रहेंगी, लेकिन नई प्रोफ़ाइल जोड़ने के लिए तिथि प्लस लें या 3 से कम प्रोफ़ाइल रखें।',
      googleNotConfigured: 'इस सर्वर पर Google कैलेंडर एकीकरण अभी कॉन्फ़िगर नहीं है।',
      googleConnected: 'कनेक्टेड',
      googleDisconnected: 'डिस्कनेक्टेड',
      googleRevoked: 'पुनः अनुमति आवश्यक',
      connectGoogleBtn: 'Google कैलेंडर कनेक्ट करें',
      reconnectGoogleBtn: 'Google कैलेंडर पुनः कनेक्ट करें',
      disconnectGoogleBtn: 'Google डिस्कनेक्ट करें',
      connectedEmailLabel: 'जुड़ा हुआ Google खाता',
      lastSyncLabel: 'अंतिम सिंक्रोनाइज़ेशन',
      neverSynced: 'अभी तक सिंक नहीं हुआ',
      syncConfigTitle: 'हिंदू जन्मदिन को Google कैलेंडर में सिंक करें',
      noProfilesToSync: 'Google कैलेंडर में सिंक करने से पहले कैलकुलेटर पृष्ठ पर कम से कम एक जन्म प्रोफ़ाइल सहेजें।',
      goToCalcBtn: 'कैलकुलेटर पर जाएं',
      selectProfileLabel: 'जन्म प्रोफ़ाइल चुनें',
      syncModeLabel: 'सिंक्रोनाइज़ेशन मोड',
      modeFree12m: 'आगामी 12 महीने (फ़्री प्लान)',
      modeUpcomingYears: 'मोड A: आगामी जन्मदिन (अगले N वर्ष)',
      modeSpecificYear: 'मोड B: विशिष्ट वर्ष (1583–2500)',
      modeYearRange: 'मोड C: कस्टम वर्ष सीमा (अधिकतम 120 वर्ष)',
      bulkAllLabel: 'सभी सहेजी गई प्रोफ़ाइल एक साथ सिंक करें (Bulk)',
      yearsAheadLabel: 'आगामी वर्ष (1–120)',
      specificYearLabel: 'लक्ष्य वर्ष (1583–2500)',
      fromYearLabel: 'प्रारंभ वर्ष',
      toYearLabel: 'समाप्ति वर्ष',
      previewSyncBtn: 'सिंक पूर्वावलोकन देखें',
      plusLockedHint: 'मल्टी-प्रोफ़ाइल बल्क सिंक, ऐतिहासिक वर्ष और कस्टम रेंज के लिए तिथि प्लस आवश्यक है।',
      managedEventsTitle: 'सिंक किए गए Google कैलेंडर इवेंट्स (तिथि द्वारा निर्मित)',
      filterByProfile: 'प्रोफ़ाइल के अनुसार फ़िल्टर:',
      allProfilesOpt: 'सभी प्रोफ़ाइल',
      noSyncedEvents: 'तिथि द्वारा अभी तक कोई सक्रिय Google कैलेंडर इवेंट सिंक नहीं किया गया है।',
      colProfile: 'प्रोफ़ाइल',
      colYear: 'वर्ष',
      colGregDate: 'ग्रेगोरियन तिथि',
      colTithiMonth: 'चंद्र मास व तिथि',
      colSyncStatus: 'स्थिति',
      colLastSynced: 'अंतिम सिंक',
      colActions: 'कार्रवाई',
      deleteSingleBtn: 'हटाएं',
      deleteProfileEventsBtn: 'प्रोफ़ाइल के इवेंट्स हटाएं',
      deleteRangeEventsBtn: 'वर्ष सीमा के इवेंट्स हटाएं (प्लस)',
      deleteAllEventsBtn: 'तिथि के सभी इवेंट्स हटाएं',
      rangeDeleteStart: 'प्रारंभ वर्ष',
      rangeDeleteEnd: 'समाप्ति वर्ष',
      syncLogsTitle: 'सिंक्रोनाइज़ेशन इतिहास',
      noSyncLogs: 'अभी तक कोई Google कैलेंडर सिंक्रोनाइज़ेशन इतिहास नहीं है।',
      colTime: 'समय',
      colAction: 'कार्रवाई',
      colMode: 'मोड / क्षेत्र',
      colProfilesCount: 'प्रोफ़ाइल',
      colYearsSpan: 'वर्ष',
      colCounts: 'नए / अपडेट / हटाए / विफल',
      colError: 'विवरण / त्रुटि',
      loadCalcBtn: 'लोड व गणना करें',
      editLabelBtn: 'नाम बदलें',
      profileCountFree: '{n} / 3 (फ़्री)',
      profileCountPlus: '{n} (असीमित)',
      syncedEventsBadge: '{n} सिंक इवेंट',
      previewProfiles: 'प्रोफ़ाइल',
      previewCreate: 'नए बनेंगे',
      previewUpdate: 'अपडेट होंगे',
      previewSkipped: 'ग्रेगोरियन वर्ष से बाहर',
      previewDateRange: 'तिथि सीमा',
      previewCandidateLabel: 'संभावित तिथि चयन:',
      previewBulkConfirm: 'मैं {p} प्रोफ़ाइल के लिए {n} हिंदू जन्मदिन इवेंट Google कैलेंडर में सिंक करने की पुष्टि करता हूँ।',
      previewEmpty: 'चयनित सीमा में कोई हिंदू जन्मदिन तिथि नहीं मिली।',
      reauthAlert: 'Google कैलेंडर अनुमति समाप्त या रद्द हो गई है। कृपया पुनः कनेक्ट करें।',
    },
  };

  function getLang() {
    return localStorage.getItem('tithi_lang') === 'hi' ? 'hi' : 'en';
  }

  function tAcc(key, vars) {
    const lang = getLang();
    let txt = (ACC_I18N[lang] && ACC_I18N[lang][key]) || ACC_I18N.en[key] || key;
    if (vars) {
      Object.keys(vars).forEach(k => {
        txt = txt.replaceAll(`{${k}}`, String(vars[k]));
      });
    }
    return txt;
  }

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
      if (!btn.dataset.origHtml) btn.dataset.origHtml = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Please wait…';
    } else {
      btn.disabled = false;
      btn.innerHTML = defaultHtml || btn.dataset.origHtml || btn.innerHTML;
    }
  }

  async function apiFetch(url, options) {
    const session = await ensureValidSession();
    if (!session || !session.access_token) {
      throw new Error('Session expired. Please log in again.');
    }
    const opts = options || {};
    const headers = {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + session.access_token,
      ...(opts.headers || {}),
    };
    const resp = await fetch(url, {
      ...opts,
      headers,
      credentials: 'same-origin',
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const err = new Error(data.error || `Request failed (${resp.status})`);
      err.status = resp.status;
      err.code = data.code || '';
      err.data = data;
      throw err;
    }
    return data;
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

    if (window.TithiCalculator && typeof window.TithiCalculator.refreshCloudSaveBar === 'function') {
      window.TithiCalculator.refreshCloudSaveBar();
    }

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
    } catch (_) {
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
    } catch (_) {
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
    } catch (_) {
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
  // Explicit Save Actions on Calculator Page (Server Quota Enforced)
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
      const resp = await apiFetch('/api/profiles', {
        method: 'POST',
        body: JSON.stringify({
          ...lastCalc._payload,
          label,
        }),
      });
      const insertedProfile = resp.profile;

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
      if (err.code === 'PROFILE_LIMIT_REACHED') {
        const alertEl = document.getElementById('saveProfileAlert');
        if (alertEl) {
          alertEl.className = 'alert alert-warning';
          alertEl.innerHTML = `${esc(err.message)} <a href="/account" class="alert-link fw-semibold ms-1">Open My Account &amp; Start 14-Day Free Trial →</a>`;
        }
      } else {
        showInlineAlert('saveProfileAlert', err.message || 'Failed to save birth profile.', 'danger');
      }
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
    } catch (_) {
      toastError('Network error saving calculation history.');
      setButtonLoading(btn, false);
    }
  }

  // ══════════════════════════════════════════════════════
  // My Account Dashboard (/account)
  // ══════════════════════════════════════════════════════
  function handleGoogleCallbackQueryParams() {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get('google_connected');
    const errCode = params.get('google_error');
    const errMsg = params.get('google_error_msg');
    if (!connected && !errCode) return;

    if (connected === '1') {
      showInlineAlert('google-oauth-flash', 'Google Calendar connected successfully!', 'success');
    } else if (errCode) {
      showInlineAlert('google-oauth-flash', errMsg || 'Could not complete Google Calendar connection.', 'danger');
    }

    const cleanUrl = window.location.pathname + (window.location.hash || '');
    window.history.replaceState({}, document.title, cleanUrl);
  }

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

    handleGoogleCallbackQueryParams();
    loadAccountDashboard();
  }

  async function loadAccountDashboard() {
    const sb = getClient();
    const session = await ensureValidSession();
    if (!sb || !session) return;

    const profilesContainer = document.getElementById('saved-profiles-list');
    const historyContainer = document.getElementById('calculation-history-list');

    if (profilesContainer) {
      profilesContainer.innerHTML = '<div class="text-muted small"><i class="fas fa-spinner fa-spin me-2"></i>Loading saved profiles…</div>';
    }
    if (historyContainer) {
      historyContainer.innerHTML = '<div class="text-muted small"><i class="fas fa-spinner fa-spin me-2"></i>Loading calculation history…</div>';
    }

    try {
      const [profRes, googleStatusRes, histResp] = await Promise.all([
        apiFetch('/api/profiles'),
        apiFetch('/api/google/status'),
        sb
          .from('calculation_history')
          .select('id, saved_birth_profile_id, input_data, calculation_result, created_at')
          .order('created_at', { ascending: false }),
      ]);

      dashboardState = {
        entitlement: googleStatusRes.entitlement || profRes.entitlement,
        profiles: profRes.profiles || [],
        syncedCountsByProfile: profRes.synced_counts_by_profile || {},
        historyRows: histResp.data || [],
        googleConfigured: Boolean(googleStatusRes.google_calendar_configured),
        connection: googleStatusRes.connection || null,
        events: googleStatusRes.events || [],
        syncLogs: googleStatusRes.sync_logs || [],
      };

      renderAllDashboardSections();
    } catch (err) {
      toastError(err.message || 'Failed to load account data. Please refresh.');
    }
  }

  async function refreshGoogleSyncSection() {
    try {
      const [profRes, googleStatusRes] = await Promise.all([
        apiFetch('/api/profiles'),
        apiFetch('/api/google/status'),
      ]);
      dashboardState.entitlement = googleStatusRes.entitlement || profRes.entitlement;
      dashboardState.profiles = profRes.profiles || [];
      dashboardState.syncedCountsByProfile = profRes.synced_counts_by_profile || {};
      dashboardState.googleConfigured = Boolean(googleStatusRes.google_calendar_configured);
      dashboardState.connection = googleStatusRes.connection || null;
      dashboardState.events = googleStatusRes.events || [];
      dashboardState.syncLogs = googleStatusRes.sync_logs || [];
      renderAllDashboardSections();
    } catch (err) {
      toastError(err.message || 'Failed to refresh Google sync status.');
    }
  }

  function renderAllDashboardSections() {
    renderEntitlementUI();
    renderGoogleSyncUI();
    renderSavedProfilesList(dashboardState.profiles);

    const profileMap = {};
    dashboardState.profiles.forEach(p => { profileMap[p.id] = p.label; });
    renderCalculationHistoryList(dashboardState.historyRows, profileMap);

    const countsEl = document.getElementById('account-counts');
    if (countsEl) {
      countsEl.textContent = `${dashboardState.profiles.length} / ${dashboardState.historyRows.length}`;
    }
  }

  // ── Entitlements & 14-Day Trial UI ──
  function renderEntitlementUI() {
    const ent = dashboardState.entitlement || {};
    const badgeEl = document.getElementById('account-plan-badge');
    const summaryEl = document.getElementById('account-trial-summary');
    const hostEl = document.getElementById('plan-entitlement-host');
    const pillEl = document.getElementById('profiles-quota-pill');
    const limitAlertEl = document.getElementById('saved-profiles-limit-alert');

    const isPlus = Boolean(ent.is_plus);
    const isTrial = ent.plus_source === 'trial';

    if (badgeEl) {
      if (isPlus && isTrial) {
        badgeEl.className = 'badge rounded-pill plan-badge-trial';
        badgeEl.textContent = tAcc('planTrial');
      } else if (isPlus) {
        badgeEl.className = 'badge rounded-pill plan-badge-plus';
        badgeEl.textContent = tAcc('planPlus');
      } else {
        badgeEl.className = 'badge rounded-pill plan-badge-free';
        badgeEl.textContent = tAcc('planFree');
      }
    }

    if (summaryEl) {
      if (isTrial) {
        summaryEl.innerHTML = `<span class="text-success fw-bold">${esc(ent.trial_days_remaining)} ${esc(tAcc('trialActiveLabel'))}</span>`;
      } else if (isPlus) {
        summaryEl.innerHTML = `<span class="text-success fw-bold">${esc(tAcc('planPlus'))}</span>`;
      } else if (ent.trial_expired) {
        summaryEl.innerHTML = `<span class="text-danger fw-semibold">${esc(tAcc('trialExpiredLabel'))}</span>`;
      } else {
        summaryEl.innerHTML = `<span class="text-saffron fw-semibold">${esc(tAcc('trialEligibleBadge'))}</span>`;
      }
    }

    if (pillEl) {
      const pCount = dashboardState.profiles.length;
      pillEl.textContent = isPlus
        ? tAcc('profileCountPlus', { n: pCount })
        : tAcc('profileCountFree', { n: pCount });
    }

    if (limitAlertEl) {
      if (ent.over_profile_limit) {
        limitAlertEl.innerHTML = `
          <div class="alert alert-warning small mb-3">
            <i class="fas fa-info-circle me-1"></i>${esc(tAcc('overLimitWarn', { count: dashboardState.profiles.length }))}
          </div>`;
      } else {
        limitAlertEl.innerHTML = '';
      }
    }

    if (!hostEl) return;

    if (isPlus && isTrial) {
      const expDisp = ent.trial_expires_at ? new Date(ent.trial_expires_at).toLocaleDateString() : '';
      hostEl.innerHTML = `
        <div class="plan-banner plan-banner-trial p-3 rounded d-flex flex-wrap align-items-center justify-content-between gap-3">
          <div>
            <div class="fw-bold text-navy">
              <i class="fas fa-crown text-saffron me-2"></i>${esc(tAcc('trialActiveTitle'))}
              <span class="badge bg-success ms-2">${esc(ent.trial_days_remaining)} ${esc(tAcc('trialActiveLabel'))}</span>
            </div>
            <div class="small text-muted mt-1">
              ${esc(tAcc('trialActiveDesc'))} ${expDisp ? `(Ends ${esc(expDisp)})` : ''}
            </div>
          </div>
          <button type="button" class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#upgradePlusModal">
            <i class="fas fa-star me-1"></i>${esc(tAcc('upgradeBtn'))}
          </button>
        </div>`;
    } else if (!isPlus && ent.trial_expired) {
      hostEl.innerHTML = `
        <div class="plan-banner plan-banner-expired p-3 rounded d-flex flex-wrap align-items-center justify-content-between gap-3">
          <div>
            <div class="fw-bold text-danger">
              <i class="fas fa-hourglass-end me-2"></i>${esc(tAcc('trialExpiredTitle'))}
            </div>
            <div class="small text-muted mt-1">${esc(tAcc('trialExpiredDesc'))}</div>
          </div>
          <button type="button" class="btn btn-sm btn-saffron fw-semibold" data-bs-toggle="modal" data-bs-target="#upgradePlusModal">
            <i class="fas fa-crown me-1"></i>${esc(tAcc('upgradeBtn'))}
          </button>
        </div>`;
    } else if (!isPlus && ent.trial_eligible) {
      hostEl.innerHTML = `
        <div class="plan-banner plan-banner-promo p-3 rounded d-flex flex-wrap align-items-center justify-content-between gap-3">
          <div>
            <div class="fw-bold text-navy">
              <i class="fas fa-gift text-saffron me-2"></i>${esc(tAcc('trialBannerTitle'))}
            </div>
            <div class="small text-muted mt-1">${esc(tAcc('trialBannerDesc'))}</div>
          </div>
          <div class="d-flex gap-2 flex-wrap">
            <button type="button" class="btn btn-sm btn-saffron fw-semibold" id="btn-start-plus-trial">
              <i class="fas fa-bolt me-1"></i>${esc(tAcc('startTrialBtn'))}
            </button>
          </div>
        </div>`;
    } else {
      hostEl.innerHTML = '';
    }
  }

  async function startFreeTrial() {
    const btn = document.getElementById('btn-start-plus-trial');
    setButtonLoading(btn, true);
    try {
      const res = await apiFetch('/api/entitlements/start-trial', { method: 'POST', body: '{}' });
      dashboardState.entitlement = res.entitlement;
      renderAllDashboardSections();
      toastSuccess('Your 14-day Tithi Plus trial is now active!');
    } catch (err) {
      toastError(err.message || 'Unable to start 14-day free trial.');
    } finally {
      setButtonLoading(btn, false);
    }
  }

  // ── Google Calendar Sync UI ──
  function renderGoogleSyncUI() {
    const connHost = document.getElementById('google-connection-host');
    const ctrlHost = document.getElementById('google-sync-controls-host');
    const eventsHost = document.getElementById('google-events-host');
    const logsHost = document.getElementById('google-sync-logs-host');
    if (!connHost || !ctrlHost || !eventsHost || !logsHost) return;

    const conn = dashboardState.connection;
    const status = conn ? conn.status : 'disconnected';
    const isConnected = status === 'connected';
    const isRevoked = status === 'revoked';

    if (!dashboardState.googleConfigured) {
      connHost.innerHTML = `<div class="alert alert-secondary small mb-0">${esc(tAcc('googleNotConfigured'))}</div>`;
    } else {
      let badgeHtml = `<span class="badge bg-secondary">${esc(tAcc('googleDisconnected'))}</span>`;
      if (isConnected) badgeHtml = `<span class="badge bg-success">${esc(tAcc('googleConnected'))}</span>`;
      else if (isRevoked) badgeHtml = `<span class="badge bg-danger">${esc(tAcc('googleRevoked'))}</span>`;

      const lastSyncStr = conn && conn.last_synced_at
        ? new Date(conn.last_synced_at).toLocaleString()
        : tAcc('neverSynced');
      const errHtml = conn && conn.last_sync_error
        ? `<div class="alert alert-warning small mt-2 mb-0"><i class="fas fa-exclamation-triangle me-1"></i>${esc(conn.last_sync_error)}</div>`
        : '';

      connHost.innerHTML = `
        <div class="p-3 rounded border bg-light">
          <div class="d-flex flex-wrap align-items-center justify-content-between gap-3">
            <div>
              <div class="d-flex align-items-center gap-2 mb-1">
                <strong class="text-navy">${esc(tAcc('connectedEmailLabel'))}:</strong>
                ${badgeHtml}
              </div>
              <div class="small">
                ${conn && conn.google_email ? `<span class="fw-semibold">${esc(conn.google_email)}</span>` : '<span class="text-muted">—</span>'}
              </div>
              <div class="small text-muted mt-1">
                <i class="fas fa-clock me-1"></i>${esc(tAcc('lastSyncLabel'))}: <strong>${esc(lastSyncStr)}</strong>
                ${conn && conn.last_sync_status ? `(${esc(conn.last_sync_status)})` : ''}
              </div>
            </div>
            <div class="d-flex gap-2 flex-wrap">
              ${!isConnected
                ? `<button type="button" class="btn btn-saffron fw-semibold" id="btn-connect-google">
                     <i class="fab fa-google me-1"></i>${esc(isRevoked ? tAcc('reconnectGoogleBtn') : tAcc('connectGoogleBtn'))}
                   </button>`
                : `<button type="button" class="btn btn-outline-danger btn-sm" id="btn-open-disconnect-google"
                           data-bs-toggle="modal" data-bs-target="#googleDisconnectModal">
                     <i class="fas fa-unlink me-1"></i>${esc(tAcc('disconnectGoogleBtn'))}
                   </button>`}
              ${isRevoked
                ? `<button type="button" class="btn btn-outline-secondary btn-sm" id="btn-open-disconnect-google"
                           data-bs-toggle="modal" data-bs-target="#googleDisconnectModal">
                     <i class="fas fa-trash me-1"></i>${esc(tAcc('disconnectGoogleBtn'))}
                   </button>`
                : ''}
            </div>
          </div>
          ${errHtml}
        </div>`;
    }

    // Sync controls panel
    const ent = dashboardState.entitlement || {};
    const isPlus = Boolean(ent.is_plus);
    const profiles = dashboardState.profiles || [];

    if (!isConnected) {
      ctrlHost.innerHTML = '';
    } else if (!profiles.length) {
      ctrlHost.innerHTML = `
        <div class="p-3 rounded border text-center">
          <p class="small text-muted mb-2">${esc(tAcc('noProfilesToSync'))}</p>
          <a href="/#calculator" class="btn btn-sm btn-saffron">${esc(tAcc('goToCalcBtn'))}</a>
        </div>`;
    } else if (!isPlus) {
      const optionsHtml = profiles
        .map(p => `<option value="${esc(p.id)}">${esc(p.label)} (${esc(p.birth_date)})</option>`)
        .join('');
      ctrlHost.innerHTML = `
        <div class="p-3 rounded border">
          <h6 class="fw-bold text-navy mb-3"><i class="fas fa-sliders-h text-saffron me-2"></i>${esc(tAcc('syncConfigTitle'))}</h6>
          <div class="row g-3 align-items-end">
            <div class="col-md-5">
              <label class="form-label small fw-semibold" for="syncSingleProfileSelect">${esc(tAcc('selectProfileLabel'))}</label>
              <select class="form-select" id="syncSingleProfileSelect">${optionsHtml}</select>
            </div>
            <div class="col-md-4">
              <label class="form-label small fw-semibold">${esc(tAcc('syncModeLabel'))}</label>
              <input type="text" class="form-control bg-light" value="${esc(tAcc('modeFree12m'))}" readonly />
            </div>
            <div class="col-md-3">
              <button type="button" class="btn btn-saffron w-100 fw-semibold" id="btn-preview-google-sync">
                <i class="fas fa-eye me-1"></i>${esc(tAcc('previewSyncBtn'))}
              </button>
            </div>
          </div>
          <div class="small text-muted mt-2">
            <i class="fas fa-lock text-saffron me-1"></i>${esc(tAcc('plusLockedHint'))}
          </div>
        </div>`;
    } else {
      const checksHtml = profiles.map((p, idx) => `
        <div class="col-sm-6 col-lg-4">
          <div class="form-check p-2 border rounded bg-light">
            <input class="form-check-input ms-0 me-2 sync-profile-checkbox" type="checkbox"
                   value="${esc(p.id)}" id="syncProfChk_${esc(p.id)}" ${idx === 0 ? 'checked' : ''} />
            <label class="form-check-label small fw-semibold text-truncate d-inline-block" style="max-width: 85%;"
                   for="syncProfChk_${esc(p.id)}">${esc(p.label)}</label>
          </div>
        </div>`).join('');

      const curYear = new Date().getFullYear();
      ctrlHost.innerHTML = `
        <div class="p-3 rounded border">
          <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
            <h6 class="fw-bold text-navy mb-0"><i class="fas fa-sliders-h text-saffron me-2"></i>${esc(tAcc('syncConfigTitle'))}</h6>
            <div class="form-check form-switch">
              <input class="form-check-input" type="checkbox" id="syncBulkAllToggle" />
              <label class="form-check-label small fw-semibold" for="syncBulkAllToggle">${esc(tAcc('bulkAllLabel'))}</label>
            </div>
          </div>

          <div class="row g-2 mb-3" id="syncProfilesCheckboxGrid">${checksHtml}</div>

          <div class="row g-3 align-items-end">
            <div class="col-md-5">
              <label class="form-label small fw-semibold" for="plusSyncModeSelect">${esc(tAcc('syncModeLabel'))}</label>
              <select class="form-select" id="plusSyncModeSelect">
                <option value="upcoming_years">${esc(tAcc('modeUpcomingYears'))}</option>
                <option value="specific_year">${esc(tAcc('modeSpecificYear'))}</option>
                <option value="year_range">${esc(tAcc('modeYearRange'))}</option>
              </select>
            </div>
            <div class="col-md-4" id="plusModeParamHost">
              <label class="form-label small fw-semibold" for="syncYearsAheadInput">${esc(tAcc('yearsAheadLabel'))}</label>
              <input type="number" class="form-control" id="syncYearsAheadInput" min="1" max="120" value="5" />
            </div>
            <div class="col-md-3">
              <button type="button" class="btn btn-saffron w-100 fw-semibold" id="btn-preview-google-sync">
                <i class="fas fa-eye me-1"></i>${esc(tAcc('previewSyncBtn'))}
              </button>
            </div>
          </div>
          <div class="row g-2 mt-2 d-none" id="plusSpecificYearRow">
            <div class="col-md-4">
              <label class="form-label small fw-semibold" for="syncSpecificYearInput">${esc(tAcc('specificYearLabel'))}</label>
              <input type="number" class="form-control" id="syncSpecificYearInput" min="1583" max="2500" value="${curYear}" />
            </div>
          </div>
          <div class="row g-2 mt-2 d-none" id="plusYearRangeRow">
            <div class="col-md-4">
              <label class="form-label small fw-semibold" for="syncRangeStartInput">${esc(tAcc('fromYearLabel'))}</label>
              <input type="number" class="form-control" id="syncRangeStartInput" min="1583" max="2500" value="${curYear}" />
            </div>
            <div class="col-md-4">
              <label class="form-label small fw-semibold" for="syncRangeEndInput">${esc(tAcc('toYearLabel'))}</label>
              <input type="number" class="form-control" id="syncRangeEndInput" min="1583" max="2500" value="${Math.min(2500, curYear + 10)}" />
            </div>
          </div>
        </div>`;
    }

    renderManagedEventsSection(eventsHost, isConnected, isPlus);
    renderSyncLogsSection(logsHost);
  }

  function renderManagedEventsSection(container, isConnected, isPlus) {
    const events = dashboardState.events || [];
    const filterEl = document.getElementById('eventsProfileFilterSelect');
    const prevFilter = filterEl ? filterEl.value : 'ALL';

    if (!events.length) {
      container.innerHTML = `
        <div class="border rounded p-3">
          <h6 class="fw-bold text-navy mb-2"><i class="fas fa-calendar-alt text-saffron me-2"></i>${esc(tAcc('managedEventsTitle'))}</h6>
          <p class="small text-muted mb-0">${esc(tAcc('noSyncedEvents'))}</p>
        </div>`;
      return;
    }

    const distinctProfiles = [];
    const seenPid = new Set();
    events.forEach(ev => {
      const pid = ev.saved_birth_profile_id || '';
      const key = pid || `orphan:${ev.profile_label_snapshot}`;
      if (!seenPid.has(key)) {
        seenPid.add(key);
        distinctProfiles.push({
          key,
          profileId: pid,
          label: ev.profile_label_snapshot || 'Deleted Profile',
        });
      }
    });

    const filtered = prevFilter === 'ALL'
      ? events
      : events.filter(ev => (ev.saved_birth_profile_id || `orphan:${ev.profile_label_snapshot}`) === prevFilter);

    const filterOptionsHtml = [`<option value="ALL">${esc(tAcc('allProfilesOpt'))}</option>`]
      .concat(distinctProfiles.map(dp =>
        `<option value="${esc(dp.key)}" ${dp.key === prevFilter ? 'selected' : ''}>${esc(dp.label)}</option>`
      ))
      .join('');

    const profileDeleteOptionsHtml = distinctProfiles
      .filter(dp => dp.profileId)
      .map(dp => `<option value="${esc(dp.profileId)}">${esc(dp.label)}</option>`)
      .join('');

    const rowsHtml = filtered.map(ev => `
      <tr>
        <td class="fw-semibold">${esc(ev.profile_label_snapshot)}</td>
        <td><strong>${esc(ev.hindu_year)}</strong></td>
        <td class="text-nowrap">${esc(ev.gregorian_date)}</td>
        <td>${esc(ev.lunar_month_en || '')} ${esc(ev.tithi_label || '')}</td>
        <td><span class="badge bg-success-subtle text-success border">${esc(ev.sync_status)}</span></td>
        <td class="small text-muted">${ev.last_synced_at ? esc(new Date(ev.last_synced_at).toLocaleString()) : '—'}</td>
        <td class="text-end">
          <button type="button" class="btn btn-sm btn-outline-danger btn-delete-single-google-event"
                  data-event-row-id="${esc(ev.id)}"
                  data-event-desc="${esc(ev.profile_label_snapshot)} (${esc(ev.hindu_year)} — ${esc(ev.gregorian_date)})"
                  ${!isConnected ? 'disabled' : ''}>
            <i class="fas fa-trash-alt me-1"></i>${esc(tAcc('deleteSingleBtn'))}
          </button>
        </td>
      </tr>`).join('');

    container.innerHTML = `
      <div class="border rounded p-3">
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
          <h6 class="fw-bold text-navy mb-0">
            <i class="fas fa-calendar-alt text-saffron me-2"></i>${esc(tAcc('managedEventsTitle'))} (${events.length})
          </h6>
          <div class="d-flex align-items-center gap-2">
            <label class="small text-muted mb-0" for="eventsProfileFilterSelect">${esc(tAcc('filterByProfile'))}</label>
            <select class="form-select form-select-sm" style="width:auto;" id="eventsProfileFilterSelect">${filterOptionsHtml}</select>
          </div>
        </div>

        <div class="table-responsive" style="max-height: 320px; overflow-y: auto;">
          <table class="table table-sm table-hover align-middle small mb-0">
            <thead class="table-light sticky-top">
              <tr>
                <th>${esc(tAcc('colProfile'))}</th>
                <th>${esc(tAcc('colYear'))}</th>
                <th>${esc(tAcc('colGregDate'))}</th>
                <th>${esc(tAcc('colTithiMonth'))}</th>
                <th>${esc(tAcc('colSyncStatus'))}</th>
                <th>${esc(tAcc('colLastSynced'))}</th>
                <th class="text-end">${esc(tAcc('colActions'))}</th>
              </tr>
            </thead>
            <tbody>${rowsHtml}</tbody>
          </table>
        </div>

        <div class="d-flex flex-wrap align-items-end gap-2 mt-3 pt-3 border-top">
          ${profileDeleteOptionsHtml ? `
            <div class="d-flex align-items-center gap-1">
              <select class="form-select form-select-sm" style="width:auto;" id="deleteByProfileSelect">${profileDeleteOptionsHtml}</select>
              <button type="button" class="btn btn-sm btn-outline-danger" id="btn-delete-events-by-profile" ${!isConnected ? 'disabled' : ''}>
                <i class="fas fa-user-times me-1"></i>${esc(tAcc('deleteProfileEventsBtn'))}
              </button>
            </div>` : ''}

          ${isPlus ? `
            <div class="d-flex align-items-center gap-1">
              <input type="number" class="form-control form-control-sm" style="width:92px;" id="deleteRangeStartYear" min="1583" max="2500" placeholder="${esc(tAcc('rangeDeleteStart'))}" />
              <span class="small">–</span>
              <input type="number" class="form-control form-control-sm" style="width:92px;" id="deleteRangeEndYear" min="1583" max="2500" placeholder="${esc(tAcc('rangeDeleteEnd'))}" />
              <button type="button" class="btn btn-sm btn-outline-danger" id="btn-delete-events-by-range" ${!isConnected ? 'disabled' : ''}>
                ${esc(tAcc('deleteRangeEventsBtn'))}
              </button>
            </div>` : ''}

          <button type="button" class="btn btn-sm btn-danger ms-auto" id="btn-delete-all-tithi-events" ${!isConnected ? 'disabled' : ''}>
            <i class="fas fa-trash me-1"></i>${esc(tAcc('deleteAllEventsBtn'))}
          </button>
        </div>
      </div>`;
  }

  function renderSyncLogsSection(container) {
    const logs = dashboardState.syncLogs || [];
    if (!logs.length) {
      container.innerHTML = `
        <div class="border rounded p-3">
          <h6 class="fw-bold text-navy mb-2"><i class="fas fa-clipboard-list text-saffron me-2"></i>${esc(tAcc('syncLogsTitle'))}</h6>
          <p class="small text-muted mb-0">${esc(tAcc('noSyncLogs'))}</p>
        </div>`;
      return;
    }

    const rowsHtml = logs.map(log => {
      const statusBadge = log.status === 'success'
        ? '<span class="badge bg-success">success</span>'
        : (log.status === 'partial'
            ? '<span class="badge bg-warning text-dark">partial</span>'
            : '<span class="badge bg-danger">error</span>');
      const yearSpan = (log.year_start && log.year_end) ? `${log.year_start}–${log.year_end}` : '—';
      const countsText = `${log.created_count || 0} / ${log.updated_count || 0} / ${log.deleted_count || 0} / ${log.failed_count || 0}`;
      return `
        <tr>
          <td class="text-nowrap">${log.created_at ? esc(new Date(log.created_at).toLocaleString()) : '—'}</td>
          <td><span class="fw-semibold">${esc(log.action_type)}</span></td>
          <td>${esc(log.sync_mode || '—')}</td>
          <td>${esc(log.profile_count ?? 0)}</td>
          <td>${esc(yearSpan)}</td>
          <td>${esc(countsText)}</td>
          <td>${statusBadge}${log.error_message ? `<div class="text-danger small mt-1">${esc(log.error_message)}</div>` : ''}</td>
        </tr>`;
    }).join('');

    container.innerHTML = `
      <div class="border rounded p-3">
        <h6 class="fw-bold text-navy mb-3"><i class="fas fa-clipboard-list text-saffron me-2"></i>${esc(tAcc('syncLogsTitle'))}</h6>
        <div class="table-responsive">
          <table class="table table-sm align-middle small mb-0">
            <thead class="table-light">
              <tr>
                <th>${esc(tAcc('colTime'))}</th>
                <th>${esc(tAcc('colAction'))}</th>
                <th>${esc(tAcc('colMode'))}</th>
                <th>${esc(tAcc('colProfilesCount'))}</th>
                <th>${esc(tAcc('colYearsSpan'))}</th>
                <th>${esc(tAcc('colCounts'))}</th>
                <th>${esc(tAcc('colError'))}</th>
              </tr>
            </thead>
            <tbody>${rowsHtml}</tbody>
          </table>
        </div>
      </div>`;
  }

  // ── Google OAuth Connect & Sync Execution ──
  async function connectGoogleCalendar() {
    const btn = document.getElementById('btn-connect-google');
    setButtonLoading(btn, true);
    try {
      const res = await apiFetch('/api/google/oauth/start', { method: 'POST', body: '{}' });
      if (res.auth_url) {
        window.location.assign(res.auth_url);
      } else {
        throw new Error('Could not obtain Google authorization URL.');
      }
    } catch (err) {
      toastError(err.message || 'Could not initiate Google Calendar connection.');
      setButtonLoading(btn, false);
    }
  }

  function gatherSyncRequestParams(candidateSelectionsOverride) {
    const isPlus = Boolean(dashboardState.entitlement && dashboardState.entitlement.is_plus);
    if (!isPlus) {
      const sel = document.getElementById('syncSingleProfileSelect')?.value;
      return {
        profile_ids: sel ? [sel] : [],
        sync_mode: 'upcoming_12m',
        candidate_selections: candidateSelectionsOverride || {},
      };
    }

    const bulkAll = Boolean(document.getElementById('syncBulkAllToggle')?.checked);
    let profileIds = [];
    if (bulkAll) {
      profileIds = (dashboardState.profiles || []).map(p => String(p.id));
    } else {
      document.querySelectorAll('.sync-profile-checkbox:checked').forEach(chk => {
        profileIds.push(chk.value);
      });
    }

    const mode = document.getElementById('plusSyncModeSelect')?.value || 'upcoming_years';
    const req = {
      profile_ids: profileIds,
      sync_mode: mode,
      candidate_selections: candidateSelectionsOverride || {},
    };
    if (mode === 'upcoming_years') {
      req.years_ahead = parseInt(document.getElementById('syncYearsAheadInput')?.value || '5', 10);
    } else if (mode === 'specific_year') {
      req.specific_year = parseInt(document.getElementById('syncSpecificYearInput')?.value || String(new Date().getFullYear()), 10);
    } else if (mode === 'year_range') {
      req.start_year = parseInt(document.getElementById('syncRangeStartInput')?.value || String(new Date().getFullYear()), 10);
      req.end_year = parseInt(document.getElementById('syncRangeEndInput')?.value || String(new Date().getFullYear() + 10), 10);
    }
    return req;
  }

  async function openSyncPreview(candidateSelectionsOverride) {
    const req = gatherSyncRequestParams(candidateSelectionsOverride);
    if (!req.profile_ids.length) {
      toastError('Please select at least one birth profile.');
      return;
    }

    const btn = document.getElementById('btn-preview-google-sync');
    setButtonLoading(btn, true);
    try {
      const preview = await apiFetch('/api/google/sync/preview', {
        method: 'POST',
        body: JSON.stringify(req),
      });
      activePreviewRequest = req;
      activePreviewResponse = preview;
      renderSyncPreviewModal(preview);
      const modalEl = document.getElementById('googleSyncPreviewModal');
      if (modalEl && window.bootstrap) {
        bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    } catch (err) {
      toastError(err.message || 'Unable to generate synchronization preview.');
    } finally {
      setButtonLoading(btn, false);
    }
  }

  function renderSyncPreviewModal(preview) {
    const contentEl = document.getElementById('syncPreviewContent');
    const progWrap = document.getElementById('syncProgressWrap');
    const confirmBtn = document.getElementById('btnConfirmSyncExecute');
    showInlineAlert('syncPreviewAlert', '');
    if (progWrap) progWrap.classList.add('d-none');

    const counts = preview.counts || {};
    const items = preview.items || [];
    const profiles = preview.profiles || [];

    if (!items.length) {
      if (confirmBtn) confirmBtn.disabled = true;
      contentEl.innerHTML = `<div class="alert alert-warning mb-0">${esc(tAcc('previewEmpty'))}</div>`;
      return;
    }
    if (confirmBtn) confirmBtn.disabled = false;

    const candidateControlsHtml = profiles
      .filter(p => p.has_multiple_candidates)
      .map(p => {
        const opts = (p.candidate_options || []).map(opt =>
          `<option value="${opt.index}" ${opt.index === p.candidate_index ? 'selected' : ''}>${esc(opt.label)}</option>`
        ).join('');
        return `
          <div class="alert alert-warning small py-2 mb-2">
            <strong>${esc(p.label)}</strong> — ${esc(tAcc('previewCandidateLabel'))}
            <select class="form-select form-select-sm mt-1 preview-candidate-select" data-profile-id="${esc(p.profile_id)}">
              ${opts}
            </select>
          </div>`;
      }).join('');

    const rangeDisp = preview.date_range && preview.date_range.start
      ? `${preview.date_range.start} → ${preview.date_range.end}`
      : `${preview.year_start}–${preview.year_end}`;

    const rowsPreview = items.slice(0, 60).map(it => `
      <tr>
        <td class="fw-semibold">${esc(it.profile_label)}</td>
        <td>${esc(it.hindu_year)}</td>
        <td class="text-nowrap">${esc(it.gregorian_date)}</td>
        <td>${esc(it.lunar_month_en)} ${esc(it.tithi_label)}</td>
        <td>
          ${it.action === 'create'
            ? '<span class="badge bg-success">Create</span>'
            : '<span class="badge bg-primary">Update</span>'}
        </td>
        <td class="small text-muted">${esc(it.observance_status)}</td>
      </tr>`).join('');

    const bulkRequired = items.length > 1 || profiles.length > 1;
    const bulkCheckboxHtml = bulkRequired ? `
      <div class="form-check p-3 rounded border bg-light mt-3">
        <input class="form-check-input ms-0 me-2" type="checkbox" id="bulkSyncConfirmCheckbox" />
        <label class="form-check-label small fw-semibold" for="bulkSyncConfirmCheckbox">
          ${esc(tAcc('previewBulkConfirm', { n: items.length, p: profiles.length }))}
        </label>
      </div>` : '';

    contentEl.innerHTML = `
      <div class="row g-2 mb-3 text-center">
        <div class="col-6 col-md-3">
          <div class="p-2 rounded border bg-light">
            <div class="small text-muted">${esc(tAcc('previewProfiles'))}</div>
            <div class="fw-bold fs-5 text-navy">${profiles.length}</div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="p-2 rounded border bg-light">
            <div class="small text-muted">${esc(tAcc('previewCreate'))}</div>
            <div class="fw-bold fs-5 text-success">+${counts.create || 0}</div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="p-2 rounded border bg-light">
            <div class="small text-muted">${esc(tAcc('previewUpdate'))}</div>
            <div class="fw-bold fs-5 text-primary">${counts.update || 0}</div>
          </div>
        </div>
        <div class="col-6 col-md-3">
          <div class="p-2 rounded border bg-light">
            <div class="small text-muted">${esc(tAcc('previewSkipped'))}</div>
            <div class="fw-bold fs-5 text-secondary">${counts.skipped || 0}</div>
          </div>
        </div>
      </div>

      <div class="small text-muted mb-2">
        <strong>${esc(tAcc('previewDateRange'))}:</strong> ${esc(rangeDisp)} ·
        <strong>Profiles:</strong> ${esc(profiles.map(p => p.label).join(', '))}
      </div>

      ${candidateControlsHtml}

      <div class="table-responsive border rounded" style="max-height: 260px; overflow-y: auto;">
        <table class="table table-sm table-striped align-middle small mb-0">
          <thead class="table-light sticky-top">
            <tr>
              <th>${esc(tAcc('colProfile'))}</th>
              <th>${esc(tAcc('colYear'))}</th>
              <th>${esc(tAcc('colGregDate'))}</th>
              <th>${esc(tAcc('colTithiMonth'))}</th>
              <th>Action</th>
              <th>${esc(tAcc('colSyncStatus'))}</th>
            </tr>
          </thead>
          <tbody>${rowsPreview}</tbody>
        </table>
      </div>
      ${items.length > 60 ? `<div class="small text-muted mt-1">Showing first 60 of ${items.length} events in preview.</div>` : ''}
      ${bulkCheckboxHtml}`;
  }

  async function executeConfirmedSync() {
    if (!activePreviewRequest || !activePreviewResponse || syncInProgress) return;
    const items = activePreviewResponse.items || [];
    const profiles = activePreviewResponse.profiles || [];
    const bulkRequired = items.length > 1 || profiles.length > 1;
    if (bulkRequired) {
      const chk = document.getElementById('bulkSyncConfirmCheckbox');
      if (!chk || !chk.checked) {
        showInlineAlert('syncPreviewAlert', 'Please tick the confirmation checkbox before starting bulk synchronization.', 'warning');
        return;
      }
    }

    syncInProgress = true;
    const btn = document.getElementById('btnConfirmSyncExecute');
    const progWrap = document.getElementById('syncProgressWrap');
    const progBar = document.getElementById('syncProgressBar');
    const progLbl = document.getElementById('syncProgressLabel');
    const progPct = document.getElementById('syncProgressPercent');
    setButtonLoading(btn, true);
    showInlineAlert('syncPreviewAlert', '');
    if (progWrap) progWrap.classList.remove('d-none');

    let offset = 0;
    const batchLimit = 20;
    const total = items.length;
    const accum = { created: 0, updated: 0, failed: 0 };
    const allErrors = [];

    try {
      while (true) {
        if (progLbl) progLbl.textContent = `Synchronizing ${Math.min(offset + batchLimit, total)} / ${total} events…`;
        const chunkRes = await apiFetch('/api/google/sync/execute', {
          method: 'POST',
          body: JSON.stringify({
            ...activePreviewRequest,
            offset,
            limit: batchLimit,
            accumulated: accum,
          }),
        });
        accum.created += chunkRes.created || 0;
        accum.updated += chunkRes.updated || 0;
        accum.failed += chunkRes.failed || 0;
        if (Array.isArray(chunkRes.errors)) {
          allErrors.push(...chunkRes.errors);
        }

        const pct = total > 0 ? Math.min(100, Math.round((chunkRes.next_offset / total) * 100)) : 100;
        if (progBar) progBar.style.width = `${pct}%`;
        if (progPct) progPct.textContent = `${pct}%`;

        if (chunkRes.done) break;
        offset = chunkRes.next_offset;
      }

      if (accum.failed > 0) {
        showInlineAlert(
          'syncPreviewAlert',
          `Completed with warnings: Created ${accum.created}, Updated ${accum.updated}, Failed ${accum.failed}. ${allErrors.slice(0, 3).join('; ')}`,
          'warning'
        );
      } else {
        showInlineAlert(
          'syncPreviewAlert',
          `Synchronization complete! Created ${accum.created}, Updated ${accum.updated} event(s).`,
          'success'
        );
      }
      if (btn) btn.disabled = true;
      await refreshGoogleSyncSection();
    } catch (err) {
      showInlineAlert('syncPreviewAlert', err.message || 'Synchronization failed.', 'danger');
      if (err.code === 'GOOGLE_REAUTH_REQUIRED') {
        await refreshGoogleSyncSection();
      }
    } finally {
      syncInProgress = false;
      setButtonLoading(btn, false);
    }
  }

  async function confirmDisconnectGoogle() {
    const btn = document.getElementById('btnConfirmDisconnectGoogle');
    const deleteEvents = Boolean(document.getElementById('disconnectDeleteEventsCheck')?.checked);
    setButtonLoading(btn, true);
    showInlineAlert('googleDisconnectAlert', '');
    try {
      const res = await apiFetch('/api/google/disconnect', {
        method: 'POST',
        body: JSON.stringify({ delete_events: deleteEvents }),
      });
      const modalEl = document.getElementById('googleDisconnectModal');
      if (modalEl && window.bootstrap) {
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      }
      toastSuccess(
        deleteEvents
          ? `Google Calendar disconnected and ${res.deleted_events_count || 0} Tithi event(s) deleted.`
          : 'Google Calendar disconnected. Previously synced events remain in your calendar.'
      );
      await refreshGoogleSyncSection();
    } catch (err) {
      showInlineAlert('googleDisconnectAlert', err.message || 'Failed to disconnect Google Calendar.', 'danger');
    } finally {
      setButtonLoading(btn, false);
    }
  }

  function openDeleteCalendarEventsModal(actionPayload, summaryText) {
    pendingDeleteEventAction = actionPayload;
    showInlineAlert('deleteCalEventsAlert', '');
    const summaryEl = document.getElementById('deleteCalEventsSummary');
    if (summaryEl) summaryEl.textContent = summaryText;
    const modalEl = document.getElementById('deleteCalendarEventsModal');
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  }

  async function confirmDeleteCalendarEvents() {
    if (!pendingDeleteEventAction) return;
    const btn = document.getElementById('btnConfirmDeleteCalEvents');
    setButtonLoading(btn, true);
    showInlineAlert('deleteCalEventsAlert', '');
    try {
      const res = await apiFetch('/api/google/events/delete', {
        method: 'POST',
        body: JSON.stringify(pendingDeleteEventAction),
      });
      const modalEl = document.getElementById('deleteCalendarEventsModal');
      if (modalEl && window.bootstrap) {
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      }
      toastSuccess(`Deleted ${res.deleted_count || 0} Tithi calendar event(s).`);
      pendingDeleteEventAction = null;
      await refreshGoogleSyncSection();
    } catch (err) {
      showInlineAlert('deleteCalEventsAlert', err.message || 'Failed deleting calendar events.', 'danger');
    } finally {
      setButtonLoading(btn, false);
    }
  }

  // ── Saved Profiles & Calculation History Lists ──
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

    const syncedCounts = dashboardState.syncedCountsByProfile || {};
    let html = '<div class="row g-3">';
    profiles.forEach(p => {
      const timeDesc = p.birth_time_mode === 'exact'
        ? (p.birth_time || '').slice(0, 5)
        : (p.birth_time_mode === 'approximate'
            ? `${(p.birth_time_start || '').slice(0, 5)}–${(p.birth_time_end || '').slice(0, 5)}`
            : 'Unknown');
      const syncCnt = syncedCounts[p.id] || 0;
      html += `
        <div class="col-md-6">
          <div class="saved-item-card p-3 rounded border h-100 d-flex flex-column justify-content-between">
            <div>
              <div class="d-flex justify-content-between align-items-start gap-2 mb-2">
                <h5 class="mb-0 fw-bold text-navy">${esc(p.label)}</h5>
                <div class="d-flex gap-1 flex-wrap justify-content-end">
                  ${syncCnt > 0 ? `<span class="badge bg-success-subtle text-success border">${esc(tAcc('syncedEventsBadge', { n: syncCnt }))}</span>` : ''}
                  <span class="badge bg-light text-dark border">${esc(p.lunar_system)}</span>
                </div>
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
                <i class="fas fa-play me-1"></i>${esc(tAcc('loadCalcBtn'))}
              </a>
              <button type="button" class="btn btn-sm btn-outline-secondary btn-edit-profile"
                      data-profile-id="${esc(p.id)}" data-profile-label="${esc(p.label)}">
                <i class="fas fa-edit me-1"></i>${esc(tAcc('editLabelBtn'))}
              </button>
              <button type="button" class="btn btn-sm btn-outline-danger ms-auto btn-delete-profile"
                      data-profile-id="${esc(p.id)}" data-profile-label="${esc(p.label)}">
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
      toastSuccess('Profile label updated. (Existing Google Calendar events keep their label until re-synced.)');
      loadAccountDashboard();
    } finally {
      setButtonLoading(btn, false);
    }
  }

  function openDeleteProfileModal(profileId, profileLabel) {
    const syncCnt = (dashboardState.syncedCountsByProfile || {})[profileId] || 0;
    const isGoogleConnected = dashboardState.connection && dashboardState.connection.status === 'connected';
    document.getElementById('deleteProfileTargetId').value = profileId;
    showInlineAlert('deleteProfileAlert', '');

    const textEl = document.getElementById('deleteProfileConsequenceText');
    const optWrap = document.getElementById('deleteProfileGoogleOptionWrap');
    const chk = document.getElementById('deleteProfileGoogleEventsCheck');
    if (chk) chk.checked = false;

    if (syncCnt > 0) {
      textEl.textContent = `Delete saved birth profile "${profileLabel}"? This profile currently has ${syncCnt} synchronized event(s) in Google Calendar. Deleting the profile will NOT silently delete those Google Calendar events unless you explicitly check the box below.`;
      if (optWrap) optWrap.classList.toggle('d-none', !isGoogleConnected);
    } else {
      textEl.textContent = `Delete saved birth profile "${profileLabel}"? Any linked calculation history will be preserved without the profile link.`;
      if (optWrap) optWrap.classList.add('d-none');
    }

    const modalEl = document.getElementById('deleteProfileModal');
    if (modalEl && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    }
  }

  async function confirmDeleteProfile() {
    const id = document.getElementById('deleteProfileTargetId').value;
    if (!id) return;
    const deleteGoogleEvents = Boolean(document.getElementById('deleteProfileGoogleEventsCheck')?.checked);
    const btn = document.getElementById('btnConfirmDeleteProfile');
    setButtonLoading(btn, true);
    showInlineAlert('deleteProfileAlert', '');

    try {
      const res = await apiFetch(`/api/profiles/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        body: JSON.stringify({ delete_calendar_events: deleteGoogleEvents }),
      });
      const modalEl = document.getElementById('deleteProfileModal');
      if (modalEl && window.bootstrap) {
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      }
      toastSuccess(
        res.deleted_calendar_events
          ? `Birth profile deleted and ${res.deleted_calendar_events} Google Calendar event(s) removed.`
          : 'Birth profile deleted.'
      );
      loadAccountDashboard();
    } catch (err) {
      showInlineAlert('deleteProfileAlert', err.message || 'Failed to delete birth profile.', 'danger');
    } finally {
      setButtonLoading(btn, false);
    }
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
    } catch (_) {
      showInlineAlert('deleteAccountAlert', 'Network error while deleting account. Please try again.', 'danger');
    } finally {
      setButtonLoading(btn, false);
    }
  }

  // ══════════════════════════════════════════════════════
  // Deep-link Loading on Calculator Page
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
  // Initialization & Event Delegation
  // ══════════════════════════════════════════════════════
  function bindAccountDashboardDelegatedEvents() {
    document.getElementById('plan-entitlement-host')?.addEventListener('click', event => {
      if (event.target.closest('#btn-start-plus-trial')) {
        startFreeTrial();
      }
    });

    document.getElementById('google-connection-host')?.addEventListener('click', event => {
      if (event.target.closest('#btn-connect-google')) {
        connectGoogleCalendar();
      }
    });

    const ctrlHost = document.getElementById('google-sync-controls-host');
    ctrlHost?.addEventListener('change', event => {
      if (event.target.id === 'syncBulkAllToggle') {
        const bulk = Boolean(event.target.checked);
        document.querySelectorAll('.sync-profile-checkbox').forEach(chk => {
          chk.checked = bulk;
          chk.disabled = bulk;
        });
      }
      if (event.target.id === 'plusSyncModeSelect') {
        const mode = event.target.value;
        const paramHost = document.getElementById('plusModeParamHost');
        const specRow = document.getElementById('plusSpecificYearRow');
        const rangeRow = document.getElementById('plusYearRangeRow');
        if (paramHost) paramHost.classList.toggle('d-none', mode !== 'upcoming_years');
        if (specRow) specRow.classList.toggle('d-none', mode !== 'specific_year');
        if (rangeRow) rangeRow.classList.toggle('d-none', mode !== 'year_range');
      }
    });
    ctrlHost?.addEventListener('click', event => {
      if (event.target.closest('#btn-preview-google-sync')) {
        openSyncPreview();
      }
    });

    document.getElementById('googleSyncPreviewModal')?.addEventListener('change', event => {
      if (event.target.classList.contains('preview-candidate-select') && activePreviewRequest) {
        const nextSel = { ...(activePreviewRequest.candidate_selections || {}) };
        document.querySelectorAll('.preview-candidate-select').forEach(selEl => {
          nextSel[selEl.dataset.profileId] = parseInt(selEl.value, 10) || 0;
        });
        openSyncPreview(nextSel);
      }
    });

    const eventsHost = document.getElementById('google-events-host');
    eventsHost?.addEventListener('change', event => {
      if (event.target.id === 'eventsProfileFilterSelect') {
        const ent = dashboardState.entitlement || {};
        const isConnected = dashboardState.connection && dashboardState.connection.status === 'connected';
        renderManagedEventsSection(eventsHost, Boolean(isConnected), Boolean(ent.is_plus));
      }
    });
    eventsHost?.addEventListener('click', event => {
      const singleBtn = event.target.closest('.btn-delete-single-google-event');
      if (singleBtn) {
        openDeleteCalendarEventsModal(
          { scope: 'single', event_record_id: singleBtn.dataset.eventRowId },
          `Delete Google Calendar event for ${singleBtn.dataset.eventDesc || 'this entry'}?`
        );
        return;
      }
      if (event.target.closest('#btn-delete-events-by-profile')) {
        const selEl = document.getElementById('deleteByProfileSelect');
        const pid = selEl?.value;
        const plabel = selEl?.selectedOptions?.[0]?.textContent || 'this profile';
        if (pid) {
          openDeleteCalendarEventsModal(
            { scope: 'profile', profile_id: pid },
            `Delete all Tithi-created Google Calendar events for "${plabel}"?`
          );
        }
        return;
      }
      if (event.target.closest('#btn-delete-events-by-range')) {
        const sy = parseInt(document.getElementById('deleteRangeStartYear')?.value || '', 10);
        const ey = parseInt(document.getElementById('deleteRangeEndYear')?.value || '', 10);
        if (isNaN(sy) || isNaN(ey) || ey < sy) {
          toastError('Please enter a valid starting and ending year to delete.');
          return;
        }
        openDeleteCalendarEventsModal(
          { scope: 'year_range', year_start: sy, year_end: ey },
          `Delete all Tithi-created Google Calendar events in years ${sy}–${ey}?`
        );
        return;
      }
      if (event.target.closest('#btn-delete-all-tithi-events')) {
        openDeleteCalendarEventsModal(
          { scope: 'all' },
          'Delete ALL events created by Tithi from your connected Google Calendar?'
        );
      }
    });

    document.getElementById('saved-profiles-list')?.addEventListener('click', event => {
      const editBtn = event.target.closest('.btn-edit-profile');
      if (editBtn) {
        openRenameModal(editBtn.dataset.profileId || '', editBtn.dataset.profileLabel || '');
        return;
      }
      const delBtn = event.target.closest('.btn-delete-profile');
      if (delBtn && delBtn.dataset.profileId) {
        openDeleteProfileModal(delBtn.dataset.profileId, delBtn.dataset.profileLabel || 'Profile');
      }
    });

    document.getElementById('calculation-history-list')?.addEventListener('click', event => {
      const delHistBtn = event.target.closest('.btn-delete-history');
      if (delHistBtn && delHistBtn.dataset.historyId) {
        deleteHistory(delHistBtn.dataset.historyId);
      }
    });
  }

  async function init() {
    if (initialized) return;
    initialized = true;

    document.getElementById('loginForm')?.addEventListener('submit', handleLoginSubmit);
    document.getElementById('signupForm')?.addEventListener('submit', handleSignupSubmit);
    document.getElementById('saveProfileForm')?.addEventListener('submit', handleSaveProfileSubmit);
    document.getElementById('renameProfileForm')?.addEventListener('submit', handleRenameProfileSubmit);

    bindAccountDashboardDelegatedEvents();

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
    refreshGoogleSyncSection,
    openRenameModal,
    confirmDeleteProfile,
    deleteHistory,
    confirmDeleteAccount,
    executeConfirmedSync,
    confirmDisconnectGoogle,
    confirmDeleteCalendarEvents,
    onLanguageChange: () => {
      if (document.getElementById('account-dashboard') && currentUser) {
        renderAllDashboardSections();
      }
    },
  };
})();

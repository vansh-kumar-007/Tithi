# Google Cloud Console & Render Setup Guide (Tithi V1.1)

This guide explains how to configure Google Cloud OAuth 2.0 credentials for **Tithi V1.1** (`https://tithi-f24b.onrender.com`) and configure the required server environment variables on Render and local development.

---

## 1. Create Google Cloud Project & Enable Google Calendar API

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project selector in the top bar and choose **New Project** (e.g., `Tithi-Hindu-Calendar`).
3. Inside the new project, open **APIs & Services → Library**.
4. Search for **Google Calendar API** and click **Enable**.

---

## 2. Configure the OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen** (or **Google Auth Platform → Branding / Audience**).
2. Choose **External** as the User Type (so any Google user can authorize their own calendar) and click **Create**.
3. Fill in required **App Information**:
   - **App name:** `Hindu Tithi Birthday Calculator (Tithi)`
   - **User support email:** your support email address
   - **Developer contact information:** your email address
4. Under **App domain** (required when publishing to production):
   - **Application home page:** `https://tithi-f24b.onrender.com`
   - **Application privacy policy link:** `https://tithi-f24b.onrender.com/privacy`
   - **Authorized domain:** `onrender.com` *(or custom domain if added later)*
5. Under **Scopes** (**Data Access → Add or remove scopes**), add ONLY these three minimal scopes:
   - `https://www.googleapis.com/auth/calendar.events` *(View and edit events on all your calendars — creates/updates/deletes only Tithi birthday events)*
   - `openid`
   - `https://www.googleapis.com/auth/userinfo.email` *(Reads primary Google email address for display in My Account)*
   - **Do NOT add** Gmail, Drive, Contacts, or full Calendar admin scopes.

### Important: Testing vs Published Production Verification
- While **Publishing Status** is **Testing**:
  - Only **Test Users** explicitly listed under **Audience → Test Users** (up to **100 test users**) can connect Google Calendar.
  - Refresh tokens issued while in Testing mode **automatically expire after 7 days** (Tithi handles expired tokens gracefully by prompting the user to reconnect).
- Before opening to the general public:
  - Because `https://www.googleapis.com/auth/calendar.events` is a **Google sensitive scope**, switch Publishing Status to **In Production** and submit **Google OAuth App Verification**.
  - Google's verification team typically requires:
    1. A live working homepage (`https://tithi-f24b.onrender.com`) and privacy policy page (`https://tithi-f24b.onrender.com/privacy`).
    2. A short screen-recording demo video showing the OAuth consent screen (including the Client ID in the URL bar) and how Tithi creates/updates/deletes events.
    3. Clear explanation of why `calendar.events` is required (Hindu lunar birthdays shift every Gregorian year so recurring rules cannot be used).

---

## 3. Create OAuth 2.0 Web Application Credentials

1. Navigate to **APIs & Services → Credentials → + Create Credentials → OAuth client ID**.
2. Choose **Application type: Web application**.
3. Set **Name:** `Tithi Web Client`.
4. Under **Authorized JavaScript origins**, add:
   - `https://tithi-f24b.onrender.com`
   - `http://localhost:5000` *(local development)*
5. Under **Authorized redirect URIs**, add BOTH exact callbacks:
   - **Production:** `https://tithi-f24b.onrender.com/auth/google/callback`
   - **Local Development:** `http://localhost:5000/auth/google/callback` *(and `http://127.0.0.1:5000/auth/google/callback` if you open 127.0.0.1 locally)*
6. Click **Create** and securely note your **Client ID** and **Client Secret**. Never commit these values to Git.

---

## 4. Generate a Fernet Encryption Key

Tithi encrypts all stored Google refresh tokens and access tokens server-side using `cryptography.fernet.Fernet`.

Generate a fresh 32-byte URL-safe base64 key in your terminal:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep this key private in your server `.env` and Render Environment Variables. Rotating keys is also supported by supplying comma-separated Fernet keys (`new_key,old_key` for `MultiFernet`).

---

## 5. Environment Variables

### Local `.env` (for development)
```env
GOOGLE_CLIENT_ID=your-google-oauth-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
GOOGLE_REDIRECT_URI=http://localhost:5000/auth/google/callback
GOOGLE_TOKEN_ENCRYPTION_KEY=<generated-fernet-key>
```

### Render Dashboard → Environment → Environment Variables (Production)
Set these in addition to `SECRET_KEY`, `DEBUG=false`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_SERVICE_ROLE_KEY`:

| Key | Value |
| --- | --- |
| `GOOGLE_CLIENT_ID` | Your Google OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | Your Google OAuth Client Secret |
| `GOOGLE_REDIRECT_URI` | `https://tithi-f24b.onrender.com/auth/google/callback` |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | Your generated Fernet encryption key |

Check safe diagnostic status (booleans only, zero secrets exposed) after deployment at:
`GET https://tithi-f24b.onrender.com/api/google-status`

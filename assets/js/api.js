/**
 * BITVORA EXCHANGE — API Client
 * Single fetch wrapper used by all pages.
 * Handles JWT injection, token refresh, 401 redirects, error normalization.
 */

// Decode JWT payload without signature verification (client-side only)
function _decodeJwtPayload(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const json = decodeURIComponent(
            atob(base64).split('').map(c =>
                '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
            ).join('')
        );
        return JSON.parse(json);
    } catch (e) {
        return null;
    }
}

// Check if JWT is expired or expiring within 60 seconds
function _isTokenExpiringSoon(token) {
    const payload = _decodeJwtPayload(token);
    if (!payload || !payload.exp) return true;
    const now = Math.floor(Date.now() / 1000);
    return payload.exp - now < 60;
}

// Attempt to refresh the access token
async function _refreshToken() {
    const refreshToken = localStorage.getItem('bitvora_refresh_token');
    if (!refreshToken) return null;

    try {
        const resp = await fetch(`${BITVORA_CONFIG.API_BASE_URL}/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken }),
        });

        if (!resp.ok) {
            // Refresh token expired — clear session
            localStorage.removeItem('bitvora_session');
            localStorage.removeItem('bitvora_refresh_token');
            return null;
        }

        const data = await resp.json();
        localStorage.setItem('bitvora_session', data.access_token);
        localStorage.setItem('bitvora_refresh_token', data.refresh_token);
        return data.access_token;
    } catch (e) {
        return null;
    }
}

/**
 * Main API fetch wrapper.
 * @param {string} endpoint - API path e.g. "/transaction/quote"
 * @param {object} options - fetch options (method, body, headers, etc.)
 * @returns {object} { ok, status, data, error }
 */
async function apiFetch(endpoint, options = {}) {
    const url = `${BITVORA_CONFIG.API_BASE_URL}${endpoint}`;

    // Prepare headers
    const headers = { ...options.headers };
    if (!headers['Content-Type'] && options.body && typeof options.body === 'string') {
        headers['Content-Type'] = 'application/json';
    }

    // Inject JWT if available
    let token = localStorage.getItem('bitvora_session');
    if (token) {
        // Proactive refresh if expiring soon
        if (_isTokenExpiringSoon(token)) {
            const newToken = await _refreshToken();
            if (newToken) {
                token = newToken;
            } else {
                // Refresh failed — redirect to signin
                window.location.href = 'signin.html?expired=1';
                return { ok: false, status: 401, data: null, error: 'Session expired' };
            }
        }
        headers['Authorization'] = `Bearer ${token}`;
    }

    try {
        const resp = await fetch(url, { ...options, headers });
        const data = await resp.json().catch(() => null);

        // Handle token_expired specifically
        if (resp.status === 401 && data && data.detail === 'token_expired') {
            const newToken = await _refreshToken();
            if (newToken) {
                // Retry the original request with new token
                headers['Authorization'] = `Bearer ${newToken}`;
                const retryResp = await fetch(url, { ...options, headers });
                const retryData = await retryResp.json().catch(() => null);
                return {
                    ok: retryResp.ok,
                    status: retryResp.status,
                    data: retryData,
                    error: retryResp.ok ? null : (retryData?.detail || 'Request failed'),
                };
            } else {
                window.location.href = '/pages/signin.html?expired=1';
                return { ok: false, status: 401, data: null, error: 'Session expired' };
            }
        }

        // Handle other 401s
        if (resp.status === 401) {
            localStorage.removeItem('bitvora_session');
            localStorage.removeItem('bitvora_refresh_token');
            window.location.href = '/pages/signin.html';
            return { ok: false, status: 401, data: null, error: 'Unauthorized' };
        }

        return {
            ok: resp.ok,
            status: resp.status,
            data: data,
            error: resp.ok ? null : (data?.detail || 'Request failed'),
        };
    } catch (e) {
        return {
            ok: false,
            status: 0,
            data: null,
            error: 'Network error. Check your connection and try again.',
        };
    }
}

/**
 * Get the current user info from the stored JWT.
 * @returns {object|null} { sub, username, exp }
 */
function getCurrentUser() {
    const token = localStorage.getItem('bitvora_session');
    if (!token) return null;
    const payload = _decodeJwtPayload(token);
    if (!payload) return null;
    // Check expiry
    const now = Math.floor(Date.now() / 1000);
    if (payload.exp && payload.exp < now) return null;
    return payload;
}

/**
 * Check if user is authenticated. Redirects to signin if not.
 * @returns {boolean}
 */
function requireAuth() {
    const user = getCurrentUser();
    if (!user) {
        window.location.href = '/pages/signin.html';
        return false;
    }
    return true;
}

/**
 * Sign out — clear session and redirect.
 */
function signOut() {
    localStorage.removeItem('bitvora_session');
    localStorage.removeItem('bitvora_refresh_token');
    window.location.replace('/pages/signin.html');
}

// Hide Telegram WebApp Back Button if injected
if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.BackButton) {
    window.Telegram.WebApp.BackButton.hide();
}

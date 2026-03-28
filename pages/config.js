/**
 * BITVORA EXCHANGE — Frontend Configuration
 * SECURE VERSION: No direct database keys in the browser.
 * All data passes through the FastAPI backend "Layer".
 */

const BITVORA_CONFIG = {
    // Auto-detect: localhost → local API, bitvora.in → production API
    API_BASE_URL: (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
        ? 'http://localhost:8000'
        : 'https://api.bitvora.in',

    SUPPORT_EMAIL: 'support@bitvora.in',
};

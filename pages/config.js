/**
 * BITVORA EXCHANGE — Frontend Configuration
 * SECURE VERSION: No direct database keys in the browser.
 * All data passes through the FastAPI backend "Layer".
 */

const BITVORA_CONFIG = {
    // Force production API for local testing since backend is on the VPS
    API_BASE_URL: 'https://api.bitvora.in',
    SUPPORT_EMAIL: 'support@bitvora.in',
};

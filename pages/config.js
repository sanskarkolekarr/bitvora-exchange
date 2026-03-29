/**
 * BITVORA EXCHANGE — Frontend Configuration
 * SECURE VERSION: No direct database keys in the browser.
 * All data passes through the FastAPI backend "Layer".
 */

const BITVORA_CONFIG = {
    // Force production API using Nginx proxy to bypass Cloudflare Tunnel 502 issue
    API_BASE_URL: 'https://bitvora.in/api',
    SUPPORT_EMAIL: 'support@bitvora.in',
};

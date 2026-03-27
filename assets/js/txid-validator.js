/**
 * BITVORA EXCHANGE — TXID Validator
 * Client-side format validation per chain.
 */

function validateTxid(txid, chain) {
    if (!txid || !chain) {
        return { valid: false, error: '· TRANSACTION NOT FOUND ON CHAIN. VERIFY YOUR TXID AND SELECTED NETWORK.' };
    }

    const trimmedTxid = txid.trim();
    const targetChain = chain.toLowerCase();

    // EVM Chains
    if (['ethereum', 'bsc', 'polygon', 'arbitrum', 'avalanche'].includes(targetChain)) {
        const evmRegex = /^0x[a-fA-F0-9]{64}$/;
        if (!evmRegex.test(trimmedTxid)) {
            return { valid: false, error: '· MALFORMED TXID. EVM TXIDS MUST START WITH 0x FOLLOWED BY 64 HEX CHARACTERS.' };
        }
    }
    
    // Tron
    else if (targetChain === 'tron') {
        const tronRegex = /^[a-fA-F0-9]{64}$/;
        if (!tronRegex.test(trimmedTxid)) {
            return { valid: false, error: '· MALFORMED TXID. TRON TXIDS MUST BE EXACTLY 64 HEX CHARACTERS.' };
        }
    }
    
    // Solana (base58)
    else if (targetChain === 'solana') {
        const solanaRegex = /^[1-9A-HJ-NP-Za-km-z]{87,88}$/;
        if (!solanaRegex.test(trimmedTxid)) {
            return { valid: false, error: '· MALFORMED SIGNATURE. SOLANA SIGNATURES MUST BE 87-88 BASE58 CHARACTERS.' };
        }
    }
    
    // Bitcoin
    else if (targetChain === 'bitcoin') {
        const btcRegex = /^[a-fA-F0-9]{64}$/;
        if (!btcRegex.test(trimmedTxid)) {
            return { valid: false, error: '· MALFORMED TXID. BITCOIN TXIDS MUST BE EXACTLY 64 HEX CHARACTERS.' };
        }
    }
    
    // TON
    else if (targetChain === 'ton') {
        const tonRegex = /^[a-fA-F0-9]{64}$/;
        // Note: TON can also be base64. The backend normalizes it.
        // For client side, we'll accept either 64 hex OR base64 length (44 chars)
        const tonBase64Regex = /^[A-Za-z0-9+/=_-]{43,44}$/;
        if (!tonRegex.test(trimmedTxid) && !tonBase64Regex.test(trimmedTxid)) {
            return { valid: false, error: '· MALFORMED TXID. TON TXIDS MUST BE 64 HEX CHARACTERS OR A BASE64 HASH.' };
        }
    }
    
    else {
        return { valid: false, error: '· UNSUPPORTED NETWORK SELECTED.' };
    }

    return { valid: true, error: null };
}

// Export for module systems or attach to window
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { validateTxid };
} else {
    window.validateTxid = validateTxid;
}

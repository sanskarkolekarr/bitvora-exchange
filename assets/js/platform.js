/**
 * BITVORA EXCHANGE — Platform Enhancements
 * Maintenance Mode overlay, Live Payout Feed, AI Chatbot Widget
 * Injected on every public page via <script src="../assets/js/platform.js">
 */

(async function () {
    // Use global BITVORA_CONFIG, fallback to empty string
    const API = (typeof BITVORA_CONFIG !== 'undefined' && BITVORA_CONFIG.API_BASE_URL) ? BITVORA_CONFIG.API_BASE_URL : '';

    // ═══════════════════════════════════════════════════════════
    // 1. MAINTENANCE MODE CHECK
    // ═══════════════════════════════════════════════════════════

    async function checkMaintenance() {
        try {
            const res = await fetch(`${API}/assets/status`);
            if (!res.ok) return;
            const data = await res.json();
            if (data.maintenance) {
                showMaintenanceOverlay();
            }
        } catch (e) { /* silently fail if backend offline */ }
    }

    function showMaintenanceOverlay() {
        // Remove submit/action buttons so users can't proceed
        document.querySelectorAll('button[type="submit"], a[href="submit.html"]').forEach(el => {
            el.style.pointerEvents = 'none';
            el.style.opacity = '0.3';
        });

        // Inject overlay
        const existing = document.getElementById('maintenance-overlay');
        if (existing) return;

        const overlay = document.createElement('div');
        overlay.id = 'maintenance-overlay';
        overlay.style.cssText = `
            position: fixed; inset: 0; z-index: 9999;
            background: rgba(6,6,8,0.92); backdrop-filter: blur(24px);
            display: flex; flex-direction: column;
            align-items: center; justify-content: center;
            text-align: center; padding: 24px;
        `;
        overlay.innerHTML = `
            <div style="max-width: 480px;">
                <div style="width: 64px; height: 64px; border-radius: 16px; background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); display: flex; align-items: center; justify-content: center; margin: 0 auto 24px;">
                    <span class="material-symbols-outlined" style="color: #ef4444; font-size: 32px;">construction</span>
                </div>
                <h1 style="font-family: 'Geist', sans-serif; font-size: 32px; color: white; margin-bottom: 12px; letter-spacing: -0.02em;">Under Maintenance</h1>
                <p style="font-family: 'Geist Mono', monospace; font-size: 11px; color: rgba(200,200,216,0.6); text-transform: uppercase; letter-spacing: 0.15em; line-height: 1.8;">
                    BITVORA Exchange is temporarily unavailable.<br>Existing transactions continue to process in the background.<br>Check back shortly.
                </p>
                <div style="margin-top: 32px; display: flex; align-items: center; justify-content: center; gap: 8px;">
                    <span style="width: 8px; height: 8px; border-radius: 50%; background: #ef4444; animation: pulse 2s infinite;"></span>
                    <span style="font-family: 'Geist Mono', monospace; font-size: 10px; color: rgba(200,200,216,0.4); text-transform: uppercase; letter-spacing: 0.2em;">SYSTEM OFFLINE</span>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
    }


    // ═══════════════════════════════════════════════════════════
    // 2. LIVE PAYOUT FEED MARQUEE
    // Only injected on the homepage (index.html)
    // ═══════════════════════════════════════════════════════════

    const isHomepage = window.location.pathname.endsWith('index.html') || window.location.pathname === '/' || window.location.pathname.endsWith('/pages/');

    async function injectPayoutFeed() {
        if (!isHomepage) return;
        // Find the inject point — just before the footer
        const footer = document.querySelector('footer');
        if (!footer) return;

        try {
            const res = await fetch(`${API}/assets/recent-payouts`);
            if (!res.ok) return;
            const data = await res.json();
            if (!data.payouts || data.payouts.length === 0) return;

            const container = document.createElement('div');
            container.style.cssText = `overflow: hidden; position: relative; width: 100%; padding: 24px 0; border-top: 1px solid rgba(255,255,255,0.04); border-bottom: 1px solid rgba(255,255,255,0.04); margin-bottom: 0;`;

            const label = document.createElement('div');
            label.style.cssText = `position: absolute; left: 0; top: 0; bottom: 0; width: 120px; background: linear-gradient(to right, #060608 60%, transparent); z-index: 10; display: flex; align-items: center; padding-left: 24px;`;
            label.innerHTML = `<span style="font-family: 'Geist Mono', monospace; font-size: 9px; text-transform: uppercase; letter-spacing: 0.2em; color: rgba(200,200,216,0.3);">LIVE FEED</span>`;

            const labelRight = document.createElement('div');
            labelRight.style.cssText = `position: absolute; right: 0; top: 0; bottom: 0; width: 80px; background: linear-gradient(to left, #060608 60%, transparent); z-index: 10;`;

            const track = document.createElement('div');
            track.style.cssText = `display: flex; gap: 48px; width: max-content; animation: marquee-scroll 30s linear infinite; padding-left: 160px;`;

            const formatINR = (num) => {
                if (num >= 10000000) return `₹${(num / 10000000).toFixed(1)}Cr`;
                if (num >= 100000) return `₹${(num / 100000).toFixed(1)}L`;
                return `₹${Number(num).toLocaleString('en-IN')}`;
            };

            const timeAgo = (ts) => {
                const secs = Math.floor((Date.now() - new Date(ts)) / 1000);
                if (secs < 60) return `${secs}s ago`;
                if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
                return `${Math.floor(secs / 3600)}h ago`;
            };

            // Duplicate payouts for seamless loop
            const doubled = [...data.payouts, ...data.payouts];
            doubled.forEach(p => {
                const chip = document.createElement('div');
                chip.style.cssText = `display: inline-flex; align-items: center; gap: 10px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 100px; padding: 8px 16px; white-space: nowrap; flex-shrink: 0;`;
                chip.innerHTML = `
                    <span style="font-family: 'Geist Mono', monospace; font-size: 10px; color: rgba(200,200,216,0.6);">${p.asset.toUpperCase()}</span>
                    <span style="color: rgba(255,255,255,0.2); font-size: 10px;">→</span>
                    <span style="font-family: 'Geist', sans-serif; font-size: 12px; font-weight: 500; color: white;">${formatINR(p.amount_inr)}</span>
                    <span style="color: #22c55e; font-size: 12px;">✓</span>
                    <span style="font-family: 'Geist Mono', monospace; font-size: 9px; color: rgba(200,200,216,0.3);">${timeAgo(p.payout_sent_at)}</span>
                `;
                track.appendChild(chip);
            });

            container.appendChild(label);
            container.appendChild(labelRight);
            container.appendChild(track);

            // Add keyframe if not present
            if (!document.getElementById('marquee-style')) {
                const style = document.createElement('style');
                style.id = 'marquee-style';
                style.textContent = `@keyframes marquee-scroll { 0% { transform: translateX(0); } 100% { transform: translateX(-50%); } }`;
                document.head.appendChild(style);
            }

            footer.parentNode.insertBefore(container, footer);
        } catch (e) {}
    }


    // ═══════════════════════════════════════════════════════════
    // INIT
    // ═══════════════════════════════════════════════════════════

    // Wait for DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    async function init() {
        await checkMaintenance();
        injectPayoutFeed();
    }

})();

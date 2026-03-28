/**
 * KINETIC MONOLITH — Shared Components
 * Injects Navbar, Footer, and overlays for landing/marketing pages.
 * Functional pages (exchange, dashboard, tracker, profile) have their own built-in nav.
 */

const NAVBAR_HTML = `
    <!-- Kinetic Topbar (Marketing Pages) -->
    <nav id="navbar" class="navbar-pill z-[110]" style="
        position:fixed; top:0; width:100%;
        border-bottom:1px solid rgba(255,255,255,0.06);
        background:rgba(0,0,0,0.95);
        backdrop-filter:blur(12px);
        z-index:110;
        display:flex; justify-content:space-between; align-items:center;
        padding:16px 24px;
    ">
        <a href="index.html" class="flex items-center gap-2 group whitespace-nowrap" style="text-decoration:none;">
            <span class="material-symbols-outlined text-zinc-100" style="font-variation-settings:'FILL' 1;">toll</span>
            <span class="text-xl font-headline font-bold tracking-tighter text-zinc-100" style="font-family:'Space Grotesk',sans-serif;">KINETIC</span>
        </a>
        
        <!-- Center Nav (Desktop) -->
        <div class="hidden lg:flex items-center gap-4">
            <a href="index.html" style="font-family:'Inter',sans-serif;font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;color:rgba(255,255,255,0.3);transition:color 0.1s;">Home</a>
            <a href="exchange.html" style="font-family:'Inter',sans-serif;font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;color:rgba(255,255,255,0.3);transition:color 0.1s;">Exchange</a>
            <a href="dashboard.html" style="font-family:'Inter',sans-serif;font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;color:rgba(255,255,255,0.3);transition:color 0.1s;">Dashboard</a>
            <a href="profile.html" style="font-family:'Inter',sans-serif;font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;color:rgba(255,255,255,0.3);transition:color 0.1s;">Profile</a>
            <a href="support.html" style="font-family:'Inter',sans-serif;font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;color:rgba(255,255,255,0.3);transition:color 0.1s;">Support</a>
        </div>
        
        <!-- Right Zone -->
        <div class="flex items-center gap-3">
            <!-- Guest State -->
            <a id="nav-launch" href="signin.html" style="
                background:linear-gradient(135deg, #E5E5E5 0%, #6E6E6E 50%, #2A2A2A 100%);
                color:#000; padding:6px 20px; border-radius:2px;
                font-family:'Space Grotesk',sans-serif; font-weight:700;
                font-size:10px; letter-spacing:0.12em; text-transform:uppercase;
                text-decoration:none; transition:all 0.1s;
            ">LAUNCH</a>
            
            <!-- Logged-in State -->
            <div id="nav-user-zone" class="hidden items-center gap-3">
                <a href="exchange.html" class="hidden md:inline-block" style="font-family:'DM Mono',monospace;font-size:10px;color:rgba(255,255,255,0.3);text-decoration:none;letter-spacing:0.1em;">EXCHANGE</a>
                <a id="nav-dash-v2" href="dashboard.html" style="
                    background:linear-gradient(135deg, #E5E5E5 0%, #6E6E6E 50%, #2A2A2A 100%);
                    color:#000; padding:6px 20px; border-radius:2px;
                    font-family:'Space Grotesk',sans-serif; font-weight:700;
                    font-size:10px; letter-spacing:0.12em; text-transform:uppercase;
                    text-decoration:none;
                ">DASHBOARD</a>
                
                <button onclick="(typeof signOut === 'function' ? signOut() : (localStorage.removeItem('bitvora_session'), window.location.href='signin.html'))" class="hidden md:flex" style="
                    width:28px;height:28px;border-radius:2px;
                    background:rgba(255,255,255,0.04);
                    border:1px solid rgba(255,255,255,0.06);
                    display:flex;align-items:center;justify-content:center;
                    opacity:0.4;cursor:pointer;transition:opacity 0.1s;
                ">
                    <span class="material-symbols-outlined" style="font-size:13px;color:#E5E5E5;">logout</span>
                </button>
            </div>

            <div class="lg:hidden" style="height:18px;width:1px;background:rgba(255,255,255,0.06);margin:0 4px;"></div>
            
            <button id="mobile-menu-btn" class="lg:hidden" style="
                width:32px;height:32px;display:flex;align-items:center;justify-content:center;
                border-radius:2px;background:rgba(255,255,255,0.04);
                border:1px solid rgba(255,255,255,0.06);cursor:pointer;
            ">
                <span class="material-symbols-outlined" style="font-size:18px;color:rgba(255,255,255,0.5);">menu</span>
            </button>
        </div>
    </nav>
`;

const MOBILE_OVERLAY_HTML = `
<div id="mobile-overlay" style="
    position:fixed;inset:0;background:rgba(0,0,0,0.97);backdrop-filter:blur(8px);
    z-index:200;opacity:0;pointer-events:none;transition:opacity 0.2s ease;
">
    <button id="mobile-close" style="position:absolute;top:32px;right:32px;color:#E5E5E5;background:none;border:none;cursor:pointer;min-width:44px;min-height:44px;display:flex;align-items:center;justify-content:center;">
        <span class="material-symbols-outlined" style="font-size:24px;">close</span>
    </button>
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:36px;">
        <a href="index.html" class="mobile-nav-link" style="font-family:'Space Grotesk',sans-serif;font-size:20px;font-weight:700;color:#E5E5E5;text-decoration:none;letter-spacing:-0.02em;text-transform:uppercase;opacity:0;transform:translateY(8px);transition:all 0.2s;">HOME</a>
        <a href="exchange.html" class="mobile-nav-link" style="font-family:'Space Grotesk',sans-serif;font-size:20px;font-weight:700;color:#E5E5E5;text-decoration:none;letter-spacing:-0.02em;text-transform:uppercase;opacity:0;transform:translateY(8px);transition:all 0.2s;transition-delay:0.05s;">EXCHANGE</a>
        <a href="dashboard.html" class="mobile-nav-link" style="font-family:'Space Grotesk',sans-serif;font-size:20px;font-weight:700;color:#E5E5E5;text-decoration:none;letter-spacing:-0.02em;text-transform:uppercase;opacity:0;transform:translateY(8px);transition:all 0.2s;transition-delay:0.1s;">DASHBOARD</a>
        <a href="profile.html" class="mobile-nav-link" style="font-family:'Space Grotesk',sans-serif;font-size:20px;font-weight:700;color:#E5E5E5;text-decoration:none;letter-spacing:-0.02em;text-transform:uppercase;opacity:0;transform:translateY(8px);transition:all 0.2s;transition-delay:0.15s;">PROFILE</a>
        <a href="support.html" class="mobile-nav-link" style="font-family:'Space Grotesk',sans-serif;font-size:20px;font-weight:700;color:#E5E5E5;text-decoration:none;letter-spacing:-0.02em;text-transform:uppercase;opacity:0;transform:translateY(8px);transition:all 0.2s;transition-delay:0.2s;">SUPPORT</a>
        <div style="width:80vw;max-width:280px;height:1px;background:rgba(255,255,255,0.06);"></div>
        <a href="signin.html" style="
            background:linear-gradient(135deg, #E5E5E5 0%, #6E6E6E 50%, #2A2A2A 100%);
            color:#000;padding:16px 48px;border-radius:2px;
            font-family:'Space Grotesk',sans-serif;font-weight:700;
            font-size:11px;letter-spacing:0.15em;text-transform:uppercase;
            text-decoration:none;text-align:center;width:100%;max-width:280px;
        ">LAUNCH APP</a>
    </div>
</div>
`;

const FOOTER_HTML = `
    <footer style="width:100%;background:#000;padding:60px 24px 40px;border-top:1px solid rgba(255,255,255,0.04);">
        <div style="max-width:1200px;margin:0 auto;">
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:40px;margin-bottom:40px;">
                <!-- Brand -->
                <div>
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:16px;">
                        <span class="material-symbols-outlined" style="font-size:20px;color:#E5E5E5;font-variation-settings:'FILL' 1;">toll</span>
                        <span style="font-family:'Space Grotesk',sans-serif;font-size:16px;font-weight:700;color:#E5E5E5;letter-spacing:-0.02em;">KINETIC</span>
                    </div>
                    <p style="font-family:'Inter',sans-serif;font-size:13px;color:rgba(255,255,255,0.2);line-height:1.6;max-width:250px;">Turn crypto into rupees. Instant settlement, institutional liquidity.</p>
                </div>
                <!-- Platform -->
                <div>
                    <span style="font-family:'DM Mono',monospace;font-size:9px;letter-spacing:0.2em;text-transform:uppercase;color:rgba(255,255,255,0.15);font-weight:700;">Platform</span>
                    <div style="display:flex;flex-direction:column;gap:10px;margin-top:16px;">
                        <a href="exchange.html" style="font-family:'Inter',sans-serif;font-size:13px;color:rgba(255,255,255,0.3);text-decoration:none;">Exchange</a>
                        <a href="dashboard.html" style="font-family:'Inter',sans-serif;font-size:13px;color:rgba(255,255,255,0.3);text-decoration:none;">Dashboard</a>
                        <a href="tracker.html" style="font-family:'Inter',sans-serif;font-size:13px;color:rgba(255,255,255,0.3);text-decoration:none;">Tracker</a>
                        <a href="profile.html" style="font-family:'Inter',sans-serif;font-size:13px;color:rgba(255,255,255,0.3);text-decoration:none;">Profile</a>
                    </div>
                </div>
            </div>
            <div style="border-top:1px solid rgba(255,255,255,0.04);padding-top:24px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;">
                <span style="font-family:'DM Mono',monospace;font-size:10px;color:rgba(255,255,255,0.1);letter-spacing:0.15em;">© 2026 BITVORA_EXCHANGE</span>
                <span style="font-family:'DM Mono',monospace;font-size:9px;color:rgba(255,255,255,0.08);letter-spacing:0.2em;text-transform:uppercase;">Built for the decentralized era.</span>
            </div>
        </div>
    </footer>
`;

function injectComponents() {
    // Inject Navbar if not disabled
    const noNav = document.body.classList.contains('no-navbar');
    if (!noNav && !document.getElementById('navbar')) {
        document.body.insertAdjacentHTML('afterbegin', NAVBAR_HTML);
        document.body.insertAdjacentHTML('beforeend', MOBILE_OVERLAY_HTML);
        _initNavbarLogic();
    }

    // Inject Footer if not disabled
    const noFooter = document.body.classList.contains('no-footer');
    if (!noFooter && !document.querySelector('footer')) {
        document.body.insertAdjacentHTML('beforeend', FOOTER_HTML);
    }
}

function _initNavbarLogic() {
    // Mobile Menu Logic
    const overlay = document.getElementById("mobile-overlay");
    const closeBtn = document.getElementById("mobile-close");
    const links = document.querySelectorAll(".mobile-nav-link");
    const menuBtn = document.getElementById("mobile-menu-btn");

    const openMenu = () => {
        if(!overlay) return;
        overlay.style.opacity = '1';
        overlay.style.pointerEvents = 'all';
        links.forEach(l => { l.style.opacity = '1'; l.style.transform = 'translateY(0)'; });
    };
    const closeMenu = () => {
        if(!overlay) return;
        overlay.style.opacity = '0';
        overlay.style.pointerEvents = 'none';
        links.forEach(l => { l.style.opacity = '0'; l.style.transform = 'translateY(8px)'; });
    };

    if(menuBtn) menuBtn.addEventListener("click", openMenu);
    if(closeBtn) closeBtn.addEventListener("click", closeMenu);
    links.forEach(l => l.addEventListener("click", closeMenu));
    if(overlay) overlay.addEventListener("click", (e) => { if(e.target === overlay) closeMenu(); });

    // Auth-aware logic
    function _getNavUser() {
        try {
            const token = localStorage.getItem('bitvora_session');
            if (!token) return null;
            const base64Url = token.split('.')[1];
            if (!base64Url) return null;
            const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
            const payload = JSON.parse(decodeURIComponent(
                atob(base64).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join('')
            ));
            if (!payload) return null;
            const now = Math.floor(Date.now() / 1000);
            if (payload.exp && payload.exp < now) return null;
            return payload;
        } catch(e) { return null; }
    }

    function _applyNavAuth() {
        const user = _getNavUser();
        const launchBtn = document.getElementById('nav-launch');
        const userZone = document.getElementById('nav-user-zone');

        if (user) {
            if (launchBtn) launchBtn.style.display = 'none';
            if (userZone) {
                userZone.classList.remove('hidden');
                userZone.style.display = 'flex';
            }
            const heroCta = document.getElementById('hero-cta');
            if (heroCta) { heroCta.href = 'dashboard.html'; heroCta.innerText = 'GO TO DASHBOARD'; }
        } else {
            if (launchBtn) launchBtn.style.display = 'inline-block';
            if (userZone) { userZone.classList.add('hidden'); userZone.style.display = ''; }
        }
    }

    _applyNavAuth();
}

// Auto-inject when script loads
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectComponents);
} else {
    injectComponents();
}

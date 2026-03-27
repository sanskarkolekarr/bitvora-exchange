/**
 * BITVORA EXCHANGE — Shared Components
 * Injects Navbar, Footer, Cursor, and overlays to eliminate HTML duplication.
 */

const NOISE_CURSOR_HTML = `
    <div class="noise-overlay"></div>
`;

const NAVBAR_HTML = `
    <!-- Floating Pill Navbar -->
    <nav id="navbar" class="navbar-pill z-[110]">
        <!-- Left Zone: Wordmark -->
        <a href="index.html" class="flex items-center gap-2 group whitespace-nowrap">
            <span class="font-headline font-semibold text-[11px] md:text-[12px] tracking-[0.04em] text-white/90 group-hover:text-white transition-colors">BITVORA_EXCHANGE</span>
            <span class="hidden md:inline-flex h-[10px] w-[1px] bg-white/10"></span>
            <span class="hidden md:inline font-mono text-[9px] text-[#22c55e] animate-pulse">LIVE</span>
        </a>
        
        <!-- Center Zone: Nav Links (Desktop) -->
        <div class="hidden lg:flex items-center gap-[18px]">
            <a href="how-it-works.html" class="font-mono text-[9px] font-normal tracking-[0.1em] text-[rgba(255,255,255,0.3)] hover:text-white transition-colors uppercase">HOW IT WORKS</a>
            <a href="assets.html" class="font-mono text-[9px] font-normal tracking-[0.1em] text-[rgba(255,255,255,0.3)] hover:text-white transition-colors uppercase">ASSETS</a>
            <a href="why-us.html" class="font-mono text-[9px] font-normal tracking-[0.1em] text-[rgba(255,255,255,0.3)] hover:text-white transition-colors uppercase">WHY US</a>
            <a href="support.html" class="font-mono text-[9px] font-normal tracking-[0.1em] text-[rgba(255,255,255,0.3)] hover:text-white transition-colors uppercase">SUPPORT</a>
        </div>
        
        <!-- Right Zone (Desktop & Mobile Actions) -->
        <div class="flex items-center gap-[12px]">
            <!-- Guest State -->
            <a id="nav-launch" href="signin.html" class="bg-white text-black rounded-full px-4 py-[6px] font-headline font-bold text-[10px] tracking-[0.05em] uppercase hover:bg-gray-200 transition-all">LAUNCH</a>
            
            <!-- Logged-in State -->
            <div id="nav-user-zone" class="hidden items-center gap-[12px]">
                <a href="submit.html" class="hidden md:inline-block font-mono text-[9px] text-white/40 hover:text-white transition-colors">SUBMIT</a>
                <a id="nav-dash-v2" href="dashboard.html" class="bg-white text-black px-4 py-[6px] rounded-full font-headline font-bold text-[10px] tracking-[0.05em] uppercase">DASHBOARD</a>
                
                <button onclick="(typeof signOut === 'function' ? signOut() : (localStorage.removeItem('bitvora_session'), window.location.href='signin.html'))" class="hidden md:flex w-[26px] h-[26px] rounded-full bg-white/[0.04] border border-white/[0.08] items-center justify-center opacity-40 hover:opacity-100 transition-all">
                    <span class="material-symbols-outlined text-[12px]">logout</span>
                </button>
            </div>

            <div class="lg:hidden h-[18px] w-[1px] bg-white/10 mx-1"></div>
            
            <button id="mobile-menu-btn" class="lg:hidden w-[32px] h-[32px] flex items-center justify-center rounded-full bg-white/[0.05] border border-white/[0.08]">
                <span class="material-symbols-outlined text-[18px] text-white/60">menu</span>
            </button>
        </div>
    </nav>

`;

const MOBILE_OVERLAY_HTML = `
<div id="mobile-overlay" class="fixed inset-0 bg-[rgba(6,6,8,0.97)] backdrop-blur-[24px] z-[200] opacity-0 pointer-events-none transition-all duration-350" style="transition-timing-function: cubic-bezier(0.16,1,0.3,1);">
    <button id="mobile-close" class="absolute top-[32px] right-[32px] text-white flex items-center justify-center" style="min-width: 44px; min-height: 44px;">
        <span class="material-symbols-outlined text-[24px]">close</span>
    </button>
    <div class="flex flex-col items-center justify-center h-full gap-[40px]">
        <a href="how-it-works.html" class="mobile-nav-link font-headline text-[32px] font-medium text-white opacity-0 translate-y-[16px] transition-all duration-300">HOW IT WORKS</a>
        <a href="assets.html" class="mobile-nav-link font-headline text-[32px] font-medium text-white opacity-0 translate-y-[16px] transition-all duration-300" style="transition-delay: 0.1s">ASSETS</a>
        <a href="why-us.html" class="mobile-nav-link font-headline text-[32px] font-medium text-white opacity-0 translate-y-[16px] transition-all duration-300" style="transition-delay: 0.2s">WHY US</a>
        <a href="support.html" class="mobile-nav-link font-headline text-[32px] font-medium text-white opacity-0 translate-y-[16px] transition-all duration-300" style="transition-delay: 0.3s">SUPPORT</a>
        <div class="w-[80vw] max-w-[280px] h-[1px] bg-[rgba(255,255,255,0.08)]"></div>
        <a href="signin.html" class="bg-white text-black px-12 py-4 rounded-full font-headline font-bold uppercase tracking-widest text-center w-full max-w-[280px]">LAUNCH APP</a>
    </div>
</div>
`;

const FOOTER_HTML = `
    <!-- Premium Footer Section -->
    <footer class="w-full bg-black pt-20 pb-12 px-6 md:px-12 border-t border-white/5" style="padding-bottom: env(safe-area-inset-bottom);">
        <div class="max-w-7xl mx-auto flex flex-col lg:flex-row gap-8">
            <!-- Footer Card 1: Branding & Socials -->
            <div class="flex-1 bg-[#080808] border border-white/5 rounded-[40px] p-10 md:p-14 relative overflow-hidden group min-h-[400px]">
                <div class="absolute -right-10 top-1/2 -translate-y-1/2 w-64 h-64 opacity-60 pointer-events-none animate-[float_6s_ease-in-out_infinite]">
                    <canvas class="metallic-logo w-full h-full" width="200" height="200"></canvas>
                </div>
                <div class="relative z-10 h-full flex flex-col">
                    <div class="flex items-center gap-3 mb-8">
                        <canvas class="metallic-logo w-8 h-8 rounded-full" width="100" height="100"></canvas>
                        <span class="text-xl font-bold tracking-tight text-white font-headline">BITVORA_EXCHANGE</span>
                    </div>
                    <h3 class="text-3xl md:text-4xl font-headline text-white leading-tight mb-auto max-w-xs">
                        Turn Crypto Into Rupees, <span class="text-white/40">powered by speed.</span>
                    </h3>
                    <div class="mt-12">
                        <p class="font-mono text-[10px] uppercase tracking-[0.3em] text-white/40 mb-6 font-bold">STAY CONNECTED</p>
                        <div class="flex gap-4">
                            <a href="#" class="w-12 h-12 rounded-full bg-white/5 border border-white/10 flex items-center justify-center hover:bg-white hover:text-black transition-all duration-400">
                                <span class="material-symbols-outlined text-[20px]">send</span>
                            </a>
                            <a href="#" class="w-12 h-12 rounded-full bg-white/5 border border-white/10 flex items-center justify-center hover:bg-white hover:text-black transition-all duration-400">
                                <span class="material-symbols-outlined text-[20px]">camera</span>
                            </a>
                            <a href="#" class="w-12 h-12 rounded-full bg-white/5 border border-white/10 flex items-center justify-center hover:bg-white hover:text-black transition-all duration-400">
                                <span class="material-symbols-outlined text-[20px]">contact_support</span>
                            </a>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Footer Card 2: Navigation -->
            <div class="lg:w-[60%] bg-[#080808] border border-white/5 rounded-[40px] p-10 md:p-14 flex flex-col">
                <div class="grid grid-cols-2 md:grid-cols-3 gap-12 mb-auto">
                    <!-- Navigation Column -->
                    <div class="flex flex-col gap-6">
                        <span class="font-mono text-[10px] uppercase tracking-[0.3em] text-[#3b82f6] font-bold">NAVIGATION</span>
                        <div class="flex flex-col gap-4">
                            <a href="how-it-works.html" class="text-white/60 hover:text-white transition-colors font-body text-sm">How It Works</a>
                            <a href="assets.html" class="text-white/60 hover:text-white transition-colors font-body text-sm">Assets</a>
                            <a href="why-us.html" class="text-white/60 hover:text-white transition-colors font-body text-sm">Why Us</a>
                            <a href="support.html" class="text-white/60 hover:text-white transition-colors font-body text-sm">Support</a>
                        </div>
                    </div>
                    <!-- Resources Column -->
                    <div class="flex flex-col gap-6">
                        <span class="font-mono text-[10px] uppercase tracking-[0.3em] text-[#3b82f6] font-bold">BITVORA_EXCHANGE</span>
                        <div class="flex flex-col gap-4">
                            <a href="#" class="text-white/60 hover:text-white transition-colors font-body text-sm">About Us</a>
                            <a href="#" class="text-white/60 hover:text-white transition-colors font-body text-sm">Official Telegram</a>
                            <a href="#" class="text-white/60 hover:text-white transition-colors font-body text-sm">Legal & Privacy</a>
                            <a href="#" class="text-white/60 hover:text-white transition-colors font-body text-sm">Status Page</a>
                        </div>
                    </div>
                </div>

                <div class="mt-20 pt-10 border-t border-white/5 flex flex-col md:flex-row justify-between items-end gap-10">
                    <div class="flex flex-col gap-2">
                        <span class="text-white/20 font-mono text-[11px] tracking-widest">© 2026 BITVORA_EXCHANGE.</span>
                        <span class="text-white/10 font-mono text-[9px] tracking-[0.2em] uppercase">Built for the decentralized era.</span>
                    </div>
                    <div class="text-right">
                        <p class="text-white/40 font-body text-sm italic mb-2">Crypto moves fast.</p>
                        <p class="text-white font-headline text-lg tracking-tight">Stay ahead with BITVORA.</p>
                    </div>
                </div>
            </div>
        </div>
    </footer>
`;

function injectComponents() {
    // 1. Inject Noise & Cursor
    if (!document.querySelector('.noise-overlay')) {
        document.body.insertAdjacentHTML('afterbegin', NOISE_CURSOR_HTML);
    }

    // 2. Inject Navbar & Mobile Overlay if not present and not disabled by a meta tag or class
    const noNav = document.body.classList.contains('no-navbar');
    if (!noNav && !document.getElementById('navbar')) {
        document.body.insertAdjacentHTML('afterbegin', NAVBAR_HTML);
        document.body.insertAdjacentHTML('beforeend', MOBILE_OVERLAY_HTML);
        _initNavbarLogic();
    }

    // 3. Inject Footer if not present and not disabled
    const noFooter = document.body.classList.contains('no-footer');
    if (!noFooter && !document.querySelector('footer')) {
        document.body.insertAdjacentHTML('beforeend', FOOTER_HTML);
        // Dispatch event for metallic logo to draw
        window.dispatchEvent(new Event('componentsLoaded'));
    }
}

function _initNavbarLogic() {
    const navbar = document.getElementById('navbar');
    
    // Initial Drop-in Entrance
    setTimeout(() => {
        if(navbar) navbar.classList.add('loaded');
    }, 300);

    // Scrolling Glass transition
    window.addEventListener('scroll', () => {
        if (window.scrollY > 80) {
            navbar?.classList.add('scrolled');
        } else {
            navbar?.classList.remove('scrolled');
        }
    });

    // Mobile Menu Logic
    const triggers = document.querySelectorAll(".mobile-menu-trigger, #mobile-menu-btn");
    const overlay = document.getElementById("mobile-overlay");
    const closeBtn = document.getElementById("mobile-close");
    const links = document.querySelectorAll(".mobile-nav-link");
    
    const openMenu = () => {
        if(!overlay) return;
        overlay.style.opacity = '1';
        overlay.style.pointerEvents = 'all';
        links.forEach(l => {
            l.style.opacity = '1';
            l.style.transform = 'translateY(0)';
        });
    };
    const closeMenu = () => {
        if(!overlay) return;
        overlay.style.opacity = '0';
        overlay.style.pointerEvents = 'none';
        links.forEach(l => {
            l.style.opacity = '0';
            l.style.transform = 'translateY(16px)';
        });
    };
    
    triggers.forEach(t => t.addEventListener("click", openMenu));
    if(closeBtn) closeBtn.addEventListener("click", closeMenu);
    links.forEach(l => l.addEventListener("click", closeMenu));
    if(overlay) overlay.addEventListener("click", (e) => {
        if(e.target === overlay) closeMenu();
    });

    // Auth-aware logic — reads from localStorage directly, no api.js dependency
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
                userZone.classList.add('flex');
                // Ensure the dashboard button is also visible and links correctly
                const dashBtn = document.getElementById('nav-dash-v2');
                if (dashBtn) dashBtn.style.display = 'inline-block';
            }
            const usernameEl = document.getElementById('nav-username-home');
            if (usernameEl) usernameEl.innerText = `@${user.username || user.email || 'user'}`;
            const heroCta = document.getElementById('hero-cta');
            if (heroCta) { 
                heroCta.href = 'submit.html'; 
                heroCta.innerText = 'GO TO DASHBOARD'; 
            }
        } else {
            if (launchBtn) launchBtn.style.display = 'inline-block';
            if (userZone) { userZone.classList.add('hidden'); userZone.classList.remove('flex'); }
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

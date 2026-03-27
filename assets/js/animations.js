// Force scroll to top on reload to prevent animation glitches
if (history.scrollRestoration) {
    history.scrollRestoration = 'manual';
}
window.scrollTo(0, 0);

// Global UI Animations & Interactions
document.addEventListener('DOMContentLoaded', () => {
    // 1. Global Back Button Injection (except on index or admin)
    const p = window.location.pathname;
    const isIndex = p.endsWith('index.html') || p === '/' || p.endsWith('/');
    const isAdmin = p.includes('/admin');
    
    if (!isIndex && !isAdmin) {
        const backBtn = document.createElement('a');
        backBtn.href = "javascript:history.length > 1 ? history.back() : location.href='index.html'";
        backBtn.className = "fixed top-[18px] left-[18px] md:top-[28px] md:left-[28px] z-[999] w-[40px] h-[40px] md:w-[48px] md:h-[48px] rounded-full border border-[rgba(255,255,255,0.08)] bg-[rgba(12,12,15,0.6)] backdrop-blur-xl flex items-center justify-center text-white opacity-50 hover:opacity-100 hover:bg-[rgba(255,255,255,0.05)] transition-all duration-300 group shadow-lg cursor-pointer";
        backBtn.innerHTML = '<span class="material-symbols-outlined text-[16px] md:text-[18px] group-hover:-translate-x-[2px] transition-transform duration-300 pointer-events-none">arrow_back</span>';
        
        if (!document.querySelector('link[href*="Material+Symbols"]')) {
            const fontLink = document.createElement('link');
            fontLink.rel = 'stylesheet';
            fontLink.href = 'https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap';
            document.head.appendChild(fontLink);
        }
        document.body.appendChild(backBtn);
    }

    // 2. Custom Cursor Logic
    const cursor = document.getElementById('cursor');
    if (cursor) {
        document.addEventListener('mousemove', (e) => {
            gsap.to(cursor, {
                x: e.clientX,
                y: e.clientY,
                duration: 0.1,
                ease: 'power2.out'
            });
        });

        const hoverables = 'a, button, .js-tilt, .asset-btn, .network-btn, input, textarea, .marquee-card';
        document.addEventListener('mouseover', (e) => {
            if (e.target.closest && e.target.closest(hoverables)) {
                cursor.classList.add('hover');
            }
        });
        document.addEventListener('mouseout', (e) => {
            if (e.target.closest && e.target.closest(hoverables)) {
                cursor.classList.remove('hover');
            }
        });
    }

    // 3. Card 3D Tilt Logic
    const cards = document.querySelectorAll('.js-tilt');
    const revealOptions = { threshold: 0.1, rootMargin: "0px 0px -50px 0px" };
    
    const revealOnScroll = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('revealed');
                observer.unobserve(entry.target);
            }
        });
    }, revealOptions);

    cards.forEach(card => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(30px)';
        card.style.transition = 'opacity 0.8s cubic-bezier(0.23, 1, 0.32, 1), transform 0.8s cubic-bezier(0.23, 1, 0.32, 1), box-shadow 0.4s, border-color 0.4s';
        revealOnScroll.observe(card);

        card.addEventListener('mousemove', e => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;
            const rotateX = ((y - centerY) / centerY) * -4;
            const rotateY = ((x - centerX) / centerX) * 4;
            card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;
            card.style.transition = 'none';
        });
        
        card.addEventListener('mouseleave', () => {
            card.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)';
            card.style.transition = 'transform 0.6s cubic-bezier(0.23, 1, 0.32, 1)';
        });
    });

    const style = document.createElement('style');
    style.textContent = `
        .js-tilt.revealed {
            opacity: 1 !important;
            transform: translateY(0) scale3d(1, 1, 1) !important;
        }
    `;
    document.head.appendChild(style);
});

// assets/js/scroll-stack.js

document.addEventListener('DOMContentLoaded', () => {
    const scroller = document.querySelector('.scroll-stack-scroller');
    if (!scroller) return;

    const cards = Array.from(document.querySelectorAll('.scroll-stack-card'));
    if (!cards.length) return;

    const endElement = document.querySelector('.scroll-stack-end');

    // Configuration - matches React version defaults
    const isMobile = window.innerWidth < 768;
    const itemDistance = isMobile ? 50 : 100;
    const itemScale = 0.03;
    const itemStackDistance = isMobile ? 25 : 40;
    const stackPosition = '15%'; // Pin 15% from the top
    const scaleEndPosition = isMobile ? '5%' : '10%';
    const baseScale = 0.85;
    const rotationAmount = 0;
    const blurAmount = 0; // Set to 0 strictly based on React default in this context

    cards.forEach((card, i) => {
        if (i < cards.length - 1) {
            card.style.marginBottom = `${itemDistance}px`;
        }
        card.style.willChange = 'transform, filter';
        card.style.transformOrigin = 'top center';
        card.style.backfaceVisibility = 'hidden';
    });

    const parsePercentage = (value, containerHeight) => {
        return (parseFloat(value) / 100) * containerHeight;
    };

    const calculateProgress = (scrollTop, start, end) => {
        if (scrollTop <= start) return 0;
        if (scrollTop >= end) return 1;
        return (scrollTop - start) / (end - start);
    };

    // Calculate absolute top offset ignoring transforms
    const getAbsoluteTop = (el) => {
        let top = 0;
        let p = el;
        while (p && p !== document.body) {
            top += p.offsetTop || 0;
            p = p.offsetParent;
        }
        return top;
    };

    let originalOffsets = [];
    let endElementOrigTop = 0;

    const cacheOffsets = () => {
        // Temporarily clear transforms to let elements sit naturally
        const oldTransforms = cards.map(c => c.style.transform);
        cards.forEach(c => c.style.transform = 'none');
        
        // Force reflow
        void document.body.offsetHeight;

        originalOffsets = cards.map(c => getAbsoluteTop(c));
        
        if (endElement) {
            endElementOrigTop = getAbsoluteTop(endElement);
        } else {
            // Fallback if no end element exists
            const lastCard = cards[cards.length - 1];
            endElementOrigTop = getAbsoluteTop(lastCard) + lastCard.offsetHeight + window.innerHeight;
        }

        // Restore transforms
        cards.forEach((c, i) => c.style.transform = oldTransforms[i]);
    };

    let isUpdating = false;
    const lastTransforms = new Map();

    const updateCardTransforms = () => {
        if (isUpdating) return;
        isUpdating = true;

        const scrollTop = window.scrollY || window.pageYOffset;
        const containerHeight = window.innerHeight;
        
        const stackPositionPx = parsePercentage(stackPosition, containerHeight);
        const scaleEndPositionPx = parsePercentage(scaleEndPosition, containerHeight);

        cards.forEach((card, i) => {
            const cardTop = originalOffsets[i];
            
            // Where the trigger frame starts and scale starts
            const triggerStart = cardTop - stackPositionPx - itemStackDistance * i;
            const triggerEnd = cardTop - scaleEndPositionPx;
            
            const pinStart = triggerStart;
            // The pin ends when the endElement reaches mid screen roughly, same as React "pinEnd = endElementTop - containerHeight / 2"
            const pinEnd = endElementOrigTop - containerHeight / 2;

            const scaleProgress = calculateProgress(scrollTop, triggerStart, triggerEnd);
            const targetScale = baseScale + i * itemScale;
            const scale = 1 - scaleProgress * (1 - targetScale);
            const rotation = rotationAmount ? i * rotationAmount * scaleProgress : 0;

            let blur = 0;
            if (blurAmount) {
                let topCardIndex = 0;
                for (let j = 0; j < cards.length; j++) {
                    const jTriggerStart = originalOffsets[j] - stackPositionPx - itemStackDistance * j;
                    if (scrollTop >= jTriggerStart) {
                        topCardIndex = j;
                    }
                }
                if (i < topCardIndex) {
                    const depthInStack = topCardIndex - i;
                    blur = Math.max(0, depthInStack * blurAmount);
                }
            }

            let translateY = 0;
            const isPinned = scrollTop >= pinStart && scrollTop <= pinEnd;

            if (isPinned) {
                translateY = scrollTop - cardTop + stackPositionPx + itemStackDistance * i;
            } else if (scrollTop > pinEnd) {
                translateY = pinEnd - cardTop + stackPositionPx + itemStackDistance * i;
            } else {
                // scrollTop < pinStart
                translateY = 0;
            }

            // Smoothing out pixel values to avoid jitter
            const finalY = Math.round(translateY * 10) / 10;
            const finalScale = Math.round(scale * 1000) / 1000;
            const finalRot = Math.round(rotation * 100) / 100;
            const finalBlur = Math.round(blur * 10) / 10;

            const lastTransform = lastTransforms.get(i);
            const hasChanged = !lastTransform ||
                Math.abs(lastTransform.y - finalY) > 0.5 ||
                Math.abs(lastTransform.scale - finalScale) > 0.002 ||
                Math.abs(lastTransform.blur - finalBlur) > 0.1;

            if (hasChanged) {
                card.style.transform = `translate3d(0, ${finalY}px, 0) scale(${finalScale}) rotate(${finalRot}deg)`;
                card.style.filter = finalBlur > 0 ? `blur(${finalBlur}px)` : '';

                lastTransforms.set(i, {
                    y: finalY,
                    scale: finalScale,
                    rotation: finalRot,
                    blur: finalBlur
                });
            }
        });

        isUpdating = false;
    };

    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            cacheOffsets();
            updateCardTransforms();
        }, 100);
    });

    // Run cache once images/layouts are fully stable
    window.addEventListener('load', () => {
        cacheOffsets();
        updateCardTransforms();
    });

    // Run initial cache
    cacheOffsets();
    
    // Bind to Lenis OR window scroll seamlessly
    if (typeof Lenis !== 'undefined' && !window.lenisInstance) {
        window.lenisInstance = new Lenis({
            duration: 1.2,
            easing: t => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
            direction: 'vertical',
            gestureDirection: 'vertical',
            smooth: true,
            mouseMultiplier: 1,
            smoothTouch: false,
            touchMultiplier: 2,
        });

        window.lenisInstance.on('scroll', updateCardTransforms);
        
        function raf(time) {
            window.lenisInstance.raf(time);
            requestAnimationFrame(raf);
        }
        requestAnimationFrame(raf);
    } else {
        window.addEventListener('scroll', updateCardTransforms, { passive: true });
        // Use a continuous RAF loop to ensure high-fidelity checking even if scroll event is throttled
        function loop() {
            updateCardTransforms();
            requestAnimationFrame(loop);
        }
        requestAnimationFrame(loop);
    }

    updateCardTransforms();
});

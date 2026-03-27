class LogoLoop {
  constructor(element, options = {}) {
    this.container = element;
    this.track = this.container.querySelector('.logoloop__track');
    this.originalList = this.track.querySelector('.logoloop__list');
    
    this.options = {
      speed: options.speed ?? 120, // pixels per second
      direction: options.direction ?? 'left', // left, right, up, down
      gap: options.gap ?? 32,
      pauseOnHover: options.pauseOnHover ?? false,
      hoverSpeed: options.hoverSpeed,
      ...options
    };

    this.isVertical = this.options.direction === 'up' || this.options.direction === 'down';
    this.speedMultiplier = this.options.speed < 0 ? -1 : 1;
    this.directionMultiplier = (this.options.direction === 'up' || this.options.direction === 'left') ? 1 : -1;
    this.targetVelocity = Math.abs(this.options.speed) * this.directionMultiplier * this.speedMultiplier;
    
    this.offset = 0;
    this.velocity = 0;
    this.lastTimestamp = null;
    this.rafId = null;
    this.isHovered = false;
    this.seqSize = 0;
    
    this.init();
  }

  init() {
    this.container.style.setProperty('--logoloop-gap', `${this.options.gap}px`);
    
    if (this.options.pauseOnHover || this.options.hoverSpeed !== undefined) {
      this.container.addEventListener('mouseenter', () => this.isHovered = true);
      this.container.addEventListener('mouseleave', () => this.isHovered = false);
    }

    this.updateDimensions();
    
    window.addEventListener('resize', () => {
      this.updateDimensions();
    });

    const images = this.originalList.querySelectorAll('img');
    let loadedCount = 0;
    if (images.length === 0) this.startAnimation();
    else {
      images.forEach(img => {
        if (img.complete) {
          loadedCount++;
          if (loadedCount === images.length) this.updateDimensions();
        } else {
          img.addEventListener('load', () => {
            loadedCount++;
            if (loadedCount === images.length) this.updateDimensions();
          }, { once: true });
        }
      });
      this.startAnimation();
    }
  }

  updateDimensions() {
    const listRect = this.originalList.getBoundingClientRect();
    this.seqSize = this.isVertical ? listRect.height : listRect.width;
    
    if (this.seqSize === 0) {
      // Retry in 100ms if size is 0 (handles slow layout/component injection)
      setTimeout(() => this.updateDimensions(), 100);
      return;
    }
    
    const viewportSize = this.isVertical ? this.container.clientHeight : this.container.clientWidth;
    // adding +2 copies headroom logic like the react class
    const copiesNeeded = Math.ceil(viewportSize / this.seqSize) + 2;

    const currentLists = this.track.querySelectorAll('.logoloop__list');
    const currentCopies = currentLists.length;
    
    if (copiesNeeded > currentCopies) {
      for (let i = currentCopies; i < copiesNeeded; i++) {
        const clone = this.originalList.cloneNode(true);
        clone.setAttribute('aria-hidden', 'true');
        this.track.appendChild(clone);
      }
    }
  }

  startAnimation() {
    if (this.rafId) return;
    
    const animate = (timestamp) => {
      if (!this.lastTimestamp) this.lastTimestamp = timestamp;
      const deltaTime = Math.max(0, timestamp - this.lastTimestamp) / 1000;
      this.lastTimestamp = timestamp;

      let target = this.targetVelocity;
      if (this.isHovered) {
        if (this.options.hoverSpeed !== undefined) {
          target = (this.options.hoverSpeed * this.directionMultiplier * this.speedMultiplier);
        } else if (this.options.pauseOnHover) {
          target = 0;
        }
      }

      // smooth dampening like SMOOTH_TAU = 0.25
      this.velocity += (target - this.velocity) * (1 - Math.exp(-deltaTime / 0.25));

      if (this.seqSize > 0) {
        this.offset += this.velocity * deltaTime;
        this.offset = ((this.offset % this.seqSize) + this.seqSize) % this.seqSize;

        const transform = this.isVertical 
          ? `translate3d(0, ${-this.offset}px, 0)` 
          : `translate3d(${-this.offset}px, 0, 0)`;
        this.track.style.transform = transform;
      }

      this.rafId = requestAnimationFrame(animate);
    };
    this.rafId = requestAnimationFrame(animate);
  }
}
window.LogoLoop = LogoLoop;

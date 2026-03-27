class AnimatedList {
  constructor(container) {
    this.container = container;
    this.list = container.querySelector('.scroll-list');
    this.items = Array.from(this.list.querySelectorAll('.animated-item'));
    this.topGradient = container.querySelector('.top-gradient');
    this.bottomGradient = container.querySelector('.bottom-gradient');
    
    this.selectedIndex = -1;
    this.keyboardNav = false;
    
    this.init();
  }

  init() {
    this.list.addEventListener('scroll', () => this.handleScroll());
    this.handleScroll();

    // Setup intersection observer using threshold
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('in-view');
        } else {
          entry.target.classList.remove('in-view');
        }
      });
    }, { root: this.list, threshold: 0.1, rootMargin: "-10% 0px -10% 0px" });

    this.items.forEach((item, index) => {
      item.dataset.index = index;
      observer.observe(item);

      item.addEventListener('mouseenter', () => this.selectItem(index));
      item.addEventListener('click', () => this.selectItem(index));
    });

    window.addEventListener('keydown', (e) => this.handleKeyDown(e));
  }

  selectItem(index) {
    if (this.selectedIndex !== -1 && this.items[this.selectedIndex]) {
      this.items[this.selectedIndex].classList.remove('selected');
    }
    this.selectedIndex = index;
    if (this.items[index]) {
      this.items[index].classList.add('selected');
    }
  }

  handleScroll() {
    const { scrollTop, scrollHeight, clientHeight } = this.list;
    if (this.topGradient) {
      this.topGradient.style.opacity = Math.min(scrollTop / 50, 1);
    }
    if (this.bottomGradient) {
      const bottomDistance = scrollHeight - (scrollTop + clientHeight);
      this.bottomGradient.style.opacity = scrollHeight <= clientHeight ? 0 : Math.min(bottomDistance / 50, 1);
    }
  }

  handleKeyDown(e) {
    // Only intercept if we are actively interacting or looking at it (optional), 
    // but the React snippet explicitly binds to window.
    if (!['ArrowDown', 'ArrowUp', 'Tab'].includes(e.key)) return;
    
    // Prevent default scroll
    e.preventDefault();

    this.keyboardNav = true;
    if (e.key === 'ArrowDown' || (e.key === 'Tab' && !e.shiftKey)) {
      this.selectItem(Math.min(this.selectedIndex + 1, this.items.length - 1));
      this.scrollToSelected();
    } else if (e.key === 'ArrowUp' || (e.key === 'Tab' && e.shiftKey)) {
      this.selectItem(Math.max(this.selectedIndex - 1, 0));
      this.scrollToSelected();
    }
  }

  scrollToSelected() {
    if (this.selectedIndex < 0) return;
    const selectedItem = this.items[this.selectedIndex];
    if (!selectedItem) return;

    const extraMargin = 100;
    const containerScrollTop = this.list.scrollTop;
    const containerHeight = this.list.clientHeight;
    
    // Get item top relative to list scroll container
    const itemOffsetTop = selectedItem.offsetTop;
    const itemBottom = itemOffsetTop + selectedItem.offsetHeight;

    if (itemOffsetTop < containerScrollTop + extraMargin) {
      this.list.scrollTo({ top: itemOffsetTop - extraMargin, behavior: 'smooth' });
    } else if (itemBottom > containerScrollTop + containerHeight - extraMargin) {
      this.list.scrollTo({ top: itemBottom - containerHeight + extraMargin, behavior: 'smooth' });
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const container = document.querySelector('.scroll-list-container');
  if (container) {
    new AnimatedList(container);
  }
});

/**
 * BITVORA EXCHANGE — Live Transaction Counter Ticker
 * Deterministic synchronized randomized value.
 */

class LiveCounter {
    constructor(elementId, options = {}) {
        this.container = document.getElementById(elementId);
        this.currentValue = 0;
        this.fontSize = options.fontSize || 64;
        this.height = this.fontSize + 10;
        this.digitStyle = options.digitStyle || '';
        
        this.init();
    }

    async init() {
        await this.updateValue();
        
        // Update every 10 minutes (600,000 ms)
        setInterval(() => this.updateValue(), 600000);
    }

    async updateValue() {
        try {
            const baseUrl = (typeof BITVORA_CONFIG !== 'undefined' && BITVORA_CONFIG.API_BASE_URL) ? BITVORA_CONFIG.API_BASE_URL : '';
            const response = await fetch(`${baseUrl}/assets/live-counter`);
            const data = await response.json();
            const newValue = data.count || 0;
            
            if (newValue !== this.currentValue) {
                this.render(newValue);
                this.currentValue = newValue;
            }
        } catch (error) {
            console.error('Counter fetch error:', error);
        }
    }

    render(value) {
        const valueStr = value.toLocaleString('en-US'); // Adds commas
        const characters = valueStr.split('');
        
        // Comparison of current children to see what needs to change
        this.container.innerHTML = '';
        
        const wrapper = document.createElement('div');
        wrapper.className = 'counter-container relative';
        wrapper.style.height = `${this.height}px`;
        wrapper.style.fontSize = `${this.fontSize}px`;
        
        characters.forEach((char, index) => {
            const digitEl = document.createElement('div');
            digitEl.className = 'inline-block overflow-hidden relative';
            digitEl.style.height = `${this.height}px`;
            
            if (/\d/.test(char)) {
                // It's a digit, create a column of 0-9
                const column = document.createElement('div');
                column.className = 'counter-digit-container flex flex-col items-center';
                // Transition will happen when we set transform
                
                for (let i = 0; i <= 9; i++) {
                    const num = document.createElement('div');
                    num.className = 'counter-digit font-headline text-white';
                    num.style.height = `${this.height}px`;
                    num.innerText = i;
                    column.appendChild(num);
                }
                
                // Set final position
                const targetDigit = parseInt(char);
                column.style.transform = `translateY(-${targetDigit * this.height}px)`;
                digitEl.appendChild(column);
            } else {
                // It's a separator (comma)
                const sep = document.createElement('div');
                sep.className = 'counter-separator font-headline text-white/40 px-1';
                sep.style.height = `${this.height}px`;
                sep.innerText = char;
                digitEl.appendChild(sep);
            }
            
            wrapper.appendChild(digitEl);
        });

        // Add gradient overlay for the premium look
        const overlay = document.createElement('div');
        overlay.className = 'counter-gradient-overlay';
        wrapper.appendChild(overlay);

        this.container.appendChild(wrapper);
    }
}

// Global initialization
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('live-transaction-counter')) {
        new LiveCounter('live-transaction-counter', {
            fontSize: window.innerWidth < 768 ? 48 : 84
        });
    }
});

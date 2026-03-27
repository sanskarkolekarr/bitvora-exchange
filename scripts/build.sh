#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════
# BITVORA EXCHANGE — Frontend Build Script
# Concatenates and minifies JS/CSS for production.
# Requires: npm install -g terser cssnano-cli
# ════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

JS_DIR="$PROJECT_ROOT/assets/js"
CSS_DIR="$PROJECT_ROOT/assets/css"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${GREEN}[✓]${NC} $1"; }
step() { echo -e "${CYAN}[→]${NC} $1"; }

echo ""
echo -e "${CYAN}════════════════════════════════════════${NC}"
echo -e "${CYAN}  BITVORA EXCHANGE — Frontend Build${NC}"
echo -e "${CYAN}════════════════════════════════════════${NC}"
echo ""

# ── Check build tools ────────────────────────────────────────
if ! command -v terser &>/dev/null; then
    echo "Installing terser..."
    npm install -g terser
fi

if ! command -v cssnano &>/dev/null; then
    echo "Installing cssnano-cli..."
    npm install -g cssnano-cli
fi

# ── JavaScript Bundle ────────────────────────────────────────
step "Building JavaScript bundle..."

# Dependency order: utilities first, then page-specific scripts
JS_FILES=(
    "$JS_DIR/api.js"
    "$JS_DIR/platform.js"
    "$JS_DIR/animations.js"
    "$JS_DIR/counter.js"
    "$JS_DIR/animatedlist.js"
    "$JS_DIR/logoloop.js"
    "$JS_DIR/metallic-paint.js"
    "$JS_DIR/soft-aurora.js"
    "$JS_DIR/profile-card.js"
    "$JS_DIR/txid-validator.js"
    "$JS_DIR/chatbot-ui.js"
)

# Filter to only existing files
EXISTING_JS=()
for f in "${JS_FILES[@]}"; do
    if [ -f "$f" ]; then
        EXISTING_JS+=("$f")
    fi
done

# Add any JS files not in the ordered list
for f in "$JS_DIR"/*.js; do
    if [ -f "$f" ] && [[ ! " ${EXISTING_JS[*]} " =~ " $f " ]] && [[ "$f" != *"bundle.min.js"* ]]; then
        EXISTING_JS+=("$f")
    fi
done

if [ ${#EXISTING_JS[@]} -gt 0 ]; then
    # Concatenate all JS files
    cat "${EXISTING_JS[@]}" > "$JS_DIR/bundle.js"
    # Minify
    terser "$JS_DIR/bundle.js" \
        --compress drop_console=false,passes=2 \
        --mangle \
        --output "$JS_DIR/bundle.min.js"
    rm "$JS_DIR/bundle.js"

    ORIG_SIZE=$(stat -c %s "${EXISTING_JS[@]}" 2>/dev/null | paste -sd+ | bc 2>/dev/null || echo "?")
    MIN_SIZE=$(stat -c %s "$JS_DIR/bundle.min.js" 2>/dev/null || echo "?")
    log "JavaScript: ${#EXISTING_JS[@]} files → bundle.min.js (${MIN_SIZE} bytes)"
else
    log "No JavaScript files found"
fi

# ── CSS Bundle ───────────────────────────────────────────────
step "Building CSS bundle..."

CSS_FILES=(
    "$CSS_DIR/styles.css"
    "$CSS_DIR/animatedlist.css"
    "$CSS_DIR/counter.css"
    "$CSS_DIR/logoloop.css"
    "$CSS_DIR/profile-card.css"
)

# Filter to only existing files
EXISTING_CSS=()
for f in "${CSS_FILES[@]}"; do
    if [ -f "$f" ]; then
        EXISTING_CSS+=("$f")
    fi
done

# Add any CSS files not in the ordered list
for f in "$CSS_DIR"/*.css; do
    if [ -f "$f" ] && [[ ! " ${EXISTING_CSS[*]} " =~ " $f " ]] && [[ "$f" != *"bundle.min.css"* ]]; then
        EXISTING_CSS+=("$f")
    fi
done

if [ ${#EXISTING_CSS[@]} -gt 0 ]; then
    # Concatenate all CSS files
    cat "${EXISTING_CSS[@]}" > "$CSS_DIR/bundle.css"
    # Minify
    cssnano "$CSS_DIR/bundle.css" "$CSS_DIR/bundle.min.css" 2>/dev/null || \
        cp "$CSS_DIR/bundle.css" "$CSS_DIR/bundle.min.css"
    rm "$CSS_DIR/bundle.css"

    MIN_SIZE=$(stat -c %s "$CSS_DIR/bundle.min.css" 2>/dev/null || echo "?")
    log "CSS: ${#EXISTING_CSS[@]} files → bundle.min.css (${MIN_SIZE} bytes)"
else
    log "No CSS files found"
fi

echo ""
log "Build complete!"
echo ""

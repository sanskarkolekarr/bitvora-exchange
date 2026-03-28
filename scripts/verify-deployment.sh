#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════
# BITVORA EXCHANGE — Production Deployment Verification
# Run on the VPS after 'docker compose up -d' to verify all
# services, routing, and domain accessibility.
# Usage: bash scripts/verify-deployment.sh
# ════════════════════════════════════════════════════════════

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() { echo -e "${GREEN}  ✓ $1${NC}"; ((PASS++)); }
fail() { echo -e "${RED}  ✗ $1${NC}"; ((FAIL++)); }
warn() { echo -e "${YELLOW}  ! $1${NC}"; ((WARN++)); }

header() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════${NC}"
}

# ════════════════════════════════════════════════════════════
header "1/8 — Docker Services"
# ════════════════════════════════════════════════════════════

REQUIRED_CONTAINERS=("bitvora-backend" "bitvora-redis" "bitvora-nginx" "bitvora-worker-verifier" "bitvora-cloudflared")

for container in "${REQUIRED_CONTAINERS[@]}"; do
    if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        STATUS=$(docker inspect --format='{{.State.Status}}' "$container" 2>/dev/null)
        if [ "$STATUS" = "running" ]; then
            pass "$container is running"
        else
            fail "$container exists but status is: $STATUS"
        fi
    else
        fail "$container is NOT running"
    fi
done

# ════════════════════════════════════════════════════════════
header "2/8 — Backend Health (localhost:8000)"
# ════════════════════════════════════════════════════════════

HEALTH=$(curl -sf http://localhost:8000/health 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -q '"status"'; then
    pass "Backend /health responded: $HEALTH"
else
    fail "Backend /health not responding (got: $HEALTH)"
fi

# ════════════════════════════════════════════════════════════
header "3/8 — Nginx Frontend (localhost:80)"
# ════════════════════════════════════════════════════════════

NGINX_RESP=$(curl -sf -o /dev/null -w "%{http_code}" http://localhost 2>/dev/null || echo "000")
if [ "$NGINX_RESP" = "200" ]; then
    pass "Nginx returned HTTP 200 on port 80"
else
    fail "Nginx returned HTTP $NGINX_RESP on port 80"
fi

# Check HTML content
NGINX_HTML=$(curl -sf http://localhost 2>/dev/null || echo "")
if echo "$NGINX_HTML" | grep -qi "bitvora\|exchange\|html"; then
    pass "Nginx serves HTML content"
else
    fail "Nginx response does not contain expected HTML"
fi

# ════════════════════════════════════════════════════════════
header "4/8 — Redis Connectivity"
# ════════════════════════════════════════════════════════════

REDIS_PING=$(docker exec bitvora-redis redis-cli ping 2>/dev/null || echo "FAILED")
if [ "$REDIS_PING" = "PONG" ]; then
    pass "Redis is healthy (PONG)"
else
    fail "Redis ping failed (got: $REDIS_PING)"
fi

# ════════════════════════════════════════════════════════════
header "5/8 — Cloudflare Tunnel"
# ════════════════════════════════════════════════════════════

CF_LOGS=$(docker logs bitvora-cloudflared --tail 5 2>&1 || echo "FAILED")
if echo "$CF_LOGS" | grep -qi "registered\|connected\|serving"; then
    pass "Cloudflared tunnel appears connected"
elif echo "$CF_LOGS" | grep -qi "error\|failed\|unauthorized"; then
    fail "Cloudflared shows errors: $(echo "$CF_LOGS" | tail -1)"
else
    warn "Cloudflared status unclear — check: docker logs bitvora-cloudflared"
fi

# ════════════════════════════════════════════════════════════
header "6/8 — Domain DNS Resolution"
# ════════════════════════════════════════════════════════════

for domain in "bitvora.in" "api.bitvora.in" "www.bitvora.in"; do
    if host "$domain" &>/dev/null || nslookup "$domain" &>/dev/null; then
        pass "$domain resolves"
    else
        fail "$domain does NOT resolve — add DNS route: cloudflared tunnel route dns bitvora-tunnel $domain"
    fi
done

# ════════════════════════════════════════════════════════════
header "7/8 — External Domain Access"
# ════════════════════════════════════════════════════════════

# Test API endpoint
API_EXT=$(curl -sf --max-time 10 https://api.bitvora.in/health 2>/dev/null || echo "FAILED")
if echo "$API_EXT" | grep -q '"status"'; then
    pass "https://api.bitvora.in/health is accessible: $API_EXT"
else
    fail "https://api.bitvora.in/health not accessible (got: $API_EXT)"
fi

# Test Frontend
FRONT_EXT=$(curl -sf -o /dev/null --max-time 10 -w "%{http_code}" https://bitvora.in 2>/dev/null || echo "000")
if [ "$FRONT_EXT" = "200" ]; then
    pass "https://bitvora.in returns HTTP 200"
else
    fail "https://bitvora.in returned HTTP $FRONT_EXT"
fi

# ════════════════════════════════════════════════════════════
header "8/8 — Frontend Config Check"
# ════════════════════════════════════════════════════════════

CONFIG_FILE="/var/www/bitvoraexchange/pages/config.js"
if [ -f "$CONFIG_FILE" ]; then
    if grep -q "api.bitvora.in" "$CONFIG_FILE"; then
        pass "Frontend config points to https://api.bitvora.in"
    else
        fail "Frontend config does NOT point to api.bitvora.in — update config.js"
    fi
else
    warn "Frontend config not found at $CONFIG_FILE — run 'make build' to sync"
fi

# ════════════════════════════════════════════════════════════
header "RESULTS"
# ════════════════════════════════════════════════════════════

echo ""
echo -e "  ${GREEN}Passed: $PASS${NC}"
echo -e "  ${RED}Failed: $FAIL${NC}"
echo -e "  ${YELLOW}Warnings: $WARN${NC}"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}══════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✓ ALL CHECKS PASSED — System is PRODUCTION-READY${NC}"
    echo -e "${GREEN}══════════════════════════════════════════════${NC}"
else
    echo -e "${RED}══════════════════════════════════════════════${NC}"
    echo -e "${RED}  ✗ $FAIL CHECK(S) FAILED — Fix issues above${NC}"
    echo -e "${RED}══════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${YELLOW}Common fixes:${NC}"
    echo "  • Restart services:  docker compose restart"
    echo "  • Check logs:        docker compose logs -f [service]"
    echo "  • DNS routes:        cloudflared tunnel route dns bitvora-tunnel <domain>"
    echo "  • Rebuild:           docker compose up -d --build"
    echo "  • Sync frontend:     make build"
fi
echo ""

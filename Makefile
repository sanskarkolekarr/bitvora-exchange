# ════════════════════════════════════════════════════════════
# BITVORA EXCHANGE — Makefile
# Developer commands for setup, build, deploy, and operations.
# ════════════════════════════════════════════════════════════

.PHONY: setup build deploy restart logs status health clean

# ── Setup: Run server setup script ───────────────────────────
setup:
	@echo "Running server setup..."
	bash setup.sh

# ── Build: Minify frontend assets ────────────────────────────
build:
	@echo "Building frontend assets..."
	bash scripts/build.sh
	@echo "Syncing to web root..."
	rsync -avz --exclude='backend/' --exclude='.git/' --exclude='node_modules/' \
		--exclude='.venv/' --exclude='__pycache__/' --exclude='*.pyc' \
		./ /var/www/bitvoraexchange/
	@echo "Build complete!"

# ── Deploy: Full deployment (build + restart services) ───────
deploy:
	@echo "Deploying BITVORA Exchange..."
	docker compose pull
	docker compose up -d --build
	$(MAKE) build
	@echo "Waiting for health check..."
	@sleep 10
	@curl -sf http://localhost:8000/health | python3 -m json.tool || echo "Health check failed!"
	@echo "Deployment complete!"

# ── Restart: Restart core services only ──────────────────────
restart:
	docker compose restart backend worker-verifier

# ── Restart All: Restart everything ──────────────────────────
restart-all:
	docker compose restart

# ── Logs: Tail all service logs ──────────────────────────────
logs:
	docker compose logs -f --tail=100

# ── Logs for specific services ───────────────────────────────
logs-api:
	docker compose logs -f --tail=100 backend

logs-workers:
	docker compose logs -f --tail=100 worker-verifier

logs-redis:
	docker compose logs -f --tail=50 redis

# ── Status: Show service status + health ─────────────────────
status:
	@echo ""
	@echo "═══ Service Status ═══"
	docker compose ps
	@echo ""
	@echo "═══ Health Check ═══"
	@curl -sf http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "API not responding"
	@echo ""
	@echo "═══ Redis Queue Depth ═══"
	@docker compose exec -T redis redis-cli LLEN bitvora:verify:queue 2>/dev/null || echo "Redis not available"

# ── Health: Quick health check ───────────────────────────────
health:
	@curl -sf http://localhost:8000/health | python3 -m json.tool

# ── Clean: Remove built artifacts ────────────────────────────
clean:
	rm -f assets/js/bundle.min.js assets/js/bundle.js
	rm -f assets/css/bundle.min.css assets/css/bundle.css
	@echo "Build artifacts cleaned"

# ── Down: Stop all services ─────────────────────────────────
down:
	docker compose down

# ── Up: Start all services ──────────────────────────────────
up:
	docker compose up -d
	@echo "Waiting for services..."
	@sleep 15
	$(MAKE) status

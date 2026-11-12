.PHONY: dev test lint seed backend-test frontend-check compose-up compose-down

# Local development (backend on SQLite, frontend via Vite)
dev:
	cd apps/backend && DJANGO_SETTINGS_MODULE=config.settings.development uv run python manage.py runserver

seed:
	cd apps/backend && DJANGO_SETTINGS_MODULE=config.settings.development uv run python manage.py seed_networks_assets

backend-test:
	cd apps/backend && uv run pytest

lint:
	cd apps/backend && uv run ruff check .

frontend-check:
	cd apps/dashboard && npm run typecheck && npm test && npm run build

test: backend-test frontend-check

compose-up:
	docker compose up --build

compose-down:
	docker compose down

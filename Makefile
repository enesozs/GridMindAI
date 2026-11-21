# GridMind — common commands. Requires uv (Python) and Node 20+.
.PHONY: setup test lint ingest panel features backtest export web-build web-dev screenshots live all

setup:            ## install Python and web dependencies
	uv sync
	cd apps/web && npm ci

test:             ## Python unit/integration tests
	uv run pytest -q

lint:             ## Python + web lint and type checks
	uv run ruff check src tests
	cd apps/web && npm run lint && npx tsc --noEmit

ingest:           ## incremental SMARD + Open-Meteo (48-h-lead GFS) ingest (network, a few minutes)
	uv run gridmind ingest-smard
	uv run gridmind ingest-openmeteo

panel:            ## hourly panel, calendar, quality report
	uv run gridmind build-panel
	uv run gridmind quality-report

features:         ## point-in-time feature matrix
	uv run gridmind build-features

backtest:         ## rolling-origin backtest + load benchmark report
	uv run gridmind backtest

export:           ## JSON artifacts for the static site
	uv run gridmind export

web-build:        ## static site into apps/web/out
	cd apps/web && npm run build

web-dev:
	cd apps/web && npm run dev

screenshots:      ## screenshots of the built site (light/dark, desktop/mobile)
	cd apps/web && node scripts/screenshots.mjs ../../docs/screenshots

live:             ## issue tomorrow's forecast (append-only) and refresh the site data
	uv run gridmind live

all: ingest panel features backtest export web-build

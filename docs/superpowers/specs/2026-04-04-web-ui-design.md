# mev-kit Web UI — Design Spec

## Overview

A professional, data-dense web dashboard for mev-kit targeting MEV strategy developers, trading desks, quant firms, and MEV searchers. Launched via `mev-kit ui`, it provides full pipeline control (start/stop/hot-reload params), real-time monitoring, backtesting, analysis, data management, and educational content — replacing the CLI for day-to-day use.

## Target Users

- MEV searchers iterating on strategies
- Quant desks running paper/live pipelines
- Strategy developers backtesting and analyzing results
- Newcomers learning Solana MEV concepts

## Tech Stack

### Backend
- **FastAPI** — async REST + WebSocket API server
- **Pydantic** — request/response validation (already in codebase)
- **aiosqlite** — existing SQLite access for results
- **Existing mev-kit core** — Pipeline, Adapters, Detectors, Sinks used directly

### Frontend
- **React 18 + TypeScript** — SPA, pre-built and bundled as static files served by FastAPI
- **react-grid-layout** — draggable/resizable dashboard panels
- **Lightweight Charts** (by TradingView) — P&L curves, price charts
- **Recharts** — histograms, heatmaps, bar charts
- **Tailwind CSS** — utility-first styling for Dense Pro aesthetic

### Bundling
- Frontend is pre-built (`npm run build`) and output is placed in `src/mev_kit/ui/static/`
- FastAPI serves static files at `/*`, API at `/api/*`, WebSocket at `/ws/*`
- End users never touch Node.js — `pip install mev-kit` includes the built frontend
- Dev workflow: `cd ui && npm run dev` for hot-reload during frontend development

## Architecture

```
mev-kit ui --port 8080
    │
    ▼
┌──────────────────────────────────────────────────┐
│  FastAPI Server (src/mev_kit/ui/server.py)       │
│                                                  │
│  REST API                                        │
│    POST /api/pipeline/start    (mode, config)    │
│    POST /api/pipeline/stop                       │
│    GET  /api/pipeline/status                     │
│    PATCH /api/pipeline/params  (hot-reload)      │
│    GET  /api/config            (load TOML)       │
│    PUT  /api/config            (save TOML)       │
│    GET  /api/config/profiles   (list configs)    │
│    POST /api/backtest/start    (data, config)    │
│    GET  /api/backtest/status                     │
│    GET  /api/analysis/:db      (summary stats)   │
│    GET  /api/analysis/:db/trades (paginated)     │
│    GET  /api/data/files        (list Parquet)    │
│    GET  /api/data/files/:name/preview            │
│    DELETE /api/data/files/:name                  │
│    POST /api/data/fetch/helius                   │
│    POST /api/data/fetch/binance                  │
│    GET  /api/data/fetch/status                   │
│    GET  /api/docs/guides       (list guides)     │
│    GET  /api/docs/guides/:slug (guide content)   │
│                                                  │
│  WebSocket                                       │
│    /ws/pipeline   metrics + opportunities @ 1Hz  │
│    /ws/logs       structlog stream               │
│    /ws/backtest   backtest progress stream        │
│                                                  │
│  Static Files                                    │
│    /*             React SPA (index.html + assets) │
│                                                  │
│  Backend Services                                │
│    PipelineManager  — owns running Pipeline ref  │
│    ConfigManager    — TOML read/write/validate   │
│    DataManager      — Parquet CRUD + fetch jobs  │
│    BacktestRunner   — async backtest execution   │
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────┐
│  Existing mev-kit core (unchanged)               │
│  Pipeline, IngestAdapter, Detector, Simulator,   │
│  Sink, Models, Config                            │
└──────────────────────────────────────────────────┘
```

### PipelineManager

Singleton that manages the running pipeline instance:

- `start(mode, config)` — instantiates adapters, detector, simulator, sink based on config. Launches `pipeline.run()` as a background asyncio task.
- `stop()` — calls `pipeline.stop()`, awaits task completion.
- `status()` — returns current state: idle/running/stopping, mode, elapsed time, all pipeline metrics.
- `hot_reload(params)` — patches live detector config values (`min_spread_bps`, `position_size_sol`, `fee_bps`, `max_daily_loss_sol`) on the running instance. No restart.
- `subscribe()` — async generator yielding metric snapshots + opportunity events for the WebSocket.

### WebSocket Protocol

`/ws/pipeline` sends JSON messages at ~1Hz:

```json
{
  "type": "metrics",
  "data": {
    "updates_processed": 8412,
    "opportunities_detected": 47,
    "opportunities_executed": 39,
    "total_profit_sol": 2.847,
    "consecutive_misses": 0,
    "detection_rate": 0.56,
    "elapsed_seconds": 3847.2,
    "dex_price": 148.23,
    "cex_price": 148.91,
    "current_spread_bps": 45.8,
    "queue_size": 23
  }
}
```

```json
{
  "type": "opportunity",
  "data": {
    "id": "uuid",
    "direction": "BUY_DEX",
    "spread_bps": 47.2,
    "estimated_profit_sol": 0.0034,
    "simulated_profit_sol": 0.0029,
    "sim_latency_ms": 38,
    "success": true,
    "timestamp": "2026-04-04T12:04:32Z"
  }
}
```

`/ws/logs` sends structured log entries:

```json
{
  "type": "log",
  "level": "info",
  "event": "pipeline.execution_success",
  "data": {"profit_sol": 0.003, "mode": "paper"},
  "timestamp": "2026-04-04T12:04:32Z"
}
```

## Visual Design

### Aesthetic: Dense Pro

- Dark background: `#1a1a2e` (main), `#16213e` (panels), `#12122a` (sidebar)
- Borders: `#2a2a4a` (subtle panel separation)
- Text: `#e0e0e0` (primary), `#7f8ea3` (labels/secondary)
- Accent green: `#00e676` (profit, success)
- Accent red: `#ef5350` (loss, failure)
- Accent amber: `#ffab00` (warnings, spread values)
- Accent indigo: `#6366f1` (interactive elements, editable params)
- Font: Inter for UI, SF Mono/monospace for data values
- Spacing: Minimal — 2px panel gaps, 8px internal padding
- Every pixel earns its place. No decorative elements.

### Navigation: Icon Sidebar

- 52px wide, dark background (`#12122a`)
- Top: mev-kit logo mark
- Icons for 6 pages: Dashboard, Backtest, Config, Analysis, Data, Learn
- Active page: highlighted background (`#252547`)
- Pipeline status indicator always visible at the bottom of sidebar (green dot = running, idle = gray)

## Pages

### 1. Dashboard

The primary view while a pipeline is running. Uses `react-grid-layout` for configurable panel arrangement.

**Default layout (Layout A):**
- Row 1: Metrics strip (always pinned, not draggable) — P&L, Win%, Opp/min, Updates, Queue, Latency
- Row 2: P&L Curve (2/3 width) + Spread Distribution histogram (1/3 width)
- Row 3: Live Opportunity Feed table (2/3 width) + Prices/Hot Params sidebar (1/3 width)

**Available panels (draggable/resizable):**

| Panel | Description | Update frequency |
|-------|-------------|-----------------|
| Metrics Strip | Key counters: P&L, win rate, opp/min, updates, queue, latency | 1Hz via WebSocket |
| P&L Curve | Cumulative profit line chart (TradingView Lightweight Charts) | On each execution |
| Spread Distribution | Histogram of spread_bps across opportunities | On each detection |
| Live Opportunity Feed | Scrolling table: time, direction, spread, est P&L, sim P&L, latency, status | On each execution |
| Live Prices | DEX price, CEX price, current spread in bps | 1Hz via WebSocket |
| Hot Params | Inline-editable strategy params. Edit button opens inline inputs, "Apply" patches live pipeline | User-triggered |
| Log Stream | Scrolling structlog output from /ws/logs | Real-time |
| Pipeline Controls | Mode selector (backtest/paper/live), Start/Stop buttons, config profile picker | User-triggered |

**Panel layout persistence:** Saved to localStorage keyed by user. Reset to default button available.

**Pipeline controls at top of page:**
- Mode badge: green "PAPER RUNNING" / yellow "BACKTEST" / red "LIVE" / gray "IDLE"
- Stop button (red, requires confirmation for live mode)
- When idle: Start button with mode selector dropdown

### 2. Backtest

Streamlined backtest workflow: configure → run → analyze.

**Top section: Configuration form**
- Data source: dropdown of Parquet files from `data/` directory (fetched from `/api/data/files`), or file upload
- Strategy params: min_spread_bps, fee_bps, position_size_sol (inline number inputs)
- Simulate: toggle for simulate_before_execute
- "Run Backtest" button

**During execution:**
- Progress indicator (based on rows processed / total rows)
- Live metrics updating via `/ws/backtest` — same panels as dashboard but fed from replay data
- Cancel button

**After completion: Results view**
- Summary cards: total opportunities, win rate, total P&L, avg profit, avg spread, duration
- Charts:
  - P&L curve over time
  - Spread distribution histogram
  - Hourly heatmap (opportunity density by hour)
  - Direction breakdown (BUY_DEX vs SELL_DEX pie/bar)
- Full trade table: sortable, filterable by type/direction/spread range/profit range
- Export: CSV download, Parquet download
- "Tweak & Re-run" button: opens config form pre-filled with current params for quick iteration

### 3. Config

Full configuration editor with profile management.

**Profile bar:**
- Dropdown: free, pro, custom profiles
- "Load" loads selected TOML into the form
- "Save" writes current form state to TOML file
- "Save As" creates a new profile

**Grouped sections (accordion or tabs):**

| Section | Parameters |
|---------|-----------|
| Strategy | strategy (selector), min_spread_bps, fee_bps, pair, position_size_sol, max_position_size_sol |
| Ingest Adapters | Multi-select: helius_ws, binance_ws, geyser, etc. |
| Simulator | Type selector (rpc, passthrough, forked_validator), simulate_before_execute toggle |
| Sink | Type selector (paper_trade, backtest, jito_bundle), db_path, tip_percentage, min/max_tip_lamports |
| Risk Management | max_daily_loss_sol, max_consecutive_misses, circuit_breaker_enabled toggle |
| API Keys | Status indicators (green/red) for HELIUS_API_KEY, HELIUS_RPC_URL, SOLANA_RPC_URL, JITO_BLOCK_ENGINE_URL, WALLET_KEYPAIR_PATH. Never display actual key values — show "Set" or "Not set" only. |

**Validation:** Inline validation on each field (min/max ranges, required fields). Form-level validation before save.

### 4. Analysis

Post-hoc results explorer for paper trades and backtests.

**Database selector:** Dropdown of SQLite files in `data/` directory.

**Summary cards row:**
- Total trades, win rate (%), total P&L (SOL), avg profit/trade, best trade, worst trade, avg spread, date range

**Charts (4-panel grid):**
- P&L curve over time (line chart)
- Spread distribution (histogram, bucketed: 0-20, 20-50, 50-100, 100-200, 200+ bps)
- Hourly heatmap (24 columns, color intensity = opportunity count)
- Direction breakdown (BUY_DEX vs SELL_DEX: count + total P&L)

**Trade table:**
- Columns: timestamp, type, direction, pair, dex, dex_price, reference_price, spread_bps, estimated_profit, simulated_profit, pool_address, detector
- Sortable by any column (click header)
- Filterable: text search, direction dropdown, spread range slider, date range picker
- Pagination (50 rows per page)
- Export: CSV button, Parquet button

**Compare mode:**
- Select two SQLite databases (e.g., two different backtest runs)
- Overlay P&L curves on same chart
- Side-by-side summary card comparison
- Useful for A/B testing strategy param changes

### 5. Data

Parquet file management and historical data fetching.

**File browser table:**
- Columns: filename, size, row count, date range (min/max timestamp in file), created date
- Actions per file: Preview (shows first 10 rows in a modal table), Download, Delete (with confirmation)

**Fetch Historical (Helius) form:**
- Pool address (text input, default: Raydium SOL/USDC)
- Interval (seconds): number input, default 5
- Duration (minutes): number input, default 60
- Output directory: text input, default ./data/
- "Start Fetch" button → runs in background, shows progress (slot numbers, price, percentage)
- Requires HELIUS_API_KEY (form disabled with warning if not set)

**Fetch Binance form:**
- Symbol: text input, default SOLUSDT
- Interval: dropdown (1s, 1m, 1h, 1d)
- Days: number input, default 1
- Output directory: text input
- "Start Fetch" button → runs in background, shows progress (batch count, total candles)

**Active fetches:** Panel showing running fetch jobs with progress bars and cancel buttons.

### 6. Learn

Educational content for Solana MEV practitioners.

**Built-in guides** (shipped as markdown files in `src/mev_kit/ui/guides/`, rendered as HTML in the UI):

| Guide | Content |
|-------|---------|
| MEV on Solana: Concepts | What MEV is, how Solana's architecture (leader schedule, continuous block production) differs from Ethereum's (proposer-builder separation), why Jito exists |
| How CEX-DEX Arbitrage Works | The specific strategy: price discrepancy between Binance and Raydium, spread calculation, fee accounting, when to buy vs sell on DEX |
| The mev-kit Pipeline | Source → Detector → Simulator → Sink explained with diagrams. What each layer does, how data flows, how adapters are swapped |
| Writing a Custom Detector | Tutorial: subclass Detector, implement `process()`, emit Opportunity objects. Complete code example with inline commentary |
| Backtesting Your Strategy | Step-by-step: fetch data → create Parquet → configure backtest → run → analyze results. Uses the UI's own pages as the walkthrough |

**External resources** (curated links with short descriptions):

| Category | Links |
|----------|-------|
| Solana Core | Solana Cookbook, Solana docs (transactions, programs) |
| Jito | Jito docs, Jito bundles explained, tip accounts |
| DEX Protocols | Raydium SDK, Orca Whirlpools, Phoenix docs |
| Data Sources | Helius docs (WebSocket, RPC), Birdeye API |
| MEV Research | Flashbots research, Jito MEV dashboard, relevant papers |

**Rendering:** Markdown rendered with syntax-highlighted code blocks. Table of contents sidebar for longer guides. Previous/Next navigation between guides.

## File Organization

```
src/mev_kit/
├── ui/
│   ├── __init__.py
│   ├── server.py           ← FastAPI app, routes, WebSocket handlers
│   ├── pipeline_manager.py ← PipelineManager singleton
│   ├── config_manager.py   ← TOML read/write/validate
│   ├── data_manager.py     ← Parquet CRUD + fetch job runner
│   ├── backtest_runner.py  ← Async backtest execution
│   ├── guides/             ← Markdown guide files
│   │   ├── 01-mev-on-solana.md
│   │   ├── 02-cex-dex-arb.md
│   │   ├── 03-pipeline.md
│   │   ├── 04-custom-detector.md
│   │   └── 05-backtesting.md
│   └── static/             ← Pre-built React app (gitignored, built during release)
│       ├── index.html
│       └── assets/
ui/                          ← React source (development only)
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── vite.config.ts
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/                ← API client + WebSocket hooks
│   │   ├── client.ts
│   │   ├── ws.ts
│   │   └── types.ts
│   ├── components/
│   │   ├── Layout.tsx      ← Sidebar + page shell
│   │   ├── panels/         ← Dashboard panels (MetricsStrip, PnlChart, Feed, etc.)
│   │   ├── charts/         ← Reusable chart components
│   │   └── common/         ← Buttons, inputs, modals, tables
│   ├── pages/
│   │   ├── Dashboard.tsx
│   │   ├── Backtest.tsx
│   │   ├── Config.tsx
│   │   ├── Analysis.tsx
│   │   ├── Data.tsx
│   │   └── Learn.tsx
│   └── hooks/              ← Custom React hooks (usePipeline, useWebSocket, etc.)
└── public/
```

## CLI Entry Point

Add `ui` command to `src/mev_kit/cli.py`:

```
mev-kit ui --port 8080 --no-open
```

- `--port`: Server port (default 8080)
- `--no-open`: Don't auto-open browser

Starts FastAPI with uvicorn, serves the built React SPA and API. Opens browser to `http://localhost:{port}` by default.

## Dependencies to Add

### Python (pyproject.toml)
- `fastapi>=0.111`
- `uvicorn[standard]>=0.29`
- `python-multipart>=0.0.9` (file uploads)
- `markdown>=3.6` (guide rendering)
- `pygments>=2.17` (code syntax highlighting in guides)

### Frontend (ui/package.json)
- `react`, `react-dom`, `react-router-dom`
- `typescript`
- `vite` (build tool)
- `tailwindcss`
- `react-grid-layout` (draggable panels)
- `lightweight-charts` (TradingView charts)
- `recharts` (histograms, heatmaps)
- `react-markdown` + `remark-gfm` (guide rendering)
- `lucide-react` (icons)

## Error Handling

- API errors return structured JSON: `{"error": "message", "detail": "..."}`
- WebSocket disconnections: frontend auto-reconnects with exponential backoff (1s, 2s, 4s, max 30s) — matches the adapter reconnect pattern
- Pipeline start failures: error displayed in a toast notification with the specific error message
- Missing API keys: relevant features show a clear "API key required" message with link to config page
- Circuit breaker trip: dashboard shows a prominent warning banner, pipeline auto-stops

## Testing Strategy

- **Backend API tests:** pytest + httpx AsyncClient against FastAPI test app. Mock PipelineManager.
- **WebSocket tests:** pytest-asyncio with WebSocket test client. Verify message format and frequency.
- **Frontend:** Vitest + React Testing Library for component tests. Playwright for E2E (start server → navigate pages → verify data renders).
- **Integration:** Start real pipeline with ParquetReplayAdapter, verify dashboard receives updates via WebSocket and displays them.

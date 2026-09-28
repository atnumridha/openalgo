# OpenAlgo Documentation Map

The entry point for humans and AI agents. This file is a **map, not a copy** —
it points at the canonical docs that already live under `docs/`. Edit a source
doc once; everything that reads through this map sees the change immediately.

**How to use (progressive disclosure):** read this map → open the one area you
need → drill into the specific file. Don't load everything at once.

---

## Using OpenAlgo (product, API, SDK)

| Read this when you need… | Entry point |
|---|---|
| The REST API (`/api/v1/`) — orders, market data, options, account, streaming | [api/README.md](api/README.md) |
| The Python SDK — install, client, data/order/account calls | [<prompt/openalgo python sdk.md>](<prompt/openalgo python sdk.md>) |
| Symbol format across exchanges (equity/futures/options) | [prompt/symbol-format.md](prompt/symbol-format.md) |
| Order constants (exchange / product / price-type / action codes) | [prompt/order-constants.md](prompt/order-constants.md) |
| Contract lot sizes | [prompt/LotSize.md](prompt/LotSize.md) |
| WebSocket subscription & message format | [prompt/websockets-format.md](prompt/websockets-format.md) · [prompt/websockets-verbose-control.md](prompt/websockets-verbose-control.md) |
| Service-layer functions & Flow JSON import | [prompt/services_documentation.md](prompt/services_documentation.md) · [prompt/flow-import-format.md](prompt/flow-import-format.md) |
| Strategy module & risk engine (multi-leg options, signal mode, RMS) | [prompt/strategy_rms_documentation.md](prompt/strategy_rms_documentation.md) · [api/strategy-services/](api/strategy-services/) · [prd/strategy-module-rms.md](prd/strategy-module-rms.md) · [bdd/strategy_module_rms.feature](bdd/strategy_module_rms.feature) |
| Technical indicators (`ta` library) | [<prompt/indicators/openalgo indicators - introduction.md>](<prompt/indicators/openalgo indicators - introduction.md>) |
| The charting terminal at `/trading`, its order dock and its shortcuts | [userguide/32-charting-terminal](userguide/32-charting-terminal/README.md) |
| Writing your own chart indicators for `/trading` | [custom-indicators.md](custom-indicators.md) |
| Writing studies in OpenScript for `/trading` | [openscript.md](openscript.md) |
| Step-by-step user guide (setup → first order → integrations) | [userguide/README.md](userguide/README.md) |
| MCP tool reference (Claude Desktop / Cursor / Windsurf) | [mcp-tool-reference.md](mcp-tool-reference.md) |

## Install, deploy & operate

| Topic | Entry point |
|---|---|
| One-click local startup (macOS) | [local-startup.md](local-startup.md) |
| Groww algorithmic tests and cumulative strategy ranking | [strategy-ranking-2026-09-27.md](strategy-ranking-2026-09-27.md) |
| 28 September strategy results, entry refusals and execution audit | [strategy-operations-audit-2026-09-28.md](strategy-operations-audit-2026-09-28.md) |
| Kotak MCX contract units, supported products and accounting examples | [mcx-contract-units.md](mcx-contract-units.md) |
| Ubuntu server install | [installation-guidelines/getting-started/ubuntu-server-installation.md](installation-guidelines/getting-started/ubuntu-server-installation.md) |
| Docker | [docker/README.md](docker/README.md) |
| Upgrade / SMTP / TOTP / forgot-password | https://docs.openalgo.in/installation-guidelines/getting-started/ |
| Broker integration (36 plugins) | [broker-integration-guide.md](broker-integration-guide.md) |
| Release notes & changelog | [releases/](releases/) · [CHANGELOG.md](CHANGELOG.md) |

## Feature surfaces

| Feature | Entry point |
|---|---|
| Agent (`/agent`) | [design/55-agent/README.md](design/55-agent/README.md) |
| Strategy Research and shared capital limits | [trading-research.md](trading-research.md) |
| Offline technical ML training and results | [technical-ml-training-2026-09-26.md](technical-ml-training-2026-09-26.md) |
| Twelve-configuration ML search and chronological retraining | [ml-walkforward-search-2026-09-26.md](ml-walkforward-search-2026-09-26.md) |
| Prediction-quality improvements and benchmark results | [ml-prediction-improvement-2026-09-26.md](ml-prediction-improvement-2026-09-26.md) |
| EMA9/15, MACD and 5EMA scalping comparison at INR25,000 | [ema-scalping-evaluation-2026-09-26.md](ema-scalping-evaluation-2026-09-26.md) |
| Automated scalping presets: sandbox/live controls and limits | [scalping-strategies.md](scalping-strategies.md) |
| Four-hour range reversal: Nifty accuracy and after-cost results | [fourhour-range-evaluation-2026-09-26.md](fourhour-range-evaluation-2026-09-26.md) |
| Fabio order-flow strategy: data availability and testability audit | [fabio-orderflow-evaluation-2026-09-26.md](fabio-orderflow-evaluation-2026-09-26.md) |
| IG stochastic, MA, SAR and RSI scalping comparison | [ig-scalping-evaluation-2026-09-27.md](ig-scalping-evaluation-2026-09-27.md) |
| Tradetron guide: EMA, RSI divergence, Bollinger and price-action tests | [tradetron-scalping-evaluation-2026-09-27.md](tradetron-scalping-evaluation-2026-09-27.md) |
| StockGro guidance: matched EMA chart intervals and entry sessions | [stockgro-timeframes-2026-09-27.md](stockgro-timeframes-2026-09-27.md) |
| Tradejini: EMA9/21 and opening range with option-premium exits | [tradejini-scalping-evaluation-2026-09-27.md](tradejini-scalping-evaluation-2026-09-27.md) |
| Groww video: Supertrend pullback and close-confirmed option tests | [groww-supertrend-evaluation-2026-09-27.md](groww-supertrend-evaluation-2026-09-27.md) |
| Scalping Terminal (`/scalping`) | [scalping/PRD.md](scalping/PRD.md) |
| Scanner architecture | [scanner-architecture.md](scanner-architecture.md) |
| WhatsApp alerts | [whatsapp.md](whatsapp.md) |
| Telegram chart rendering | [telegram-chart-rendering.md](telegram-chart-rendering.md) |
| Health monitoring | [HEALTH_MONITORING_IMPLEMENTATION.md](HEALTH_MONITORING_IMPLEMENTATION.md) · [HEALTH_MONITOR_REACT_FRONTEND.md](HEALTH_MONITOR_REACT_FRONTEND.md) |

## Architecture, design & specs (contributors)

| Topic | Entry point |
|---|---|
| First-time contributor setup (devsprint prep) | [devsprint/README.md](devsprint/README.md) |
| System design (frontend, backend, DB, UI) | [design/README.md](design/README.md) |
| Product requirements — Flow, Python strategies, Strategy module & RMS, Sandbox, Historify, MCP, event bus, websocket proxy | [prd/README.md](prd/README.md) · [prd/PRD.md](prd/PRD.md) |
| BDD feature specs (Gherkin `.feature`) | [bdd/README.md](bdd/README.md) |
| WebSocket architecture & quote feed | [websocket-architecture.md](websocket-architecture.md) · [websocket-quote-feed.md](websocket-quote-feed.md) |
| Security audits | [audit/README.md](audit/README.md) |
| CI/CD | [prd/ci-cd.md](prd/ci-cd.md) |
| Benchmarks | [benchmarks/](benchmarks/) |
| Migration plans | [migration/](migration/) |
| Implementation plans | [plans/](plans/) |
| Testing guides | [test/](test/) |
| XTS API | [xtsapi.md](xtsapi.md) |

---

## Governance

- User responsibilities & risk ownership: https://docs.openalgo.in/responsibilities
- Repository: https://github.com/marketcalls/openalgo · Docs: https://docs.openalgo.in

- [Allocated capital profile](trading-capital-profile.md) — activation, budgets, reconciliation and qualification limits.

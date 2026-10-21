# AI Model Gateway

<cite>
**Referenced Files in This Document**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [ai_teacher_route.py](file://backend/ai_teacher_route.py)
- [config.py](file://backend/config.py)
- [monitoring.py](file://backend/monitoring.py)
- [cost_optimization_demo/main_service.py](file://backend/cost_optimization_demo/main_service.py)
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)
- [cost_optimization_demo/config.py](file://backend/cost_optimization_demo/config.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)
- [cost_optimization_demo/regression_test.py](file://backend/cost_optimization_demo/regression_test.py)
- [test_gateway_llm.py](file://backend/test_gateway_llm.py)
- [debug_gateway_api.py](file://backend/debug_gateway_api.py)
- [list_gateway_models.py](file://backend/list_gateway_models.py)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)
10. [Appendices](#appendices)

## Introduction
This document describes the AI model gateway system that provides a multi-provider abstraction layer for large language models (LLMs). It covers intelligent model selection, cost optimization strategies, caching mechanisms, request routing, load balancing between providers, fallback mechanisms, and performance monitoring. It also documents the cache service implementation, cost tracking, usage analytics, and how to add new AI providers with provider-specific settings and custom selection strategies.

## Project Structure
The AI gateway is implemented primarily under the backend directory. Key areas include:
- Gateway core and routing logic
- Cost optimization demo module with cache service and client adapters
- Monitoring utilities
- Tests and debug utilities

```mermaid
graph TB
subgraph "Backend"
A["gateway_llm.py"]
B["ai_teacher_route.py"]
C["config.py"]
D["monitoring.py"]
E["test_gateway_llm.py"]
F["debug_gateway_api.py"]
G["list_gateway_models.py"]
end
subgraph "Cost Optimization Demo"
H["main_service.py"]
I["cache_service.py"]
J["config.py"]
K["gemini_client.py"]
L["regression_test.py"]
end
A --> B
A --> C
A --> D
H --> I
H --> J
H --> K
E --> A
F --> A
G --> A
```

**Diagram sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [ai_teacher_route.py](file://backend/ai_teacher_route.py)
- [config.py](file://backend/config.py)
- [monitoring.py](file://backend/monitoring.py)
- [test_gateway_llm.py](file://backend/test_gateway_llm.py)
- [debug_gateway_api.py](file://backend/debug_gateway_api.py)
- [list_gateway_models.py](file://backend/list_gateway_models.py)
- [cost_optimization_demo/main_service.py](file://backend/cost_optimization_demo/main_service.py)
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)
- [cost_optimization_demo/config.py](file://backend/cost_optimization_demo/config.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)
- [cost_optimization_demo/regression_test.py](file://backend/cost_optimization_demo/regression_test.py)

**Section sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [ai_teacher_route.py](file://backend/ai_teacher_route.py)
- [config.py](file://backend/config.py)
- [monitoring.py](file://backend/monitoring.py)
- [cost_optimization_demo/main_service.py](file://backend/cost_optimization_demo/main_service.py)
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)
- [cost_optimization_demo/config.py](file://backend/cost_optimization_demo/config.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)
- [cost_optimization_demo/regression_test.py](file://backend/cost_optimization_demo/regression_test.py)
- [test_gateway_llm.py](file://backend/test_gateway_llm.py)
- [debug_gateway_api.py](file://backend/debug_gateway_api.py)
- [list_gateway_models.py](file://backend/list_gateway_models.py)

## Core Components
- Multi-provider abstraction layer: Provides a unified interface to call different LLM backends (e.g., Gemini, DeepSeek). The gateway selects an appropriate provider based on configuration and strategy.
- Intelligent model selection: Applies rules or algorithms to choose the best provider/model per request considering cost, latency, availability, and policy constraints.
- Request routing and load balancing: Routes requests across available providers, supports round-robin or weighted distribution, and enforces per-provider limits.
- Fallback mechanisms: Automatically retries failed requests on alternative providers when primary ones fail or are rate-limited.
- Caching: Reuses previous responses for identical or near-duplicate requests to reduce cost and latency.
- Cost tracking and analytics: Records usage metrics, costs, and provider performance for reporting and optimization.
- Monitoring: Exposes health checks, metrics, and logs for observability.

**Section sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [ai_teacher_route.py](file://backend/ai_teacher_route.py)
- [monitoring.py](file://backend/monitoring.py)
- [cost_optimization_demo/main_service.py](file://backend/cost_optimization_demo/main_service.py)
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)
- [cost_optimization_demo/config.py](file://backend/cost_optimization_demo/config.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)

## Architecture Overview
The gateway sits between application routes and multiple LLM clients. It normalizes inputs, applies selection and caching, routes to providers, handles failures and retries, and records metrics.

```mermaid
sequenceDiagram
participant Client as "Client App"
participant Route as "ai_teacher_route.py"
participant GW as "gateway_llm.py"
participant Sel as "Selection Strategy"
participant Cache as "cache_service.py"
participant ProvA as "Provider A (Gemini)"
participant ProvB as "Provider B (DeepSeek)"
participant Mon as "monitoring.py"
Client->>Route : "POST /ai/teach"
Route->>GW : "invoke(request)"
GW->>Cache : "lookup(key)"
alt "Cache hit"
Cache-->>GW : "cached response"
GW-->>Route : "response"
else "Cache miss"
GW->>Sel : "select_provider(request)"
Sel-->>GW : "provider choice"
GW->>ProvA : "call(primary)"
alt "Success"
ProvA-->>GW : "result + usage"
GW->>Mon : "record_metrics(provider, latency, tokens)"
GW->>Cache : "store(key, result)"
GW-->>Route : "response"
else "Failure"
ProvA-->>GW : "error"
GW->>Sel : "fallback_provider()"
Sel-->>GW : "secondary provider"
GW->>ProvB : "call(fallback)"
ProvB-->>GW : "result + usage"
GW->>Mon : "record_metrics(provider, latency, tokens)"
GW->>Cache : "store(key, result)"
GW-->>Route : "response"
end
end
```

**Diagram sources**
- [ai_teacher_route.py](file://backend/ai_teacher_route.py)
- [gateway_llm.py](file://backend/gateway_llm.py)
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)
- [monitoring.py](file://backend/monitoring.py)

## Detailed Component Analysis

### Gateway Core and Routing
- Entry points expose HTTP endpoints that delegate to the gateway for LLM calls.
- The gateway encapsulates provider selection, caching, retry/fallback, and metrics recording.
- Configuration is centralized and consumed by both gateway and demo services.

```mermaid
flowchart TD
Start(["Request Received"]) --> Parse["Parse and validate request"]
Parse --> CacheLookup["Check cache by request key"]
CacheLookup --> |Hit| ReturnCached["Return cached response"]
CacheLookup --> |Miss| Select["Select provider/model"]
Select --> CallPrimary["Call primary provider"]
CallPrimary --> PrimaryOK{"Primary success?"}
PrimaryOK --> |Yes| RecordMetrics["Record metrics and usage"]
PrimaryOK --> |No| Fallback["Select fallback provider"]
Fallback --> CallFallback["Call fallback provider"]
CallFallback --> FallbackOK{"Fallback success?"}
FallbackOK --> |Yes| RecordMetrics
FallbackOK --> |No| Fail["Return error to caller"]
RecordMetrics --> StoreCache["Store result in cache"]
StoreCache --> End(["Response Sent"])
ReturnCached --> End
Fail --> End
```

**Diagram sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [ai_teacher_route.py](file://backend/ai_teacher_route.py)
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)
- [monitoring.py](file://backend/monitoring.py)

**Section sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [ai_teacher_route.py](file://backend/ai_teacher_route.py)
- [config.py](file://backend/config.py)
- [monitoring.py](file://backend/monitoring.py)

### Cost Optimization Demo Module
The demo module demonstrates practical integration patterns:
- main_service.py orchestrates requests through the gateway and integrates with cache and providers.
- cache_service.py implements in-memory or file-backed caching keyed by normalized request content.
- config.py centralizes provider credentials, model names, and selection policies.
- gemini_client.py adapts calls to the Gemini API and returns standardized results and usage metadata.
- regression_test.py validates behavior across providers and caches.

```mermaid
classDiagram
class MainService {
+invoke(request) Response
+get_usage() UsageReport
}
class CacheService {
+get(key) Optional[Response]
+put(key, response) void
+invalidate(pattern) void
}
class Config {
+providers : list
+selection_strategy : str
+rate_limits : dict
}
class GeminiClient {
+generate(prompt, params) Result
+usage() Usage
}
MainService --> CacheService : "reads/writes"
MainService --> Config : "loads settings"
MainService --> GeminiClient : "calls via adapter"
```

**Diagram sources**
- [cost_optimization_demo/main_service.py](file://backend/cost_optimization_demo/main_service.py)
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)
- [cost_optimization_demo/config.py](file://backend/cost_optimization_demo/config.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)

**Section sources**
- [cost_optimization_demo/main_service.py](file://backend/cost_optimization_demo/main_service.py)
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)
- [cost_optimization_demo/config.py](file://backend/cost_optimization_demo/config.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)
- [cost_optimization_demo/regression_test.py](file://backend/cost_optimization_demo/regression_test.py)

### Provider Abstraction Layer
- Unified interface abstracts differences between providers (authentication, request format, streaming, token accounting).
- Each provider is implemented as an adapter that conforms to the gateway’s expected contract.
- Selection strategies can be configured to prefer specific providers based on cost, latency, or capability tags.

```mermaid
classDiagram
class ProviderAdapter {
<<interface>>
+generate(prompt, params) Result
+health_check() bool
+estimate_cost(tokens) float
}
class GeminiAdapter {
+generate(prompt, params) Result
+health_check() bool
+estimate_cost(tokens) float
}
class DeepSeekAdapter {
+generate(prompt, params) Result
+health_check() bool
+estimate_cost(tokens) float
}
ProviderAdapter <|.. GeminiAdapter
ProviderAdapter <|.. DeepSeekAdapter
```

**Diagram sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)

**Section sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)

### Intelligent Model Selection and Load Balancing
- Selection considers provider capabilities, current load, historical latency, and cost targets.
- Load balancing distributes traffic across providers using configurable weights or round-robin.
- Fallback triggers when primary provider errors exceed thresholds or returns rate-limit signals.

```mermaid
flowchart TD
S(["Start Selection"]) --> CheckPolicy["Apply policy constraints<br/>budget, region, model family"]
CheckPolicy --> ScoreProviders["Score providers by cost/latency/availability"]
ScoreProviders --> ChooseBest["Choose best provider"]
ChooseBest --> ApplyLB["Apply load balancing rule"]
ApplyLB --> Done(["Provider selected"])
```

**Diagram sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [config.py](file://backend/config.py)

**Section sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [config.py](file://backend/config.py)

### Caching Mechanism
- Cache keys are derived from normalized request content to ensure hits for semantically identical prompts.
- TTL and invalidation policies control freshness and memory usage.
- Cache misses trigger full provider calls; hits bypass external calls entirely.

```mermaid
flowchart TD
In(["Incoming request"]) --> Normalize["Normalize prompt and parameters"]
Normalize --> Hash["Compute cache key"]
Hash --> Get["Get from cache"]
Get --> Hit{"Cache hit?"}
Hit --> |Yes| Return["Return cached response"]
Hit --> |No| Call["Call provider"]
Call --> Store["Store in cache with TTL"]
Store --> Return
```

**Diagram sources**
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)

**Section sources**
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)

### Cost Tracking and Usage Analytics
- Metrics include provider name, model, latency, tokens, and estimated cost.
- Aggregations support daily totals, per-user usage, and per-provider spend.
- Integration with monitoring exposes dashboards and alerts.

```mermaid
sequenceDiagram
participant GW as "Gateway"
participant Mon as "Monitoring"
participant DB as "Usage Storage"
GW->>Mon : "record(provider, tokens, latency)"
Mon->>DB : "persist metrics"
Mon-->>GW : "ack"
```

**Diagram sources**
- [monitoring.py](file://backend/monitoring.py)
- [gateway_llm.py](file://backend/gateway_llm.py)

**Section sources**
- [monitoring.py](file://backend/monitoring.py)
- [gateway_llm.py](file://backend/gateway_llm.py)

### Adding New AI Providers
To integrate a new provider:
- Implement a provider adapter conforming to the gateway’s interface.
- Register the adapter in the configuration and update selection policies if needed.
- Add tests to verify correctness and fallback behavior.

Steps:
1. Create a new adapter file implementing generate, health_check, and estimate_cost.
2. Update provider registry and configuration to include credentials and model mapping.
3. Extend selection strategy to consider the new provider’s attributes.
4. Add unit/integration tests covering success, failure, and fallback paths.

**Section sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [config.py](file://backend/config.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)
- [test_gateway_llm.py](file://backend/test_gateway_llm.py)

### Configuring Provider-Specific Settings
- Credentials, base URLs, model names, and timeouts are defined centrally.
- Per-provider options such as temperature, max tokens, and safety filters can be included.
- Rate limits and budget caps are enforced by the gateway and monitoring layers.

**Section sources**
- [config.py](file://backend/config.py)
- [cost_optimization_demo/config.py](file://backend/cost_optimization_demo/config.py)

### Implementing Custom Selection Strategies
- Selection strategies are pluggable functions or classes evaluated at runtime.
- Inputs include request context, provider scores, and current metrics.
- Outputs determine the chosen provider and any routing hints.

**Section sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [config.py](file://backend/config.py)

## Dependency Analysis
The gateway depends on configuration, monitoring, and provider adapters. The demo module adds cache and client adapters.

```mermaid
graph TB
GW["gateway_llm.py"] --> CFG["config.py"]
GW --> MON["monitoring.py"]
GW --> PROV["Provider Adapters"]
DEMO_MAIN["cost_optimization_demo/main_service.py"] --> DEMO_CACHE["cost_optimization_demo/cache_service.py"]
DEMO_MAIN --> DEMO_CFG["cost_optimization_demo/config.py"]
DEMO_MAIN --> DEMO_GEMINI["cost_optimization_demo/gemini_client.py"]
TESTS["test_gateway_llm.py"] --> GW
DEBUG["debug_gateway_api.py"] --> GW
LIST["list_gateway_models.py"] --> GW
```

**Diagram sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [config.py](file://backend/config.py)
- [monitoring.py](file://backend/monitoring.py)
- [cost_optimization_demo/main_service.py](file://backend/cost_optimization_demo/main_service.py)
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)
- [cost_optimization_demo/config.py](file://backend/cost_optimization_demo/config.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)
- [test_gateway_llm.py](file://backend/test_gateway_llm.py)
- [debug_gateway_api.py](file://backend/debug_gateway_api.py)
- [list_gateway_models.py](file://backend/list_gateway_models.py)

**Section sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [config.py](file://backend/config.py)
- [monitoring.py](file://backend/monitoring.py)
- [cost_optimization_demo/main_service.py](file://backend/cost_optimization_demo/main_service.py)
- [cost_optimization_demo/cache_service.py](file://backend/cost_optimization_demo/cache_service.py)
- [cost_optimization_demo/config.py](file://backend/cost_optimization_demo/config.py)
- [cost_optimization_demo/gemini_client.py](file://backend/cost_optimization_demo/gemini_client.py)
- [test_gateway_llm.py](file://backend/test_gateway_llm.py)
- [debug_gateway_api.py](file://backend/debug_gateway_api.py)
- [list_gateway_models.py](file://backend/list_gateway_models.py)

## Performance Considerations
- Prefer cache hits by normalizing prompts and parameters consistently.
- Use connection pooling and timeouts tuned per provider.
- Monitor latency distributions and adjust selection weights accordingly.
- Avoid excessive retries; implement exponential backoff and circuit breaking where applicable.
- Batch metrics updates to reduce overhead.

## Troubleshooting Guide
Common issues and diagnostics:
- Provider connectivity failures: check credentials, base URLs, and network reachability.
- Rate limiting: review per-provider quotas and adjust selection weights or budgets.
- Cache inconsistencies: verify normalization logic and TTL settings.
- High latency: analyze provider performance metrics and consider switching strategies.

Useful utilities:
- Debug gateway API endpoint for inspecting routing decisions and metrics.
- List available gateway models and their statuses.
- Regression tests to validate end-to-end flows across providers and caches.

**Section sources**
- [debug_gateway_api.py](file://backend/debug_gateway_api.py)
- [list_gateway_models.py](file://backend/list_gateway_models.py)
- [cost_optimization_demo/regression_test.py](file://backend/cost_optimization_demo/regression_test.py)
- [test_gateway_llm.py](file://backend/test_gateway_llm.py)

## Conclusion
The AI model gateway provides a robust, extensible foundation for integrating multiple LLM providers. Its design emphasizes intelligent selection, cost optimization, caching, and observability. By following the documented patterns, teams can add new providers, customize selection strategies, and maintain high reliability and efficiency across diverse workloads.

## Appendices

### Example: Adding a New Provider
- Implement adapter methods for generation, health checks, and cost estimation.
- Register provider details in configuration and update selection policies.
- Validate with targeted tests and monitor initial performance.

**Section sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [config.py](file://backend/config.py)
- [test_gateway_llm.py](file://backend/test_gateway_llm.py)

### Example: Configuring Provider-Specific Settings
- Define credentials, model mappings, and operational parameters in configuration files.
- Set rate limits and budget caps to enforce cost controls.
- Adjust selection strategy parameters to reflect business priorities.

**Section sources**
- [config.py](file://backend/config.py)
- [cost_optimization_demo/config.py](file://backend/cost_optimization_demo/config.py)

### Example: Implementing Custom Selection Strategies
- Provide a function or class that evaluates provider scores and returns the chosen provider.
- Incorporate real-time metrics and policy constraints into scoring.
- Test strategy changes with regression suites and monitor outcomes.

**Section sources**
- [gateway_llm.py](file://backend/gateway_llm.py)
- [config.py](file://backend/config.py)
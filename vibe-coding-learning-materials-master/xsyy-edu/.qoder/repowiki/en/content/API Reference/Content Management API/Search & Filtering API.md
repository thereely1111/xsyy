# Search & Filtering API

<cite>
**Referenced Files in This Document**
- [app.py](file://backend/app.py)
- [database/models.py](file://backend/database/models.py)
- [utils/embedding_utils.py](file://backend/utils/embedding_utils.py)
- [utils/vector_db.py](file://backend/utils/vector_db.py)
- [config.py](file://backend/config.py)
- [monitoring.py](file://backend/monitoring.py)
- [requirements.txt](file://backend/requirements.txt)
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
This document explains the search and filtering capabilities of the Content Management API, including full-text search endpoints, semantic search using vector embeddings, advanced filtering options, and sorting mechanisms. It also covers query parameters for text searches, category filters, date ranges, user-specific content retrieval, pagination, result ranking, faceted search implementation, performance optimization techniques, ChromaDB integration for vector search, embedding generation, similarity matching, and search analytics tracking.

## Project Structure
The backend exposes REST endpoints that orchestrate:
- Full-text search against relational tables (e.g., teachings, topics).
- Semantic search via vector embeddings stored in ChromaDB.
- Advanced filtering by categories, dates, and user ownership.
- Sorting and pagination for consistent result sets.
- Analytics tracking for search events.

```mermaid
graph TB
Client["Client App"] --> API["API Server<br/>Flask app.py"]
API --> DB["Relational Database<br/>models.py"]
API --> VectorDB["Vector Store<br/>ChromaDB via utils/vector_db.py"]
API --> Embeddings["Embedding Generator<br/>utils/embedding_utils.py"]
API --> Monitor["Analytics & Metrics<br/>monitoring.py"]
API --> Config["Configuration<br/>config.py"]
```

**Diagram sources**
- [app.py](file://backend/app.py)
- [database/models.py](file://backend/database/models.py)
- [utils/vector_db.py](file://backend/utils/vector_db.py)
- [utils/embedding_utils.py](file://backend/utils/embedding_utils.py)
- [monitoring.py](file://backend/monitoring.py)
- [config.py](file://backend/config.py)

**Section sources**
- [app.py](file://backend/app.py)
- [database/models.py](file://backend/database/models.py)
- [utils/vector_db.py](file://backend/utils/vector_db.py)
- [utils/embedding_utils.py](file://backend/utils/embedding_utils.py)
- [monitoring.py](file://backend/monitoring.py)
- [config.py](file://backend/config.py)

## Core Components
- API Endpoints: Define routes for full-text search, semantic search, filtering, sorting, and pagination.
- Database Models: Represent entities like teachings and topics with fields used for filtering and sorting.
- Vector Store Integration: ChromaDB client wrapper for storing and querying embeddings.
- Embedding Utilities: Generate embeddings from text content and manage metadata.
- Configuration: Centralized settings for database connections, ChromaDB, and feature flags.
- Monitoring: Track search queries, latencies, and errors for analytics.

Key responsibilities:
- Validate and normalize search inputs.
- Build SQL queries for full-text search and filters.
- Convert text to embeddings and perform similarity search.
- Merge or rank results from multiple sources.
- Apply pagination and return structured responses.
- Emit metrics and logs for observability.

**Section sources**
- [app.py](file://backend/app.py)
- [database/models.py](file://backend/database/models.py)
- [utils/vector_db.py](file://backend/utils/vector_db.py)
- [utils/embedding_utils.py](file://backend/utils/embedding_utils.py)
- [config.py](file://backend/config.py)
- [monitoring.py](file://backend/monitoring.py)

## Architecture Overview
The search pipeline supports two primary modes:
- Full-text search: Keyword-based queries against relational tables with filters and sorting.
- Semantic search: Vector similarity search using embeddings stored in ChromaDB.

```mermaid
sequenceDiagram
participant C as "Client"
participant A as "API Server"
participant D as "Database"
participant V as "ChromaDB"
participant E as "Embedding Utils"
participant M as "Monitoring"
C->>A : "POST /api/search"
A->>M : "Log search request"
alt "Semantic search enabled"
A->>E : "Generate embedding(query)"
E-->>A : "vector"
A->>V : "Query vectors with top_k, filter"
V-->>A : "results[]"
end
A->>D : "Full-text search with filters/sort"
D-->>A : "rows[]"
A->>A : "Merge/rank results"
A->>A : "Apply pagination"
A-->>C : "Response {items, total, page}"
A->>M : "Log latency and outcome"
```

**Diagram sources**
- [app.py](file://backend/app.py)
- [utils/vector_db.py](file://backend/utils/vector_db.py)
- [utils/embedding_utils.py](file://backend/utils/embedding_utils.py)
- [database/models.py](file://backend/database/models.py)
- [monitoring.py](file://backend/monitoring.py)

## Detailed Component Analysis

### Full-Text Search Endpoint
- Purpose: Retrieve items matching keywords with optional filters and sorting.
- Query Parameters:
  - q: Search text
  - category: Filter by category
  - start_date, end_date: Date range filters
  - user_id: Filter by owner
  - sort_by: Field name for sorting
  - order: asc/desc
  - page, per_page: Pagination
- Behavior:
  - Validates parameters and normalizes text.
  - Builds SQL with LIKE or full-text index where available.
  - Applies filters and sorting.
  - Returns paginated results.

```mermaid
flowchart TD
Start(["Request Received"]) --> Parse["Parse Query Params"]
Parse --> Validate{"Valid?"}
Validate --> |No| Err["Return 400 Error"]
Validate --> |Yes| BuildSQL["Build SQL Query"]
BuildSQL --> Exec["Execute Query"]
Exec --> Rows{"Rows Found?"}
Rows --> |No| Empty["Return empty list"]
Rows --> |Yes| Sort["Apply Sorting"]
Sort --> Paginate["Apply Pagination"]
Paginate --> Resp["Return Response"]
Err --> End(["Done"])
Empty --> End
Resp --> End
```

**Diagram sources**
- [app.py](file://backend/app.py)
- [database/models.py](file://backend/database/models.py)

**Section sources**
- [app.py](file://backend/app.py)
- [database/models.py](file://backend/database/models.py)

### Semantic Search Endpoint
- Purpose: Perform vector similarity search using embeddings.
- Query Parameters:
  - q: Search text
  - top_k: Number of results
  - filter: Metadata filter (category, user_id, date range)
  - include_metadata: Boolean flag
- Behavior:
  - Generates embedding for query text.
  - Queries ChromaDB with similarity metric and filters.
  - Optionally merges with full-text results for hybrid ranking.
  - Returns ranked results with scores and metadata.

```mermaid
sequenceDiagram
participant C as "Client"
participant A as "API Server"
participant E as "Embedding Utils"
participant V as "ChromaDB"
participant M as "Monitoring"
C->>A : "GET /api/search/semantic?q=...&top_k=..."
A->>E : "embed(text)"
E-->>A : "vector"
A->>V : "query(vector, top_k, filter)"
V-->>A : "matches[]"
A->>A : "Rank by similarity score"
A-->>C : "Results with scores"
A->>M : "Track latency and hits"
```

**Diagram sources**
- [app.py](file://backend/app.py)
- [utils/embedding_utils.py](file://backend/utils/embedding_utils.py)
- [utils/vector_db.py](file://backend/utils/vector_db.py)
- [monitoring.py](file://backend/monitoring.py)

**Section sources**
- [app.py](file://backend/app.py)
- [utils/embedding_utils.py](file://backend/utils/embedding_utils.py)
- [utils/vector_db.py](file://backend/utils/vector_db.py)

### Advanced Filtering and Sorting
- Filters:
  - Category: Exact match or multi-select.
  - Date Range: start_date and end_date with inclusive boundaries.
  - User-Specific: user_id to restrict to owned content.
  - Status/Visibility: Optional flags for published/archived.
- Sorting:
  - Supported fields: created_at, updated_at, view_count, relevance_score.
  - Order: asc/desc.
- Implementation:
  - Dynamic SQL construction based on provided filters.
  - Index usage for common filter fields to optimize performance.

**Section sources**
- [database/models.py](file://backend/database/models.py)
- [app.py](file://backend/app.py)

### Faceted Search Implementation
- Purpose: Provide counts for facets (categories, users, date buckets).
- Process:
  - Aggregate counts across filtered dataset.
  - Return facet values with counts alongside search results.
- Use Cases:
  - UI-driven refinement of search results.
  - Analytics dashboards for content distribution.

```mermaid
flowchart TD
Start(["Facet Request"]) --> ApplyFilters["Apply Filters"]
ApplyFilters --> GroupBy["Group By Facet Fields"]
GroupBy --> Count["Count Per Group"]
Count --> Merge["Merge With Results"]
Merge --> Return["Return Facets + Items"]
```

**Diagram sources**
- [app.py](file://backend/app.py)
- [database/models.py](file://backend/database/models.py)

**Section sources**
- [app.py](file://backend/app.py)
- [database/models.py](file://backend/database/models.py)

### ChromaDB Integration
- Responsibilities:
  - Manage collections for teachings and topics.
  - Upsert embeddings with metadata (id, title, category, user_id, timestamps).
  - Query with similarity thresholds and metadata filters.
- Configuration:
  - Connection settings and collection names via config.
  - Embedding model selection and dimension handling.

```mermaid
classDiagram
class VectorStore {
+connect()
+upsert(items)
+query(vector, top_k, filter)
+delete(ids)
+list_collections()
}
class EmbeddingUtils {
+generate_embedding(text)
+normalize_vector(vec)
+validate_dimensions(dim)
}
class Config {
+chroma_url
+collection_name
+embedding_model
}
VectorStore --> Config : "uses"
EmbeddingUtils --> Config : "reads"
```

**Diagram sources**
- [utils/vector_db.py](file://backend/utils/vector_db.py)
- [utils/embedding_utils.py](file://backend/utils/embedding_utils.py)
- [config.py](file://backend/config.py)

**Section sources**
- [utils/vector_db.py](file://backend/utils/vector_db.py)
- [utils/embedding_utils.py](file://backend/utils/embedding_utils.py)
- [config.py](file://backend/config.py)

### Pagination and Result Ranking
- Pagination:
  - page: Starting page number (1-based).
  - per_page: Number of items per page.
  - Total count returned for UI navigation.
- Ranking:
  - Full-text: Relevance scoring based on keyword matches.
  - Semantic: Cosine similarity or other metric.
  - Hybrid: Weighted combination of both scores.

**Section sources**
- [app.py](file://backend/app.py)
- [database/models.py](file://backend/database/models.py)

### Search Analytics Tracking
- Tracks:
  - Query text (sanitized), timestamp, latency, result count.
  - Errors and exceptions during search execution.
- Storage:
  - In-memory counters or persistent logs depending on configuration.
- Usage:
  - Performance monitoring and search trend analysis.

**Section sources**
- [monitoring.py](file://backend/monitoring.py)
- [app.py](file://backend/app.py)

## Dependency Analysis
The search system depends on:
- Flask application layer for routing and request handling.
- Database models for schema and ORM operations.
- ChromaDB client for vector storage and queries.
- Embedding utilities for text-to-vector conversion.
- Configuration module for environment-specific settings.
- Monitoring module for analytics and metrics.

```mermaid
graph TB
App["app.py"] --> Models["database/models.py"]
App --> VectorDB["utils/vector_db.py"]
App --> Embeddings["utils/embedding_utils.py"]
App --> Config["config.py"]
App --> Monitoring["monitoring.py"]
VectorDB --> Config
Embeddings --> Config
```

**Diagram sources**
- [app.py](file://backend/app.py)
- [database/models.py](file://backend/database/models.py)
- [utils/vector_db.py](file://backend/utils/vector_db.py)
- [utils/embedding_utils.py](file://backend/utils/embedding_utils.py)
- [config.py](file://backend/config.py)
- [monitoring.py](file://backend/monitoring.py)

**Section sources**
- [app.py](file://backend/app.py)
- [database/models.py](file://backend/database/models.py)
- [utils/vector_db.py](file://backend/utils/vector_db.py)
- [utils/embedding_utils.py](file://backend/utils/embedding_utils.py)
- [config.py](file://backend/config.py)
- [monitoring.py](file://backend/monitoring.py)

## Performance Considerations
- Indexing:
  - Add indexes on frequently filtered columns (category, user_id, timestamps).
  - Use full-text indexes where supported by the database.
- Query Optimization:
  - Limit top_k for semantic search to reduce computation.
  - Avoid deep pagination; use cursor-based pagination for large datasets.
- Caching:
  - Cache frequent queries and embeddings when appropriate.
- Concurrency:
  - Use connection pooling for database and vector store.
- Monitoring:
  - Track latency percentiles and error rates.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- Missing or invalid parameters:
  - Ensure required fields are present and correctly formatted.
- Database connectivity:
  - Verify credentials and network access.
- ChromaDB connection:
  - Check URL and collection existence.
- Embedding failures:
  - Validate input text length and encoding.
- Slow queries:
  - Review indexes and query complexity.
- Analytics gaps:
  - Confirm monitoring is enabled and logging paths are writable.

**Section sources**
- [app.py](file://backend/app.py)
- [monitoring.py](file://backend/monitoring.py)
- [config.py](file://backend/config.py)

## Conclusion
The Content Management API provides robust search and filtering capabilities through full-text and semantic search, advanced filtering, sorting, and pagination. Integration with ChromaDB enables powerful vector-based retrieval, while monitoring ensures observability and performance tuning. Proper indexing, caching, and query optimization are key to maintaining high performance at scale.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### Example Complex Search Queries
- Full-text with filters:
  - q="machine learning", category="AI", start_date="2024-01-01", end_date="2024-12-31", user_id="123", sort_by="created_at", order="desc", page=1, per_page=20
- Semantic search with metadata filter:
  - q="neural networks", top_k=10, filter={"category":"AI","user_id":"123"}, include_metadata=true

[No sources needed since this section provides conceptual examples]

### API Endpoints Summary
- POST /api/search: Full-text search with filters and sorting.
- GET /api/search/semantic: Semantic search with vector similarity.
- GET /api/search/facets: Faceted search counts.

[No sources needed since this section provides conceptual examples]

### Dependencies
- Python packages listed in requirements.txt for Flask, database drivers, ChromaDB client, and embedding libraries.

**Section sources**
- [requirements.txt](file://backend/requirements.txt)
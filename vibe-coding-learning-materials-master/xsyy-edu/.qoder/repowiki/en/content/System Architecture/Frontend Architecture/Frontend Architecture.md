# Frontend Architecture

<cite>
**Referenced Files in This Document**
- [package.json](file://web/package.json)
- [vite.config.ts](file://web/vite.config.ts)
- [tsconfig.json](file://web/tsconfig.json)
- [tailwind.config.js](file://web/tailwind.config.js)
- [postcss.config.js](file://web/postcss.config.js)
- [index.html](file://web/index.html)
- [main.tsx](file://web/src/main.tsx)
- [App.tsx](file://web/src/App.tsx)
- [types.ts](file://web/src/types.ts)
- [api.ts](file://web/src/lib/api.ts)
- [device.ts](file://web/src/lib/device.ts)
- [appStore.ts](file://web/src/store/appStore.ts)
- [TopBar.tsx](file://web/src/components/TopBar.tsx)
- [AuthModal.tsx](file://web/src/components/AuthModal.tsx)
- [AccountCenterModal.tsx](file://web/src/components/AccountCenterModal.tsx)
- [FeedbackModal.tsx](file://web/src/components/FeedbackModal.tsx)
- [InviteModal.tsx](file://web/src/components/InviteModal.tsx)
- [SystemMessagesModal.tsx](file://web/src/components/SystemMessagesModal.tsx)
- [ToastContainer.tsx](file://web/src/components/ToastContainer.tsx)
- [FooterInfoBar.tsx](file://web/src/components/FooterInfoBar.tsx)
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

## Introduction
This document describes the React frontend architecture for the application located under web/. It focuses on:
- Component-based architecture using React with TypeScript
- State management via React Context API
- API client abstraction layer
- Modular component structure and routing strategy
- Build configuration with Vite, Tailwind CSS, and PostCSS
- Separation between UI components, business logic, and data access layers
- Component hierarchy, state flow patterns, and event handling mechanisms
- Responsive design considerations, performance optimization techniques, and cross-browser compatibility strategies

## Project Structure
The frontend is organized into a clear separation of concerns:
- src/: Source code for the React application
  - components/: Reusable UI components (modals, top bar, footer, toast container)
  - lib/: Shared utilities and API client abstraction
  - store/: Global state via Context API
  - App.tsx: Root component and layout/routing entry point
  - main.tsx: Application bootstrap and root rendering
  - types.ts: Shared TypeScript type definitions
  - styles.css: Global styles
- Configuration files at web/:
  - vite.config.ts: Vite build configuration
  - tailwind.config.js: Tailwind CSS configuration
  - postcss.config.js: PostCSS configuration
  - tsconfig.json: TypeScript configuration
  - package.json: Dependencies and scripts
  - index.html: HTML entry point

```mermaid
graph TB
A["web/index.html"] --> B["web/src/main.tsx"]
B --> C["web/src/App.tsx"]
C --> D["web/src/components/*"]
C --> E["web/src/store/appStore.ts"]
C --> F["web/src/lib/api.ts"]
C --> G["web/src/lib/device.ts"]
C --> H["web/src/types.ts"]
I["web/vite.config.ts"] --> J["Build Output"]
K["web/tailwind.config.js"] --> L["Tailwind Styles"]
M["web/postcss.config.js"] --> L
N["web/tsconfig.json"] --> O["TypeScript Compilation"]
P["web/package.json"] --> Q["Dependencies & Scripts"]
```

**Diagram sources**
- [index.html](file://web/index.html)
- [main.tsx](file://web/src/main.tsx)
- [App.tsx](file://web/src/App.tsx)
- [api.ts](file://web/src/lib/api.ts)
- [device.ts](file://web/src/lib/device.ts)
- [appStore.ts](file://web/src/store/appStore.ts)
- [types.ts](file://web/src/types.ts)
- [vite.config.ts](file://web/vite.config.ts)
- [tailwind.config.js](file://web/tailwind.config.js)
- [postcss.config.js](file://web/postcss.config.js)
- [tsconfig.json](file://web/tsconfig.json)
- [package.json](file://web/package.json)

**Section sources**
- [package.json](file://web/package.json)
- [vite.config.ts](file://web/vite.config.ts)
- [tsconfig.json](file://web/tsconfig.json)
- [tailwind.config.js](file://web/tailwind.config.js)
- [postcss.config.js](file://web/postcss.config.js)
- [index.html](file://web/index.html)
- [main.tsx](file://web/src/main.tsx)
- [App.tsx](file://web/src/App.tsx)
- [types.ts](file://web/src/types.ts)
- [api.ts](file://web/src/lib/api.ts)
- [device.ts](file://web/src/lib/device.ts)
- [appStore.ts](file://web/src/store/appStore.ts)

## Core Components
Key UI components include:
- TopBar: Navigation and header controls
- AuthModal: Authentication modal dialog
- AccountCenterModal: User account center modal
- FeedbackModal: Feedback submission modal
- InviteModal: Invitation management modal
- SystemMessagesModal: System messages display modal
- ToastContainer: Global toast notifications
- FooterInfoBar: Footer information bar

These components are designed to be reusable, composable, and typed with TypeScript. They consume global state from appStore.ts and interact with backend services through the api.ts client.

**Section sources**
- [TopBar.tsx](file://web/src/components/TopBar.tsx)
- [AuthModal.tsx](file://web/src/components/AuthModal.tsx)
- [AccountCenterModal.tsx](file://web/src/components/AccountCenterModal.tsx)
- [FeedbackModal.tsx](file://web/src/components/FeedbackModal.tsx)
- [InviteModal.tsx](file://web/src/components/InviteModal.tsx)
- [SystemMessagesModal.tsx](file://web/src/components/SystemMessagesModal.tsx)
- [ToastContainer.tsx](file://web/src/components/ToastContainer.tsx)
- [FooterInfoBar.tsx](file://web/src/components/FooterInfoBar.tsx)

## Architecture Overview
High-level architecture:
- Entry point: index.html loads the compiled bundle; main.tsx bootstraps React and renders App.tsx
- Root component: App.tsx orchestrates layout, routing, and context providers
- State management: appStore.ts provides global state via React Context API
- Data access: api.ts abstracts HTTP requests to the backend
- Utilities: device.ts provides device detection helpers
- Styling: Tailwind CSS configured via tailwind.config.js and processed by PostCSS
- Build tooling: Vite compiles TypeScript, bundles assets, and optimizes output

```mermaid
graph TB
subgraph "Entry"
HTML["index.html"]
Main["main.tsx"]
end
subgraph "Application"
App["App.tsx"]
Store["store/appStore.ts"]
Types["types.ts"]
end
subgraph "UI Components"
TopBarC["components/TopBar.tsx"]
AuthC["components/AuthModal.tsx"]
AccountC["components/AccountCenterModal.tsx"]
FeedbackC["components/FeedbackModal.tsx"]
InviteC["components/InviteModal.tsx"]
SysMsgC["components/SystemMessagesModal.tsx"]
ToastC["components/ToastContainer.tsx"]
FooterC["components/FooterInfoBar.tsx"]
end
subgraph "Data Access"
Api["lib/api.ts"]
Device["lib/device.ts"]
end
subgraph "Build & Config"
Vite["vite.config.ts"]
Tailwind["tailwind.config.js"]
PostCSS["postcss.config.js"]
TSConf["tsconfig.json"]
Pkg["package.json"]
end
HTML --> Main --> App
App --> Store
App --> Types
App --> TopBarC
App --> AuthC
App --> AccountC
App --> FeedbackC
App --> InviteC
App --> SysMsgC
App --> ToastC
App --> FooterC
App --> Api
App --> Device
Vite --> App
Tailwind --> App
PostCSS --> App
TSConf --> App
Pkg --> App
```

**Diagram sources**
- [index.html](file://web/index.html)
- [main.tsx](file://web/src/main.tsx)
- [App.tsx](file://web/src/App.tsx)
- [appStore.ts](file://web/src/store/appStore.ts)
- [types.ts](file://web/src/types.ts)
- [TopBar.tsx](file://web/src/components/TopBar.tsx)
- [AuthModal.tsx](file://web/src/components/AuthModal.tsx)
- [AccountCenterModal.tsx](file://web/src/components/AccountCenterModal.tsx)
- [FeedbackModal.tsx](file://web/src/components/FeedbackModal.tsx)
- [InviteModal.tsx](file://web/src/components/InviteModal.tsx)
- [SystemMessagesModal.tsx](file://web/src/components/SystemMessagesModal.tsx)
- [ToastContainer.tsx](file://web/src/components/ToastContainer.tsx)
- [FooterInfoBar.tsx](file://web/src/components/FooterInfoBar.tsx)
- [api.ts](file://web/src/lib/api.ts)
- [device.ts](file://web/src/lib/device.ts)
- [vite.config.ts](file://web/vite.config.ts)
- [tailwind.config.js](file://web/tailwind.config.js)
- [postcss.config.js](file://web/postcss.config.js)
- [tsconfig.json](file://web/tsconfig.json)
- [package.json](file://web/package.json)

## Detailed Component Analysis

### Component Hierarchy and Relationships
The root component App.tsx composes the primary UI components and wires them together. The following class diagram shows representative relationships among key components and shared modules.

```mermaid
classDiagram
class App {
+render() JSX.Element
+provideContext() void
}
class TopBar {
+onNavigate(path) void
+onToggleMenu() void
}
class AuthModal {
+isOpen boolean
+onClose() void
+onSubmit(credentials) void
}
class AccountCenterModal {
+isOpen boolean
+onClose() void
+loadProfile() void
}
class FeedbackModal {
+isOpen boolean
+onClose() void
+submitFeedback(data) void
}
class InviteModal {
+isOpen boolean
+onClose() void
+generateInvite(code) void
}
class SystemMessagesModal {
+isOpen boolean
+onClose() void
+fetchMessages() void
}
class ToastContainer {
+toasts Array
+addToast(message, type) void
+removeToast(id) void
}
class FooterInfoBar {
+render() JSX.Element
}
class AppStore {
+state Object
+dispatch(action) void
}
class ApiClient {
+get(url) Promise
+post(url, body) Promise
+put(url, body) Promise
+delete(url) Promise
}
class DeviceUtils {
+isMobile() boolean
+isTablet() boolean
+getUserAgent() string
}
App --> TopBar : "renders"
App --> AuthModal : "renders"
App --> AccountCenterModal : "renders"
App --> FeedbackModal : "renders"
App --> InviteModal : "renders"
App --> SystemMessagesModal : "renders"
App --> ToastContainer : "renders"
App --> FooterInfoBar : "renders"
App --> AppStore : "consumes"
App --> ApiClient : "uses"
App --> DeviceUtils : "uses"
```

**Diagram sources**
- [App.tsx](file://web/src/App.tsx)
- [TopBar.tsx](file://web/src/components/TopBar.tsx)
- [AuthModal.tsx](file://web/src/components/AuthModal.tsx)
- [AccountCenterModal.tsx](file://web/src/components/AccountCenterModal.tsx)
- [FeedbackModal.tsx](file://web/src/components/FeedbackModal.tsx)
- [InviteModal.tsx](file://web/src/components/InviteModal.tsx)
- [SystemMessagesModal.tsx](file://web/src/components/SystemMessagesModal.tsx)
- [ToastContainer.tsx](file://web/src/components/ToastContainer.tsx)
- [FooterInfoBar.tsx](file://web/src/components/FooterInfoBar.tsx)
- [appStore.ts](file://web/src/store/appStore.ts)
- [api.ts](file://web/src/lib/api.ts)
- [device.ts](file://web/src/lib/device.ts)

**Section sources**
- [App.tsx](file://web/src/App.tsx)
- [TopBar.tsx](file://web/src/components/TopBar.tsx)
- [AuthModal.tsx](file://web/src/components/AuthModal.tsx)
- [AccountCenterModal.tsx](file://web/src/components/AccountCenterModal.tsx)
- [FeedbackModal.tsx](file://web/src/components/FeedbackModal.tsx)
- [InviteModal.tsx](file://web/src/components/InviteModal.tsx)
- [SystemMessagesModal.tsx](file://web/src/components/SystemMessagesModal.tsx)
- [ToastContainer.tsx](file://web/src/components/ToastContainer.tsx)
- [FooterInfoBar.tsx](file://web/src/components/FooterInfoBar.tsx)
- [appStore.ts](file://web/src/store/appStore.ts)
- [api.ts](file://web/src/lib/api.ts)
- [device.ts](file://web/src/lib/device.ts)

### State Management with Context API
Global state is centralized in appStore.ts and provided to the component tree via React Context. Components subscribe to relevant slices of state and dispatch actions to update it. This approach avoids prop drilling and keeps UI behavior predictable.

```mermaid
sequenceDiagram
participant UI as "Component"
participant Store as "appStore.ts"
participant API as "api.ts"
participant Backend as "Backend Service"
UI->>Store : "dispatch(action)"
Store->>Store : "update state"
Store-->>UI : "re-render with new state"
UI->>API : "request(data)"
API->>Backend : "HTTP call"
Backend-->>API : "response"
API-->>UI : "result or error"
UI->>Store : "dispatch(setResult(result))"
Store-->>UI : "re-render with updated state"
```

**Diagram sources**
- [appStore.ts](file://web/src/store/appStore.ts)
- [api.ts](file://web/src/lib/api.ts)

**Section sources**
- [appStore.ts](file://web/src/store/appStore.ts)
- [api.ts](file://web/src/lib/api.ts)

### API Client Abstraction Layer
The API client in api.ts encapsulates HTTP operations, request/response transformations, and error handling. Components should not call fetch directly; instead, they use typed methods exposed by the client.

```mermaid
flowchart TD
Start(["Component calls API method"]) --> BuildRequest["Build request URL and headers"]
BuildRequest --> Send["Send HTTP request"]
Send --> Response{"Response OK?"}
Response --> |Yes| Transform["Transform response to typed model"]
Response --> |No| HandleError["Normalize error and throw"]
Transform --> Return["Return result to caller"]
HandleError --> Return
```

**Diagram sources**
- [api.ts](file://web/src/lib/api.ts)

**Section sources**
- [api.ts](file://web/src/lib/api.ts)

### Routing Strategy
Routing is managed within App.tsx. Depending on implementation, this may involve conditional rendering based on URL path or integration with a router library. The root component composes page-level components and navigational elements like TopBar.

```mermaid
sequenceDiagram
participant Browser as "Browser"
participant Router as "App.tsx"
participant PageA as "Page A Component"
participant PageB as "Page B Component"
Browser->>Router : "Navigate to /path"
Router->>Router : "Match route"
alt "Route matches Page A"
Router->>PageA : "Render"
else "Route matches Page B"
Router->>PageB : "Render"
end
```

**Diagram sources**
- [App.tsx](file://web/src/App.tsx)

**Section sources**
- [App.tsx](file://web/src/App.tsx)

### Event Handling Mechanisms
Components handle user interactions (clicks, form submissions, toggles) and propagate events upward to parent components or dispatch actions to the global store. Modal components typically expose open/close callbacks and submit handlers.

```mermaid
sequenceDiagram
participant User as "User"
participant Modal as "AuthModal.tsx"
participant Parent as "Parent Component"
participant Store as "appStore.ts"
User->>Modal : "Click Submit"
Modal->>Parent : "onSubmit(credentials)"
Parent->>Store : "dispatch(login(credentials))"
Store-->>Parent : "state updated"
Parent-->>Modal : "props updated (e.g., close modal)"
```

**Diagram sources**
- [AuthModal.tsx](file://web/src/components/AuthModal.tsx)
- [appStore.ts](file://web/src/store/appStore.ts)

**Section sources**
- [AuthModal.tsx](file://web/src/components/AuthModal.tsx)
- [appStore.ts](file://web/src/store/appStore.ts)

### Responsive Design Considerations
Responsive behavior is implemented using Tailwind CSS utility classes configured via tailwind.config.js. Breakpoints and custom themes can be extended to support mobile-first layouts. Device detection utilities in device.ts can inform conditional rendering or feature toggles.

```mermaid
flowchart TD
Viewport["Viewport Size"] --> Detect["Tailwind Breakpoints"]
Detect --> ApplyClasses["Apply responsive classes"]
ApplyClasses --> Layout["Layout Adjustments"]
Layout --> UX["Improved UX across devices"]
```

**Diagram sources**
- [tailwind.config.js](file://web/tailwind.config.js)
- [device.ts](file://web/src/lib/device.ts)

**Section sources**
- [tailwind.config.js](file://web/tailwind.config.js)
- [device.ts](file://web/src/lib/device.ts)

### Cross-Browser Compatibility Strategies
Compatibility is ensured by:
- Using modern browser APIs with appropriate fallbacks
- Leveraging Vite’s built-in polyfills and transpilation via tsconfig.json
- Testing across major browsers during development and CI
- Avoiding experimental features without fallbacks

[No sources needed since this section provides general guidance]

## Dependency Analysis
The following dependency graph highlights core module relationships and external tooling.

```mermaid
graph TB
App["App.tsx"] --> Store["store/appStore.ts"]
App --> Api["lib/api.ts"]
App --> Device["lib/device.ts"]
App --> Types["types.ts"]
App --> CompTop["components/TopBar.tsx"]
App --> CompAuth["components/AuthModal.tsx"]
App --> CompAccount["components/AccountCenterModal.tsx"]
App --> CompFeedback["components/FeedbackModal.tsx"]
App --> CompInvite["components/InviteModal.tsx"]
App --> CompSysMsg["components/SystemMessagesModal.tsx"]
App --> CompToast["components/ToastContainer.tsx"]
App --> CompFooter["components/FooterInfoBar.tsx"]
Vite["vite.config.ts"] --> App
Tailwind["tailwind.config.js"] --> App
PostCSS["postcss.config.js"] --> App
TSConf["tsconfig.json"] --> App
Pkg["package.json"] --> App
```

**Diagram sources**
- [App.tsx](file://web/src/App.tsx)
- [appStore.ts](file://web/src/store/appStore.ts)
- [api.ts](file://web/src/lib/api.ts)
- [device.ts](file://web/src/lib/device.ts)
- [types.ts](file://web/src/types.ts)
- [TopBar.tsx](file://web/src/components/TopBar.tsx)
- [AuthModal.tsx](file://web/src/components/AuthModal.tsx)
- [AccountCenterModal.tsx](file://web/src/components/AccountCenterModal.tsx)
- [FeedbackModal.tsx](file://web/src/components/FeedbackModal.tsx)
- [InviteModal.tsx](file://web/src/components/InviteModal.tsx)
- [SystemMessagesModal.tsx](file://web/src/components/SystemMessagesModal.tsx)
- [ToastContainer.tsx](file://web/src/components/ToastContainer.tsx)
- [FooterInfoBar.tsx](file://web/src/components/FooterInfoBar.tsx)
- [vite.config.ts](file://web/vite.config.ts)
- [tailwind.config.js](file://web/tailwind.config.js)
- [postcss.config.js](file://web/postcss.config.js)
- [tsconfig.json](file://web/tsconfig.json)
- [package.json](file://web/package.json)

**Section sources**
- [App.tsx](file://web/src/App.tsx)
- [appStore.ts](file://web/src/store/appStore.ts)
- [api.ts](file://web/src/lib/api.ts)
- [device.ts](file://web/src/lib/device.ts)
- [types.ts](file://web/src/types.ts)
- [TopBar.tsx](file://web/src/components/TopBar.tsx)
- [AuthModal.tsx](file://web/src/components/AuthModal.tsx)
- [AccountCenterModal.tsx](file://web/src/components/AccountCenterModal.tsx)
- [FeedbackModal.tsx](file://web/src/components/FeedbackModal.tsx)
- [InviteModal.tsx](file://web/src/components/InviteModal.tsx)
- [SystemMessagesModal.tsx](file://web/src/components/SystemMessagesModal.tsx)
- [ToastContainer.tsx](file://web/src/components/ToastContainer.tsx)
- [FooterInfoBar.tsx](file://web/src/components/FooterInfoBar.tsx)
- [vite.config.ts](file://web/vite.config.ts)
- [tailwind.config.js](file://web/tailwind.config.js)
- [postcss.config.js](file://web/postcss.config.js)
- [tsconfig.json](file://web/tsconfig.json)
- [package.json](file://web/package.json)

## Performance Considerations
- Code splitting and lazy loading for routes and heavy components
- Memoization with React.memo and useMemo where appropriate
- Efficient state updates via minimal re-renders and selective subscriptions
- Asset optimization via Vite’s bundling and caching strategies
- Debouncing/throttling for frequent user interactions (e.g., search inputs)
- Minimizing network payloads and leveraging caching headers

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- Build errors: Verify TypeScript configuration and import paths; ensure dependencies match package.json
- Runtime errors: Check API client error normalization and network connectivity
- State inconsistencies: Ensure actions are dispatched correctly and reducers update state immutably
- Styling conflicts: Validate Tailwind directives and purge unused styles in production builds
- Modal visibility: Confirm open/close props and event handlers are wired properly

**Section sources**
- [api.ts](file://web/src/lib/api.ts)
- [appStore.ts](file://web/src/store/appStore.ts)
- [AuthModal.tsx](file://web/src/components/AuthModal.tsx)
- [tailwind.config.js](file://web/tailwind.config.js)
- [tsconfig.json](file://web/tsconfig.json)
- [package.json](file://web/package.json)

## Conclusion
The frontend follows a clean, modular architecture centered around React and TypeScript. Global state is managed via Context API, while the API client abstracts data access. Vite powers fast builds and development, and Tailwind CSS enables responsive design. The component hierarchy promotes reusability and maintainability, with clear separation between UI, business logic, and data layers. Adhering to the outlined best practices ensures scalability, performance, and cross-browser compatibility.
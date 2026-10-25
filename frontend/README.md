# RAGNAROK — Medieval Intelligence Archive Dashboard (Frontend)

Interactive strategic frontend dashboard for **RAGNAROK — Trial of the Nine Realms: Supply Chain Disruption Impact Analyzer**, integrated with the FastAPI backend.

The interface is designed with a **minimalist, refined medieval-inspired royal intelligence archive** aesthetic: warm parchment backgrounds, aged ivory documents, ink-dark navigation, subtle antique-gold accents, and modern high-density analytics hierarchy.

---

## Visual Direction & Design System

- **Obsidian ink:** `#191A18` — Navigation, dark surface layers, high-contrast headings.
- **Warm parchment:** `#F4F0E6` — Primary canvas background.
- **Aged ivory:** `#FFFCF5` — Content surfaces, document scrolls, cards.
- **Antique gold:** `#A8874A` — Accents, badges, active selection rings, crests.
- **Weathered stone:** `#D8D0C0` — Subtle dividers, borders, chip backgrounds.
- **Forest green:** `#435747` — Established findings, sufficient evidence, healthy service.
- **Muted oxblood:** `#793F3F` — Conceded claims, evidence gaps, adverse alerts.
- **Slate ink:** `#5C605A` — Secondary metadata, timestamps, captions.

### Typography
- **Headings & Display:** `Cinzel` & `Cormorant Garamond` (Google Fonts).
- **Body & Forms:** `Inter` (Readable modern sans-serif).
- **Technical & Citations:** `JetBrains Mono` (Monospaced IDs, timestamps, document tags).

---

## Application Structure (The 5 Archival Halls)

1. **The Hall of Deliberation (`the-hall`)**: Real-time overview of cataloged disruptions, completed deliberations, backend health, and quick filing action.
2. **Case Dossier (`case-dossier`)**: Detailed inquiry inspection, temporal clock cutoff (`as_of_date`), Runemark event ID, and the **Convene Council** control with bounded sufficiency retries configuration (`max_retries`).
3. **Council Verdict (`council-verdict`)**: Odin's authoritative judicial adjudication, sufficiency verdict, calibrated confidence, claim rulings table (Established / Contested / Conceded), reasoning, and supporting citations.
4. **Trial Chronicle (`trial-chronicle`)**: Chronological audit timeline across multi-trial retry loops. Expands Heimdall verification, Thor advocacy, Loki defense, Round 2 cross-examination attacks, and formal concessions.
5. **Executive Scroll (`executive-scroll`)**: Complete royal intelligence briefing report, including chronological timeline, disruption scope, quantitative exposure comparison table, forward outlook, qualified recommendations, and bibliography. Features print-friendly styling.

---

## Quickstart & Local Development

### Prerequisites
- Node.js `v18+` (tested on Node `v24.15.0`)
- npm `v10+`

### 1. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Default value:
```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

### 2. Install Dependencies
```bash
npm install
```

### 3. Run Development Server
```bash
npm run dev
```
The application will launch at `http://localhost:5173`. Requests to `/health` and `/cases` are proxied to `http://127.0.0.1:8000`.

### 4. Run Test Suite
```bash
npm run test
```
Executes all unit and component tests with Vitest and `@testing-library/react`.

### 5. Type-Check and Production Build
```bash
npm run build
```
Type-checks via `tsc -b` and bundles with Vite into `dist/`.

### 6. Lint
```bash
npm run lint
```
Lints TypeScript and TSX files with Oxlint.

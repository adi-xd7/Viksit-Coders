# RAGNAROK — Trial of the Nine Realms (Frontend)

Interactive strategic frontend dashboard for **RAGNAROK — Trial of the Nine Realms: Supply Chain Disruption Impact Analyzer**, integrated with the FastAPI backend.

The interface combines a **minimalist, refined medieval-inspired royal intelligence archive** with deep **forensic pipeline, exposure, and evidence analysis tools**.

---

## Architecture & Views

### 1. Royal Archive Deliberation Suite
- **The Hall of Deliberation (`the-hall`)**: Real-time overview of cataloged disruptions, completed deliberations, backend health, and quick filing action.
- **Case Dossier (`case-dossier`)**: Detailed inquiry inspection, temporal clock cutoff (`as_of_date`), Runemark event ID, and the **Convene Council** control with bounded sufficiency retries configuration (`max_retries`).
- **Council Verdict (`council-verdict`)**: Odin's authoritative judicial adjudication, sufficiency verdict, calibrated confidence, claim rulings table (Established / Contested / Conceded), reasoning, and supporting citations.
- **Trial Chronicle (`trial-chronicle`)**: Chronological audit timeline across multi-trial retry loops. Expands Heimdall verification, Thor advocacy, Loki defense, Round 2 cross-examination attacks, and formal concessions.
- **Executive Scroll (`executive-scroll`)**: Complete royal intelligence briefing report, including chronological timeline, disruption scope, quantitative exposure comparison table, forward outlook, qualified recommendations, and bibliography. Features print-friendly styling.

### 2. Forensic Pipeline Suite
- **Trial View (`trial`)**: Rulings ledger, Thor / Loki claim columns, cross-examination attacks, defenses, and concessions.
- **Exposure View (`exposure`)**: Quantitative exposure table on a shared scale; Thor / Loki / Odin bounds, unit definitions, assumptions, and calculation records.
- **Evidence & Trade Archive (`evidence`)**: Publication timeline with as-of date cutoff line, document inspection, flagged injection spans, and trade table analysis.
- **Run Trace (`trace`)**: Odin sendback records, Heimdall query plans, memory state transitions, sufficiency evaluations, and raw audit event logs.

---

## Design System & Tokens (`src/index.css`, `src/App.css`)

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
- **Body & Forms:** `Inter` & `Hanken Grotesk`.
- **Technical & Citations:** `JetBrains Mono` & `IBM Plex Mono`.

---

## Local Development

```bash
# 1. Install dependencies
npm install

# 2. Run dev server (http://localhost:5173)
npm run dev

# 3. Type check & build
npm run build

# 4. Run tests
npm test
```

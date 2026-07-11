# GRAM Scope design QA

Source visual truth: `qa/antigravity-reference.png`  
Implementation screenshot: `qa/gram-scope-landing-light.png`  
Combined comparison: `qa/landing-comparison.png`  
Internal workflow screenshot: `qa/gram-scope-activity-light.png`  
Mobile screenshots: `qa/gram-scope-mobile-landing.png`, `qa/gram-scope-mobile-activity.png`  
Viewport: 1280 × 720 desktop and 390 × 844 mobile  
State: light landing; light Activity empty state; persisted-run and dark-theme states also exercised in the in-app browser.

## Full-view comparison evidence

The side-by-side comparison confirms that the implementation preserves the selected reference's core visual behavior: sparse top navigation, large centered low-contrast typography, generous whitespace, black pill-shaped primary action, restrained supporting copy, and a small field of colored particles entering from the lower/right edge. GRAM Scope intentionally replaces the reference's download conversion with a wallet-search conversion and introduces product-specific evidence cards below the fold.

## Focused region comparison evidence

A separate crop was not required because the 1280 × 720 original-scale comparison keeps the hero typography, wallet input, primary CTA, top brand area, color treatment, radii, and first supporting-card row readable. The internal Activity surface was evaluated separately because it has no equivalent in the marketing reference.

## Required fidelity surfaces

- Fonts and typography: local Manrope variable font provides the wide geometric display feel and readable small UI weights. Hero hierarchy, line breaks, letter spacing, and compact interface labels remain consistent in light and dark themes.
- Spacing and layout rhythm: landing proportions match the reference's open composition. The application uses a stable 242 px navigation rail, compact sticky search header, 12–16 px card rhythm, and clear page-level separation.
- Colors and visual tokens: off-white/charcoal foundations use restrained blue, coral, aqua, and lilac accents. Semantic success, warning, error, mock, and real states remain distinct in both themes.
- Image quality and asset fidelity: the landing uses a project-local 1672 × 937 generated particle artwork with useful negative space. It is not stretched, substituted with CSS art, or used inside the dense application workflow.
- Copy and content: GRAM is used for the native currency and TON for the blockchain. Provider observations, cryptographic proof, mock mode, canonical outputs, and run warnings remain explicitly differentiated.

## Findings

No actionable P0, P1, or P2 findings remain.

No P3 findings are being carried into handoff. The chart package is lazy-loaded after an active run, leaving the initial application chunk below the default Vite advisory threshold.

## Comparison history

### Iteration 1

- Earlier P1: the redesigned shell embedded the legacy `WalletIngestionWorkspace`, so Activity fell back to the old dense interface.
- Fix: replaced the visible legacy workspace with a new guided Activity flow: wallet scope, time window, selectable surfaces, preview coverage, saved runs, persisted-run summary, result tabs, and clean tables.
- Post-fix evidence: `qa/gram-scope-activity-light.png`; browser interaction successfully previewed coverage, persisted run #35, opened run #34, and switched result tabs.

- Earlier P2: section changes retained the previous page scroll position, causing users to land halfway through Assets or Reports.
- Fix: centralized navigation and reset the document to the top on every section transition.
- Post-fix evidence: Reports, Assets & DEX, Data Sources, Overview, and Activity each reopened at their page heading in browser verification.

- Earlier P2: at 390 px the recent-run list appeared before the Activity builder, delaying the primary wallet input.
- Fix: kept the builder first on narrow layouts and limited the secondary recent-run list to three rows on mobile.
- Post-fix evidence: `qa/gram-scope-mobile-activity.png` shows the page heading and scope builder above the fold with no horizontal overflow.

## Interaction and state verification

- Landing wallet entry and address-free workspace entry.
- Light and dark theme toggles.
- Desktop section navigation and top-of-page reset.
- Coverage preview using the configured backend.
- Persisted evidence-run creation and recent-run refresh.
- Stored-run loading and Summary/Transfers tab switching.
- Assets & DEX data view, canonical report links, and provider-status cards.
- Empty states and fail-closed mock-mode banner.
- Responsive landing, Overview, and Activity layouts at 390 × 844.
- Browser console checked after mobile and desktop interaction passes: no warnings or errors.

## Implementation checklist

- [x] Reference-like light landing
- [x] Separate dark theme
- [x] General product overview before a run
- [x] New user-friendly Activity workflow
- [x] Real run-backed charts and tables
- [x] Clean Assets, Proofs, Reports, and Data Sources sections
- [x] GRAM/TON terminology separation
- [x] Desktop responsive rules and reduced-motion support
- [x] Frontend and backend regression suites

final result: passed

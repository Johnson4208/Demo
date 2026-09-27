# SolvAI 44.7.2 Verified Method Recalculation — Design QA

## Scope

- Risk Assessment Step 2 now defaults to automatic financial inputs and a long-holding outlook.
- Risk Assessment Step 3 now has four functional sizing modes instead of display-only reference choices.
- The main path exposes only company, shares held, average cost, holding period, and optional dividend reinvestment.
- Technical assumptions and verified financial overrides remain in one collapsed expert section.
- No dashboard, login, navigation, permission, or evidence-dialog surface was changed.

## Full-view comparison

The established SolvAI typography, light/navy palette, cards, borders, inputs, and sidebar are preserved. The valuation workspace uses the existing content grid, while automatic evidence, the projection chart, and three scenarios are progressively revealed only after calculation.

## Focused comparison

The step tracker retains the 44.6 interaction contract. Step 1 starts Current while Steps 2 and 3 are Locked; a successful review unlocks Step 2; a successful automatic valuation unlocks Step 3. Completed steps remain clickable and inputs remain populated.

## Findings

- The common path no longer asks users to understand discount rates, terminal growth, margins, leverage, EPS, or cash flow.
- Automatic, manual, and unavailable evidence states are visually distinct and described in text.
- Long-holding results lead with the base path and portfolio impact; methodology and limitations remain visible but subordinate.
- The three scenario cards and SVG projection chart reflow from three columns to one without changing calculation state.
- Selecting Fixed Fractional, Kelly, Half-Kelly, or Volatility Targeting updates the active banner, reveals only relevant inputs, and recalculates existing results.
- The capture-phase Calculate handler prevents the legacy request from replacing a method-aware result; every method switch requests its own explicit API mode with caching disabled.
- Allocation percentages remain comparable without account equity. Currency and unit estimates stay unavailable until the user supplies equity, avoiding invented personal amounts.
- Raw and applied allocations are both visible, with an explicit explanation when the cash-only cap makes different methods share the same applied result.
- R-multiple is visually separated as a reward-target rule; Risk Parity remains a Portfolio Risk action.
- The existing active/completed/locked step semantics remain intact.

## Required fidelity surfaces

- Fonts and typography: existing SolvAI family, weights, hierarchy, wrapping, and compact UI labels are preserved.
- Spacing and layout rhythm: the hero, tracker, command card, result card, and active workspace align to the existing content grid; no persistent controls overflow the viewport.
- Colors and tokens: the established navy/blue palette remains primary; existing green is reused only for completed states.
- Image quality and assets: no visual assets were added or replaced. The dashboard and login image remain untouched.
- Copy and content: step labels use task language—Risk overview, Core value, Position plan. The valuation CTA states that it calculates an outlook, not a recommendation.

## Interaction and accessibility checks

- Existing disabled-step and `aria-current` semantics remain covered by regression tests.
- Labels remain bound to every new input; the dividend option uses a native checkbox.
- The projection is summarized by adjacent text and scenario cards rather than depending on the SVG alone.
- Advanced assumptions use native `details`/`summary`, so keyboard access works without custom scripting.
- Reduced-motion rules continue to disable workflow animations.

## Comparison history

- Earlier density issue: all three risk workspaces and the sizing reference were visible together.
- 44.6 fix: stateful step navigation hid inactive panels and made progression explicit.
- 44.7 fix: the remaining valuation form is automatic by default; technical fields are kept behind one optional disclosure.

## Automated verification

- Python compilation: passed.
- JavaScript syntax: passed.
- CSS parser and selector contracts: passed.
- Long-holding engine tests cover growth fade, user share count, missing-price refusal, and route forwarding.
- Full data-independent suite: 182 passed, 9 skipped.
- Executable browser-event contract: passed for card change, explicit method parameter, capture-phase Calculate ownership, and no-store requests.

## Final result

final result: passed

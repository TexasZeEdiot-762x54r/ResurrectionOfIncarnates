# Source Status

Updated 2026-10-21. This describes the public source snapshot, not a deployed
release or an independently verified reconstruction of every original game rule.

## Recent Source Corrections

- The executable builder rejects output paths that alias its clean input,
  including file-identity aliases, while accepting a distinct existing output.
- Version-2 progression selectors reject invalid types consistently in the client
  and server validators; version-1 configuration behavior remains supported.
- Manifest readers reject duplicate JSON keys instead of silently selecting the
  last value. Duplicate-key input is rejected before manifest-refresh writes.
- Profile readers reject duplicate keys, including ambiguous balance and purchase
  fields, before an update can replace the original file. They do not guess which
  conflicting value is correct or migrate existing profiles.
- Debugger writes check protection changes, the complete written-byte count,
  protection restoration and instruction-cache flushing. Replacing a registered
  breakpoint handler preserves its original instruction and pending rearm state.
- Library Story heading presentation and regression coverage were corrected.
- Offline grid tests cover five current loadouts, independent placements, reuse
  of an inventory hold across alternate layouts, and rejection of placement-driven
  loadout creation or deletion. Saving a grid does not award unverified level rights.
- Circle-capacity transaction tests cover replay protection, lost replies,
  refunds and retention of ambiguous committed receipts for reconciliation.

These are source, fixture and mock checks. They do not establish native debugger
safety, a successful game session, cross-player acceptance or deployment. The
diagnostic cube fixture is not evidence of original inventory or balance rules.

## Progression Selectors

`faithful`, `fully_unlocked` and `match_xp` remain configuration/schema selectors
only. They are deliberately not connected to new-profile initialization or match
settlement. Selecting a mode grants no levels, cubes, grid cells, XP or LP and
does not alter drops or rewrite existing saves.

The proposed `fully_unlocked` startup subset is also deferred. Its intended
values remain account level 15, character level 1 and all 16 native grid cells,
but no implementation or deployment of those startup effects is included here.
Fully upgraded cube pieces and their exact caps remain unresolved.

## Recorded Revival Targets

The following are explicitly selected revival targets, not verified universal
original-game rules and not active gameplay behavior:

| Component | Target |
| --- | --- |
| Match XP | 8 for a loss, 10 for a win, or 16 for a win with highest damage; mutually exclusive and intended for both player/account and character XP. |
| LP score bonus | `floor(total_score * 0.20)`. |
| LP team bonus | Win/S: 4000; Win/A: 2400; Win/B: 1200; Loss/B: 200. Other combinations are unspecified. |
| LP battle bonus | 6000 for a win, 4000 for a loss. |

Trusted score/rating inputs, wallet settlement and replay authority, response
encoding and level-curve integration still need a supported contract. Do not
infer missing team bonuses or enable rewards from these recorded quantities.

## Unresolved Gameplay Evidence

- Original starter ownership, progression curves and exact reward schedules.
- The cube resource-to-master association, numeric caps and synthesis XP,
  duration and cost semantics.
- Exact grid expansion rewards, prices and original starting-cell coordinates.
  Native text supports the level-5 system unlock and manual Add Block selection;
  that does not establish a per-level expansion schedule.
- Consumable activation responses, expiry, stacking and reward effects. Recovered
  `useItem` requests submit `sv_holdIds`; an original active-effect response is not
  established. Current revival catalogue IDs do not prove original database IDs.
- Outstanding account/session, native gameplay and cross-player acceptance gates.

No original names, response contracts, prices, caps or reward curves should be
invented to fill those gaps. Missing evidence for one feature does not invalidate
an independently supported correction elsewhere.

## Publication Boundary

Machine-specific deployment values belong in ignored `deployment.local.json`
and generated settings, not in this repository. Profiles, credentials, runtime
logs, binary game files, local evidence records and private review checkpoints
are excluded from the publication inventory.

`PUBLICATION-REPORT.json` records the snapshot's validation results and limits.
Run the README's publication and package checks again after intentional edits.
Working-tree scans do not sanitize Git history or author metadata, and this
snapshot does not grant redistribution rights to third-party artwork or text.

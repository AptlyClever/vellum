# Unity intake — unpark decision (2026-07-14)

## Why it was parked

Fireworks Unreal MRQ capture was the active proof path. Unity was deferred so we
did not split attention across two engine capture stacks before one worked
end-to-end for the operator.

That reason is **mostly spent**: register + vault stage + texture lookdev derive
do not require Unreal. Parking Unity *entirely* was over-broad.

## What Unity should mean for Vellum (sanity)

| Layer | Unreal | Unity |
| --- | --- | --- |
| Redeem / store human gates | Humble → Epic/Fab | Humble → Unity / Asset Store |
| Stage into vault | Aurora `host_stage` (Content / Unity folder zip; `ue_stage` alias still claimable) | Same job kind; path from host package root |
| Texture / mesh still lookdev | `derive_lookdev` from staged png/jpg | Same worker — already engine-agnostic enough |
| Simulated VFX capture | MRQ + Sequencer (done for Niagara) | **Different** — not UE MRQ; do not pretend |

## Recommended unpark order

1. Reuse **Import pack** checklist for `engine=unity` (mark redeemed / in project / stage).
2. Stage via **`host_stage`** (generalized) — zip Unity package folder the same Python way; optional `unity_packages_dir` on host profile for folder picker.
3. Run **Derive texture stills** for staged Unity packs into project lanes.
4. Only later: decide if any Unity *runtime* lookdev capture is worth a second host agent.

## Still deferred

- Automating Unity Editor package import UI.
- Particle/VFX fidelity capture parity with Niagara MRQ.

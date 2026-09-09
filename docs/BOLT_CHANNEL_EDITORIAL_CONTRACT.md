# Bolt illustrated channels

One production system, two editorial profiles. `topic_fit.py` owns their definitions and the
free research queue exposed at `/api/explainer/channels`.

| Channel | Episode promise | Boundary |
|---|---|---|
| Bolt Explains the World | What humans did to animal populations, and what happened next | One implemented bounty, eradication, introduction or predator-removal intervention, with documented aftermath |
| Bolt Explains History | One historical government program: its goal, operation and human cost | One identifiable law, decree, campaign or state project with documented harm; success at its stated goal does not disqualify it |

Animal interventions take priority even when governments organized them. The sparrow campaign
belongs only on World. A program that incidentally damages a fishery, such as the Aral Sea
irrigation diversions, belongs on History.

World excludes general wildlife facts, quizzes, meat explainers and unrealized proposals. The
American hippo proposal remains an engineering experiment, outside the launch queue. History
excludes current commentary, general biographies, unrelated wars, celebrity stories and corporate
scandals. Wells Fargo and the Streisand effect belong to neither channel.

Banner lines:
- World: **ANIMAL CONTROL. UNEXPECTED CONSEQUENCES.**
- History: **GOVERNMENT PLANS. HUMAN CONSEQUENCES.**

## Sequence and launch queue

Choose channel → check fit → establish facts → choose supported structure → produce.

The engine selector receives the researched claim ledger. A reference teaches structure and
pacing; it is not evidence about this episode and does not decide channel eligibility. The topic
screen is advisory on provider failure. An UNKNOWN verdict is not evidence of fit. A positive
wrong-channel result asks the operator to select the correct channel before research is bought.

Initial research sequence:
- World: Hanoi, Four Pests sparrows, cane toads, Hawaiian mongooses.
- History: Aral Sea irrigation diversions, Prohibition industrial-alcohol denaturing, Decree 770.

All seven UI starters are research candidates, not pre-approved historical claims. Existing Hanoi
material may be reused after its evidence and delivery records are inspected. Hoy No Circula
remains pending evidence resolution. Dust Bowl requires a specific program before eligibility can
be assessed. Keep the first six story uploads per channel within these boundaries; this is an
editorial experiment, not an algorithm threshold. Shorts should adapt the same niche. The current
illustrated endpoint supports landscape only, so the topic UI prepares a 90-second landscape
story; the legacy social/quiz controls are not an illustrated Shorts implementation.

## Corpus coverage and verification, 2026-09-09

Reviewed main `b114d69` and open PR #87 at `8e3c597`. The PR reports a 79.9-second Hanoi render,
graded 74, with gates enabled. This review did not independently inspect that live MP4. Main does
not yet include PR #87's channel and ecosystem-engine changes.

| Engine | Packaged references after this repair | Factual function map | Status |
|---|---:|---|---|
| backfiring_solution | 2 | Yes | PR #87 reports Hanoi live delivery; offline compiled delivery verified again |
| accumulating_indictment | 2 | No | Role assignment path; new History launch episodes need live verification |
| removed_keystone | 0 | Yes | No borrowed blueprint; structural tests pass; live narration overshoots remain reported in PR #87 |
| almost_happened_plan | 1, operator-written | Yes | Engineering capability, outside launch niches |
| power_reversal | 2 | No | Capability does not imply editorial eligibility |
| accidental_invention | 0 | No | Unproven and outside the current launch queue |

“Outside the corpus” needs a precise measurement:
1. A new topic using a referenced structure tests topic generalization.
2. An engine with zero references, such as `removed_keystone`, tests a new story shape.
3. `BLUEPRINT_ADHERENCE=off` disables retrieved blueprint text, but the engine contracts and
   evidence checks still run. It is not an unrestricted illustrated pipeline.

The package previously omitted `topic_fit.py` and `cobra_bounty_short.json`; the latter changed
backfiring-solution adherence from balanced in the checkout to loose after installation. Both
now ship, and the installed-wheel check asserts the same seven references and coverage.

Additional repairs: channel-aware UI selection and request metadata, old science-cache rejection,
explicit research-candidate labels, correct illustrated defaults, evidence supplied to engine
selection, removal of the stale mandatory-inversion error, and consistent engine-specific
escalation counts in planning and runtime feasibility.

## Next live canary

`spec/cane_toads_non_corpus_canary_request.json` is a **non-spending proposal request body** for
one 90-second animal-channel video, with a proposed $5 ceiling. It is not an approved action and
has no action/job ID. The server's current immutable recipe, provider manifest and motion allowance
must be reviewed on the resulting approval card; prose does not override those settings.

After deploying the reviewed branch:
1. Check production readiness, then POST that body to `/api/agent/actions` without making provider
   calls. Confirm that the deployment actually contains PR #87 and this repair.
2. Follow `AGENTS.md`: the operator approves the exact immutable hash and ceiling once. Creation
   does not authorize a paid render. Do not approve on the operator's behalf.
3. Run and monitor the bound job. Record the selected engine and retrieved reference count. The
   new-shape test qualifies only if `removed_keystone` is actually selected with zero references;
   do not call a different selected engine a non-corpus success.
4. Report supported facts, narration entailment, storyboard result, actual spend, runtime, shot
   count, technical status, automatic/editorial grades, and final downloadable artifact. A failed
   story remains failed; no budget or evidence override is part of this test.

The local compiled-delivery test rendered and downloaded an actual MP4 through worker restart
using simulated providers/storage. It exercises the Hanoi/backfiring path. It does not establish
that a fresh cane-toad script or an unreferenced engine will render successfully. Local browser
preview was blocked by the browser URL policy; JavaScript syntax and API behavior were checked.

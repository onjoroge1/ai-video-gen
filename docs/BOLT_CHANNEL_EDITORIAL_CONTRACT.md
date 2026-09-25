# Bolt illustrated channels

One production system, three editorial profiles. `topic_fit.py` owns their definitions and the
free research queue exposed at `/api/explainer/channels`.

| Channel | Episode promise | Boundary |
|---|---|---|
| Bolt Explains the World | What humans did to animal populations, and what happened next | One implemented bounty, eradication, introduction or predator-removal intervention, with documented aftermath |
| Bolt Explains History | One historical government program: its goal, operation and human cost | One identifiable law, decree, campaign or state project with documented harm; success at its stated goal does not disqualify it |
| Bolt Explains Nature | Why [animal] is a terrible parent, and why the young are the reason | One species, one documented behaviour toward its eggs or young that someone on the record read as neglect, cruelty, theft or abandonment, and the evidence that corrected the reading. No human intervention in the chain |

Nature is the series "Why [animal] is a terrible parent" (banner: **TERRIBLE PARENTS. PERFECT
STRATEGY.**). It admits two story shapes, and an episode must say which it is:

- `mistaken_verdict` (added 2026-09-23 from the Oviraptor Short): someone on the record read the
  behaviour as theft, neglect or cruelty, the reading hardened into a name or a label, and
  evidence overturned it. The load-bearing requirement is the RECORDED verdict.
- `strange_behaviour` (added 2026-09-24 from the emperor penguin draft): the behaviour merely
  LOOKS like abandonment or cruelty; the constraint that makes it necessary and its documented
  function for the young are shown. No accusation is attributed to anyone.

The second shape exists because the penguin draft tried to satisfy the first with "the lists call
her the worst mother", and when the lists were actually read they made no such accusation. An
invented reputation is worse than no story. Human programmes that harmed animals stay on World.

The channel also restricts the engine selector: a Nature run (`topic_channel=nature`) is offered
only these two engines (`topic_fit.CHANNEL_ENGINES`), so a selector choosing "by how the story
turns" cannot hand a penguin a bounty engine. World and History stay unrestricted, as measured.

**Three source gates, kept separate.** Finding a source is not reading it, and reading it is not
confirming that it supports the exact claim. Every claim ledger in a Nature brief carries a
status of `found`, `read`, or `confirms exact claim`, and a claim the narration depends on must
reach the third before a clip is bought. The penguin draft passed offline story validation while
its verdict claim sat at `found`; validation checks shape, not truth, and the two must not be
confused.

**Nature render rules (`nature_channel.py`).** The illustrated lane's defaults were written for
history references and leaked into the first penguin long-form (job 59d6106d, 2026-09-24). On
`topic_channel=nature`, and only there, the pipeline now: speaks no "explained like you are
five" lead tag; puts no people in any image state (the animal performs the verb; the state's
forbidden objects name humans and human equipment, so the verifier redraws a frame with a
person in it); carries a subject sheet, one model call fixing the adult, egg and young's look,
into every evidence prompt; refuses to render a script under the 70 quality floor instead of
logging it as degraded; and rejects a thumbnail headline whose number the narration never
speaks, with a threat drawn as weather, distance or hunger rather than a skull. World and
History read none of these rules. A request may also set `stop_after_script`, which halts after
the last pre-spend gate with the narration written to `script_for_approval.md`; the approved
rerun reuses the cached script.

**Nature writing contract (`nature_channel.WRITING_RULES`).** The flow is the illustrated causal
long-form lane (Illustrated Story v1) run under the Nature channel's engines; an episode is a
"Terrible Parents" episode. Its standing rules, injected beside the operator direction on this
channel only: one opening hook of three sentences (the episode question, the specific behaviour,
the problem the video resolves); the titled animal and behaviour stay central and a side
mechanism gets one compact explanation; every beat adds a new action, constraint, consequence,
mechanism or interpretation, and a rephrased fact is not a beat; an escalation changes the
problem and a reversal changes the interpretation; explain the behaviour early enough to be
honest and never show an unprotected egg to correct it later; narration is not visual direction;
claims are qualified and precise measurements that do not advance the parent's story are
omitted; one verdict, on the image of the young being fed, and the evidence decides it. Not
every episode acquits the parent.

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

Initial launch sequence:
- World: Hanoi, Four Pests sparrows, cane toads, Hawaiian mongooses.
- History: Aral Sea irrigation diversions, Prohibition industrial-alcohol denaturing, Decree 770.

The expanded UI research queue also includes American-history candidates. World receives only
animal-targeted interventions (including Yellowstone wolves, European starlings, nutria,
mosquitofish and Asian carp). History receives specifically named government laws, campaigns,
projects or administrative decisions (including redlining, urban renewal, highways, the GI Bill,
sentencing policy, COINTELPRO, Tuskegee, Flint and federal fire suppression). Broad subjects were
narrowed to an identifiable intervention; company towns and other purely corporate stories remain
outside the channel contract.

All UI starters are research candidates, not pre-approved historical claims. Existing Hanoi
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
| mistaken_verdict | 1 (operator-produced Short, 2026-09-23) | Yes | Nature channel; the reference was written to the engine, so it teaches the shape rather than observing it. No long-form live run yet; a filmed second reference is the next correction |
| strange_behaviour | 1 (operator-produced Short, 2026-09-24) | Yes | Nature channel's second shape; the emperor penguin Short is its reference, written to the engine after review. Loose adherence until a second reference exists |

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

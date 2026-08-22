# Bolt Long-Form Explainer Roadmap

Version 1.0 — release contract for the third long-form explainer rebuild

## 1. Product outcome

Build long-form science explainers that viewers experience as a developing human story supported by visible evidence, not as a narrated list of consequences or a slideshow of topic illustrations.

The recurring human subject leads the story. Bolt remains an important supporting character, but appears only when his presence performs useful story work: measuring, demonstrating, warning, reacting, helping, or participating in a decision. Bolt is neither removed nor used as a decorative watermark.

Success means the rendered video—not its planner metadata—makes the following legible:

1. Who the human subject is.
2. What the subject wants.
3. What concrete anomaly interrupts that goal.
4. What the subject initially believes.
5. What visible evidence challenges that belief.
6. What decision the evidence causes.
7. What question pulls the viewer into the next section.
8. How the final answer changes the meaning of the opening object.

The existing Moon diagnostic is the baseline at **39% rendered-contract compliance**. A planner score, generated field, camera move, or model assertion earns no credit unless it becomes visible in the encoded video.

## 2. Reference-derived creative principles

The production target is informed by the supplied references:

- TikTok: *The Acali Raft Experiment Might Restore Your Faith in Humanity* (4:25)
- TikTok: *Why Did Ancient Humans Lose Their Dark Skin?* (2:53)
- YouTube: *What CRAZY Tricks Did Ancient Humans Use in Winter?*

Only directly observable characteristics are treated as evidence. The references demonstrate:

- a specific title question or provocative proposition remains the organizing promise;
- one human-scale subject, group, experiment, discovery, or location carries the story;
- simple illustrations work when each one introduces a new person, object, record, action, or consequence;
- the story progresses through concrete artifacts—raft plan, crew list, diagram, skeleton, excavation, laboratory interpretation—not interchangeable beauty shots;
- visual simplicity can outperform expensive motion when the causal sequence is easy to follow;
- the viewer is shown what happened before being asked to absorb the explanation;
- recurring people and objects create continuity even when the camera or location changes;
- persistent headline/part packaging can orient the viewer, but must not compete with evidence or duplicate every narration line.

The roadmap does not assume access to private retention data or unavailable transcripts from those references.

## 3. Character system

### 3.1 Human lead

The canonical human identity reference is restored from Git history as:

`assets/mascot/human-model.png`

The human is the recurring story subject by default. Each video may cast that identity as an observer, engineer, researcher, resident, traveler, patient, technician, or other topic-appropriate role. The role must be concrete and must not falsely imply a real credential.

The human must have:

- a visible objective;
- a starting belief;
- a reason to care;
- continuity of appearance, clothing, carried objects, knowledge, and location;
- at least one prediction or decision that can be shown visually;
- a changed understanding caused by evidence.

The human must not become a presenter who merely points beside illustrations.

### 3.2 Bolt

Bolt is a selective co-investigator and brand character.

Include Bolt when he:

- measures or scans evidence;
- demonstrates a mechanism the human cannot safely perform;
- notices a clue;
- warns the human;
- tests a prediction;
- fails at a physical workaround;
- reacts to a reveal;
- helps execute the final decision or callback.

Normally omit Bolt from:

- pure evidence details;
- maps and diagrams;
- scale comparisons;
- establishing locations;
- historical records;
- mechanism close-ups;
- repeated reaction shots;
- any shot where he would only stand beside the subject.

Default rendered-presence targets:

- no more than 35% of first-act visual states;
- approximately 20–30% of the complete video;
- 0% of pure evidence/mechanism shots unless Bolt physically creates the measurement being shown.

These are defaults, not blind quotas. A justified exception must be declared in Creative Direction and reported by the grader.

### 3.3 Relationship

The human owns the personal stake and belief change. Bolt supplies capability, contrast, or intervention. Neither character may know facts merely because the narration needs them. The planner tracks what each character knows after every piece of evidence.

## 4. Story structures

### 4.1 Standard explainer

Use when the topic benefits from an early answer followed by escalating implications.

Shape:

1. Visible consequence or contradiction.
2. Human objective and immediate problem.
3. First useful mechanism by 10–20 seconds.
4. Prediction or test.
5. Evidence payoff.
6. Larger complication.
7. Deeper mechanism or reversal.
8. Final answer and opening-object callback.

Standard does not mean a list. Every section must be causally connected to the preceding discovery.

### 4.2 Evidence-led mystery

Use only when the topic contains a reasonable false belief that visible evidence can overturn.

Shape:

1. Concrete anomaly in a recurring location.
2. Human objective.
3. Plausible initial explanation.
4. Evidence that initially appears to support it.
5. Contradictory clue the viewer can notice.
6. Prediction fails.
7. Human changes course.
8. Evidence chain narrows the possible cause.
9. Deep causal explanation around 45–70%.
10. Consequences follow from the reveal.
11. Exact opening-object callback.

Mystery may withhold the deepest explanation, not all useful answers. Each evidence step must provide a local payoff.

### 4.3 Topic suitability

Before scripting, the system grades whether a topic supports a genuine mystery. Evidence-led mystery is rejected or changed to Standard unless the topic has:

- a concrete anomaly;
- a reasonable false belief;
- at least three distinguishable evidence states;
- an investigation or test;
- a reveal that changes interpretation;
- a recurring subject, object, or location.

The UI must show any automatic fallback before paid rendering.

## 5. Hook contract

The hook is the first story event, not an introduction to the topic.

Within the first five seconds, the rendered opening must show:

- the title subject;
- a visible anomaly or consequence;
- a human-scale stake;
- an unanswered causal question.

By eight seconds, the viewer must understand what the human is trying to do.

Prohibited openings:

- definitions;
- generic establishing beauty shots;
- “Imagine if…” without an immediate visible event;
- title repetition followed by a roadmap;
- exact-number dumps;
- Bolt pointing beside the subject;
- multiple unrelated disasters;
- promises without an observed problem.

Every hook declares:

```json
{
  "opening_object": "",
  "visible_anomaly": "",
  "human_goal": "",
  "initial_belief": "",
  "viewer_question": "",
  "first_evidence_deadline_sec": 8,
  "first_payoff_deadline_sec": 20
}
```

The gate verifies those claims in the rendered pixels and narration.

## 6. Evidence-shot model

A narrative beat is not a shot. Each opening beat compiles into two to four phrase-aligned evidence states.

```json
{
  "beat_id": "b03",
  "belief_before": "the wind caused the water rise",
  "question": "is this a storm surge?",
  "shots": [
    {
      "evidence_id": "e03a",
      "source_strategy": "master",
      "required_object": "human marking the tide gauge",
      "required_state": "water crosses the historical mark",
      "forbidden_state": "Bolt posing beside the gauge",
      "inference_after": "the rise is real",
      "duration_sec": 2.4,
      "human_present": true,
      "bolt_present": false
    },
    {
      "evidence_id": "e03b",
      "source_strategy": "detail",
      "required_object": "anemometer needle",
      "required_state": "needle nearly still",
      "forbidden_state": "strong visible wind",
      "inference_after": "wind is contradicted as the cause",
      "duration_sec": 2.2,
      "human_present": false,
      "bolt_present": false
    }
  ],
  "belief_after": "the rise has another cause",
  "decision_caused": "compare the historical tide records"
}
```

Evidence credit rules:

- a new generated state receives evidence credit only if its required object and state are visible;
- a crop receives evidence credit only when it reveals a declared detail already present in the master;
- pan, zoom, crossfade, caption change, or camera motion alone receives zero evidence credit;
- I2V receives evidence credit only when state-after differs visibly and correctly from state-before;
- every cut must either reveal evidence, perform an action, change scale/time/location, or create a deliberate emotional pause;
- same-source reframes may not run consecutively for more than six seconds in the opening.

Opening targets:

- 1.8–3.2 seconds per visual state;
- no unexplained hold over 3.5 seconds;
- 2–4 evidence states per beat;
- at least 70% of cuts add visible information;
- at least two distinct source/state assets per opening beat unless a verified detail exists in the master.

## 7. Visual world and creative direction

Every long-form video creates a continuity pack before paid scene generation:

- human identity reference;
- Bolt identity reference;
- recurring-location master;
- opening-object master and detail crop;
- spatial layout and camera zones;
- clothing and carried-object state;
- time-of-day and weather progression;
- color script;
- illustration/render style;
- allowed motion language;
- forbidden imagery and continuity changes.

Creative Direction may control:

- visual style: photoreal, illustrated, documentary, graphic, archival, mixed-media;
- tone and audience;
- historical period;
- color and lighting;
- camera language;
- motion intensity;
- use of diagrams, maps, records, or archival framing;
- explicit content to emphasize or avoid;
- justified character-presence exceptions.

Creative Direction may not override:

- scientific accuracy;
- story-contract requirements;
- character identity;
- evidence visibility;
- accessibility;
- spend controls;
- fail-closed gates.

The reference videos prove that simple illustrated direction is acceptable. Expensive photoreal imagery is not the default measure of quality; causal clarity is.

## 8. Motion modes

### Stills

- no paid I2V;
- meaningful evidence changes still required;
- suitable for animatic and low-cost story validation;
- pans and crops reported separately from evidence states.

### Standard motion

- motion prioritized for opening anomaly, human action, first failed prediction, reversal, peak reveal, and final callback;
- target coverage is story-role based, not even distribution;
- evidence details and diagrams remain still when movement would reduce comprehension.

### Full motion

- every eligible state may receive motion within the spend cap;
- “full” never means animate one scene master for the entire narration beat;
- pure records/diagrams may use restrained motion or remain still by declared creative decision;
- the UI reports planned, purchased, successful, and fallback clips separately.

All modes must pass the same story and evidence gates.

## 9. Scientific claim contract

Before story planning, build a claim ledger. Every material numeric or causal claim records:

```json
{
  "claim_id": "c07",
  "claim": "",
  "source_url": "",
  "source_type": "primary|authoritative_secondary",
  "calculation": "",
  "assumptions": [],
  "geographic_scope": "",
  "timescale": "",
  "confidence": "high|medium|speculative",
  "narration_phrase": "",
  "evidence_id": "",
  "allowed_exaggeration": false
}
```

Hard failures:

- unsupported major claim;
- local measurement presented as global;
- possible effect presented as certain;
- missing timescale that changes meaning;
- narration and visual contradict the approved claim;
- fact-check correction destroys a previously valid story contract.

## 10. Audio and captions

- generate and measure final-speed TTS before purchasing most visual assets;
- fit shot boundaries to real phrase timings, not estimated words per second;
- reject final runtime outside ±3% of the requested duration;
- use silence or music reduction before major evidence/reveals;
- use impacts only when a visible state changes;
- conventional subtitles are the default;
- major numbers and predictions may use large evidence-attached text;
- never display headline, subtitle, complex evidence, Bolt action, and diagram labels simultaneously;
- music structure follows story acts and does not remain at one fixed level.

## 11. Gates and release scoring

### 11.1 Topic and research gate

Runs before script/image spend. Verifies topic suitability, claim support, scope, and timescale.

### 11.2 Script gate

Verifies story fields, human objective, knowledge gap, causal chain, resolved questions, Bolt roles, callback, runtime word window, and absence of consequence enumeration.

Metadata compliance permits the script to proceed; it does not award rendered-video points.

### 11.3 Low-cost animatic gate

Uses final TTS plus inexpensive storyboard assets. A human reviewer must be able to identify the subject, objective, anomaly, evidence sequence, belief change, and forward question.

### 11.4 Rendered 45-second gate

Includes final narration, captions, music, transitions, evidence assets, and selected I2V. The approved opening is frozen and reused in the final edit.

Grade using:

1. deterministic media measurements;
2. per-cut required-object/state verification;
3. blind sequential story judgment without planner metadata;
4. human editorial approval.

The gate fails closed. Diagnostic bypass is developer-only, visibly watermarked, and cannot report PASS or produce a publishable artifact.

### 11.5 Final video gate

Verifies runtime, frozen-opening identity, unresolved questions, opening-object callback, claim ledger, visual continuity, audio mix, captions, technical delivery, and complete artifact persistence.

### 11.6 Rendered-contract score

| Category | Points |
|---|---:|
| Opening promise and anomaly | 15 |
| Human objective and developing investigation | 15 |
| Evidence accumulation and causal storytelling | 20 |
| Genuine multi-shot visual storytelling | 15 |
| Bolt discipline and usefulness | 10 |
| First-act continuity and exact callback | 10 |
| Visual pacing measured from the MP4 | 5 |
| Scientific accuracy and claim support | 5 |
| Audio, captions, and comprehension | 3 |
| Runtime and technical delivery | 2 |
| **Total** | **100** |

Caps:

- any hard-contract failure: 69 maximum;
- slideshow behavior: 49 maximum;
- unsupported major scientific claim: 59 maximum;
- failed rendered opening: full render blocked.

Release target:

- no hard failures;
- at least 85/100 for controlled pilots;
- at least 90/100 before enabling unattended production;
- 100 means complete contract compliance, not guaranteed 100% audience retention.

## 12. Production durability and spend safety

Long renders must not depend on an in-process FastAPI background task, process dictionaries, or ephemeral local checkpoints in production.

Required production properties:

- durable job and stage records;
- workflow/queue execution outside request lifetime;
- provider idempotency key per paid operation;
- asset content hashes and script/compiler version hashes;
- resume on a different worker without repurchasing completed valid assets;
- running cost ledger checked before every paid batch;
- explicit Blob/DB failure states;
- atomic finalization or compensating cleanup;
- `/finished` distinguishes empty data from storage failure;
- orphaned upload cleanup;
- downloadable reports and rejected diagnostic artifacts clearly separated.

## 13. Delivery phases and pull-request contracts

Every phase is one independently reviewable PR. A phase is not complete because tests pass; it must supply the listed proof artifacts. The next phase begins only from the merged previous phase.

### PR 0 — Roadmap and baseline contract

Deliver:

- this roadmap;
- baseline Moon score recorded as 39%;
- Standard and Evidence Mystery definitions;
- human/Bolt role contract;
- phase acceptance matrix.

Proof:

- document committed to Git;
- no production behavior changed.

### PR 1 — Human-led story and hook planner

Deliver:

- restore `assets/mascot/human-model.png` from Git history;
- add a documented human identity/role model;
- remove legacy “Bolt hosts every scene” instructions;
- permit `bolt_mode=absent` in every planning schema and fallback;
- implement deterministic Bolt role/presence budgets;
- implement Standard and Evidence Mystery routing;
- add topic-suitability fallback;
- require belief → prediction → evidence → belief change → decision;
- implement hook fields and timing requirements;
- preserve opening-object callback;
- persist selected structure and character plan in reports.

Acceptance:

- contract fixtures for both structures pass;
- consequence-list, decorative-Bolt, missing-human-goal, fake-knowledge-gap, and broken-callback fixtures fail;
- generated plans contain a human-led causal chain;
- Bolt is absent from pure-evidence fixture beats;
- no paid media generation is needed to prove the phase.

### PR 2 — Research dossier, claim ledger, and audio timing

Deliver:

- pre-script research dossier;
- claim ledger and source validation;
- scope/timescale/confidence checks;
- final-speed TTS generated before main visual purchase;
- phrase timestamps and runtime fitting;
- ±3% runtime gate.

Acceptance:

- seeded unsupported and scope-inflated claims fail;
- fact-check changes cannot silently break story structure;
- controlled 90-second scripts land between 87.3 and 92.7 seconds without post-stretching;
- claim-to-narration and claim-to-evidence joins are complete.

### PR 3 — Evidence asset and continuity compiler

Deliver:

- 2–4 evidence states per opening beat;
- required/forbidden object-state specifications;
- distinct-source and reframe accounting;
- continuity pack and stable identity/object/location IDs;
- deterministic character-reference inclusion;
- exact opening-object asset reuse;
- no automatic `new_information=true` on reframes.

Acceptance:

- at least 70% of opening cuts add verified visible information;
- at least two distinct source/state assets per opening beat unless detail verification passes;
- no pure evidence asset contains Bolt;
- human identity, clothing, location, and opening object pass continuity fixtures;
- failures become explicit rejected assets, not silent reframes.

### PR 4 — Story-role motion and final-edit compiler

Deliver:

- Stills, Standard, and Full Motion implemented against evidence states;
- role-prioritized Standard motion;
- phrase-aligned transitions;
- actual final-opening I2V generated before gate;
- motion success/fallback/cost reporting;
- frozen approved opening reused by the final edit.

Acceptance:

- Stills purchases zero I2V;
- Standard prioritizes hook, test, reversal, reveal, and callback;
- Full requests every eligible evidence state within the cap;
- gated opening and final opening match in content;
- motion semantic alignment is at least 90%;
- slow motion, caption changes, and Ken Burns moves do not count as evidence.

### PR 5 — Animatic and rendered-story gates

Deliver:

- low-cost animatic gate;
- per-cut and midpoint sequential inspection;
- deterministic visual-state, source-reuse, character-frequency, and hold checks;
- blind rendered-story judge;
- human review checklist and approval record;
- developer-only rejected diagnostic mode;
- new 100-point rendered-contract report.

Acceptance:

- seeded Bolt-everywhere, slideshow, long-hold, broken-continuity, false-belief-without-evidence, and consequence-list videos all fail;
- the old Moon diagnostic scores 39% under the frozen rubric;
- a failed opening cannot purchase remaining assets or report PASS;
- automated observations are checked against deterministic facts before scoring.

### PR 6 — Durable production execution

Deliver:

- durable workflow/queue;
- DB-backed jobs/events/stages/costs;
- Blob-backed assets and checkpoints;
- stage-level idempotency;
- cross-worker resume;
- explicit storage failures;
- reliable `/finished`;
- orphan cleanup and finalization.

Acceptance:

- terminate a worker mid-render and resume on another worker;
- no completed provider stage is purchased twice;
- status works from another instance;
- Blob and DB failures are visible and recoverable;
- `/finished` lists completed artifacts and never masks an outage as an empty library;
- forced retries remain within the configured spend cap plus one documented in-flight call.

### PR 7 — Controlled 45-second pilots

Deliver:

- one Standard pilot opening;
- one Evidence Mystery pilot opening;
- complete contact sheets, scripts, claim ledgers, asset plans, timing reports, cost reports, and rendered-contract reports;
- human editorial decisions.

Acceptance:

- both score at least 85/100;
- neither has a hard failure;
- human subject, objective, anomaly, evidence chain, belief change, and forward question are recoverable from the rendered opening;
- Bolt is useful and within the declared range;
- no full video purchased yet.

### PR 8 — Controlled 90-second production pilot

Deliver:

- one complete 90-second video selected from the stronger Phase 7 structure;
- frozen approved opening;
- final callback and all resolved questions;
- production storage proof;
- publish/no-publish recommendation.

Acceptance:

- runtime 87.3–92.7 seconds at natural TTS speed;
- at least 90/100 rendered-contract score;
- no hard failures, filler, dropped narration, unexplained artifacts, or unresolved questions;
- opening object returns as the exact conditioned/reused asset;
- scientific claims and visuals reconcile with the ledger;
- downloadable MP4 is fast-start and the complete job survives cross-worker recovery testing.

### PR 9 — Outcome calibration

Deliver:

- retention checkpoint schema;
- story-format, hook, evidence, Bolt, motion, caption, runtime, and cost experiment dimensions;
- comparison tooling for contract score versus YouTube outcomes;
- rubric-version tracking.

Acceptance:

- no causal claim is made from fewer than 10 comparable published videos;
- scoring changes are versioned and do not rewrite historical grades;
- 0/10/30/60-second and 25/50/75% retention checkpoints can be joined to generation settings.

## 14. Phase validation matrix

For every PR, the author must provide:

| Proof | Required |
|---|---:|
| Requirement-by-requirement disposition | Yes |
| Unit tests | Yes |
| Adversarial negative fixtures | Yes |
| Integration tests for affected boundaries | Yes |
| Real artifact when the phase renders media | Yes |
| Cost incurred and remaining uncertainty | Yes |
| Known limitations and non-goals | Yes |
| Rollback path | Yes |
| No unrelated changes | Yes |

Disposition vocabulary:

- **PASS — verified in real artifact**
- **PASS — deterministic test**
- **PARTIAL — limitation stated**
- **FAIL — PR cannot merge**
- **NOT APPLICABLE — reason stated**

“Implemented,” “supported,” “ready,” and “passed” may not be used without naming the validating artifact or test.

## 15. Stop conditions

Stop the phase and do not open a completion PR when:

- a load-bearing acceptance requirement is unverified;
- the implementation passes only through planner metadata;
- a paid test fails and the cause is not understood;
- an advisory bypass is required to produce the claimed artifact;
- a fallback hides failed evidence, audio, motion, storage, or continuity;
- runtime or cost cannot be bounded;
- the phase changes unrelated product behavior;
- the result would require reassuring language to compensate for missing proof.

## 16. Definition of success

The rebuild succeeds when a viewer can watch the opening with no access to the planner and accurately state:

- who the human is;
- what the human wants;
- what went wrong;
- what evidence has accumulated;
- what the human initially believed;
- why that belief changed;
- what Bolt contributed;
- and what concrete question remains.

The system succeeds technically when it can produce that experience repeatably, within runtime and cost bounds, survive production failures, reject its own bad outputs, and explain exactly why a video passed.

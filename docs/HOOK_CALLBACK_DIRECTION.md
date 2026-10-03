# Hook and callback direction — user brief, 2026-10-03

The user proposed this opening question for the New Zealand stoats story:

> How did a plan to save New Zealand’s sheep put kiwi chicks on the menu?

And this closing question:

> So before you fix one problem, ask: what else are you putting on the menu?

Use the pair as a writing direction, subject to the researched evidence. It connects
the intended beneficiary with an unexpected victim, then gives the metaphor a new
meaning at the close. The opening and ending need not be the exact same question.
Answer the opening through the story; return to its concrete image and extend the
viewer’s understanding at the end. An unanswered repeat is not a payoff.

For future hook work:

- Generate hook and closing callback together, before scene expansion.
- Prefer a specific, supported contradiction between intent and consequence.
- Follow the question with the minimum setup needed to understand the causal problem.
- Reserve the strongest explanatory turn for the story to earn; do not hide the topic.
- Echo the opening's object or image at the close, with an evidence-backed answer.
- Keep spoken cadence natural. A vivid scenario must not invent an eyewitness,
  named actor, historical scene, number, interval or source-supported outcome.
- Use timeframe tension only when both endpoints and the comparison are supported.
- Compare several pairs against the same dossier, then assess the opening plus the
  first 30 seconds and ending together. A catchy sentence alone is insufficient.

The pasted viral-hook post is qualitative inspiration, not verified experimental
evidence. Its 1,000-hook sample, 30% frequency and neuroscience/2025 trend claims were
not independently established. No retention lift or virality guarantee follows.

## Implementation

`hook_callback.py` supplies a shared writing brief and a hook/ending grading rubric.
Each planner candidate is asked for a `hook_contract`: viewer question, supported
answer, documented contrast, callback image and optional closing question. This is
writing intent, not new factual evidence. Expansion receives the same contract in
each batch and only the ending batch writes its callback. The assembled script keeps
the contract for the targeted editor and private Studio inspection.

The existing whole-script integrity review also checks `HOOK_PROMISE_UNPAID` against
the actual spoken narration, including discourse scenes. Metadata cannot stand in
for a spoken answer. The error routes to the bounded editor; a repair cannot trade
fewer factual errors for a newly unanswered opening. The source judge explicitly
checks historical questions' factual premises. No separate provider call is added.

Planner, graded-script, entailment, integrity and editorial cache contracts change.
Old plans without the field remain readable. The brief prefers a question for an
intervention story but does not force questions, invented contradictions, timelines
or identical opening/closing wording across every story engine. Live writing quality
and viewer retention are unverified until separately measured.

The current job b3cf7a4f remains a PR155 baseline test. Do not inject this new wording
into its stored request, change its evidence, or invalidate completed paid work while
resuming the provider-account interruption. Apply hook changes in a separately scoped
future generation after examining this run's actual output.

# Harp-seal Short: negative retention audit and revision

Original action: `act_f2889e3e590d48d3b471746a136d0d43` · job `454814e0`.
Original local attachment: `video (2).mp4`, 1080×1920, approximately 35.1 seconds.
Production record: technically completed, automatic 69/100 REJECT, human review pending, $1.1239 reported spend.

This is an editorial prediction of swipe-away risks, not a measured audience-retention curve. Review used one-second frame samples, the approved narration, media metadata, and source tracing. Voice diagnosis is based on the configured Onyx / tts-1-hd path and the absence of acting controls; no claim is made that an audio-only listener panel was conducted.

## What makes viewers leave

| Where | Observed problem / negative viewer response | Revision |
|---|---|---|
| 0–4.7s | Nursing close-up under a question about a terrible mother. The promised surprising behavior is not visible. “This looks like normal parenting.” | Mother already leaving in frame one; departure is the opening action. Care is shown later as a signposted explanation, not concealed. |
| 0–4.7s | Very tight crop, nearly unchanged composition, no useful hook caption. | Native portrait motion; legible wide separation of mother and pup; captions from the first spoken words. |
| ~5s | Departure is shown too briefly to become a story event after the long nursing hold. | Consecutive action/result: mother leaves, water gap opens, pup remains. |
| 6–10s | Another long low-change pup pose. Shot count is not visible development. | Short food-gap beat and early hidden-food reveal. |
| Across the cut | Side-clipped text makes the video look broken and forces viewers to guess missing words. | Authored three-word captions in a safe screen-space box after every crop and camera move. |
| Motion vs still shots | Captions are missing or inconsistent on motion. | One final caption pass covers both media types. |
| ~12–16s | Nursing flashback and fat diagram arrive late and feel like separate illustrations. | Earlier explicit BEFORE SHE LEFT tag; nursing → stored-fat illustration → reserve use in adjacent shots. |
| ~14s | Photoreal body cutaway resembles opened anatomy. | Restrained explanatory silhouette with a gold blubber band; no wound. |
| ~16–20s | White pup becomes heavily spotted without a clear elapsed-time cue. | Explicit WEEKS WITHOUT MEALS time jump, separate juvenile subject definition. |
| ~18–26s | Long ice-risk detour repeats the same seal-on-floe situation. | A clear second dependency: food is stored inside, but the resting platform is outside; show the ice itself changing. |
| ~23–26s | Drowning language and dramatic weather risk implying that this individual is dying. | Conditional IF ICE BREAKS EARLY sequence; no depicted drowning, invented rescue, or predetermined death. |
| ~26–29s | Underwater still is labelled feeding, but does not visibly show a catch or meal. | Remove the unsupported visual payoff. The short need not manufacture a successful hunt. |
| ~29–35s | Multiple conclusions: fuel, milk buys time, ice must last. Viewers can sense the ending well before the final frame. | One two-line verdict and a decisive end. |
| Whole video | Similar gray-blue compositions and poses, weak contrast between information states. | Teal/ivory visual identity, gold reserved for the stored-energy explanation, varied scale tied to purpose. |
| Whole video | The voice is configured by voice name only; no performance arc is passed to TTS. | Coral with an instruction-capable model: curious opening, playful food reveal, serious conditional risk, crisp verdict. |
| Whole video | Final mux contains narration only. There is no music or timed editorial sound layer. | Quiet original pluck/percussion bed and restrained beat accents; reduce the bed during the risk section. |
| Whole video | Cuts follow a global rescaling of estimated shot times, not the durations of their own narration scenes. | Each narration beat owns its measured picture time. |

## Production defects confirmed in source

- `_render_motion_shot` requested 1920×1080 from the provider even for portrait delivery, then cropped to 1080×1920.
- `_animate_one` prepended subtle drift / blinking to ordinary prompts. The Nature adapter now uses the existing explicit evidence-action lane and puts the action before scenery in the provider prompt.
- `_compose_directed_overlays` used large unwrapped text on the source image before zoom/crop. Nature v2 adds text after composition instead.
- The directed grade adapter supplied no cast-free continuity context, while the shared gate defaults to requiring Bolt. For a no-mascot Nature film that guarantees a `bolt_absent` failure and can cap the score at 69. Nature v2 declares `cast=none`; it does not lower score thresholds or rewrite the archived v1 grade.
- Existing visible-information checks partly relied on file existence and declared shot metadata. Those are not proof that a seal performs the requested action. The new report explicitly retains human action/continuity review and unmeasured audience retention.

## Revised narration — 92 whitespace-delimited words

> Why is this harp seal the worst mother? After about twelve days, she leaves. Her pup cannot feed itself yet.
>
> Dinner service: closed. But there is food hidden in this pup.
>
> Before she left, Mom's rich milk built a thick layer of fat. A built-in lunchbox.
>
> After weaning, that stored energy fuels the pup for weeks without meals.
>
> But there is a catch. It still needs ice to rest on as it develops. Break that up too soon, and young pups can drown.
>
> Mom leaves the fuel. The ice has to last.

The opening is the series' editorial question, not a scientific ranking. “Lunchbox” is explicitly a metaphor for fat reserves; the visuals must not place human bags or food containers on a seal.

## Directing plan

| Planned window | Story change | Treatment |
|---|---|---|
| 0–6.8s | Mother leaves; milk meals stop | Three short shots: departure, exit, absence. First two are motion. |
| 6.8–10.8s | Food is already stored | Empty-space joke, then a purposeful body-profile reveal. |
| 10.8–16.8s | Milk built the reserve | Marked flashback, visible nursing, simple fat-store diagram with filling energy graphic. |
| 16.8–21.2s | Stored energy bridges weeks without meals | Returning to post-weaning present, declining illustrative reserve graphic, explicit later juvenile. |
| 21.2–29.8s | Ice remains a separate dependency | Platform cross-section, stable resting ice, conditional breakup action and consequence. |
| 29.8–33.8s | Fuel buys time, not a guarantee | Older juvenile, supporting ice, one verdict. No loop back to a newborn. |

These are planning times. Exact TTS is generated and aligned before visuals; each beat is retimed to its actual audio. Natural speech is not slowed to fill an arbitrary target. The accepted speech window is 27–40.6 seconds; each delivered shot must fit 0.75–3.4 seconds. If a beat is too long for its storyboard, it is repartitioned before buying images.

## Voice and mix

- Model: `gpt-4o-mini-tts-2025-12-15`, voice: `coral`.
- Tone: bright science storyteller talking to a friend; smile on the dinner/lunchbox wording, no shouting or fake animal emotion.
- Direction is part of the immutable spec and TTS cache identity.
- Whisper word timing drives authored three-word captions. Timing alignment confidence is recorded; approximate matches require human review.
- Original quiet 116 BPM pulse, no licensed song or fabricated seal calls; risk passage has a quieter bed.
- Gold energy graphics have no percentages or scientific scale. They explain the concept, not measured fat depletion for an individual.

## Governing files and safeguards

- Authoritative episode: `spec/harp_seal_nature_story_v2.json`.
- Durable render bundle: `spec/harp_seal_nature_short_v2.json`, generated by `nature_story_flow.compile_directed_short` after the shared storyboard and KPI validation.
- Opt-in presentation implementation: `nature_short_presentation.py`.
- The complete old approved spec still hashes to `4d4f1c7370786862a625fd686f9b58b4251dcbc1cce48fb2a5411b6ad36032d6`.
- Legacy directed/landscape behavior remains the default. Nature v2 cannot be selected for a landscape or partial long-form request.
- New words, voice, shots and presentation require a NEW immutable approval. The v1 approval cannot fund this revision.
- Estimated media allowance is about $3, with a proposed hard ceiling of $5. Provider success, grade and retention are not guaranteed.

## Acceptance and honest limits

Before rendering: canonical narration/bundle equality, shared storyboard validity, old-hash stability, measured beat alignment, portrait provider dimensions, voice-cache invalidation and caption-control escaping are covered by focused tests. The actual FFmpeg caption and sound-mix path was exercised on a synthetic two-second fixture and visually inspected for safe text placement.

The installable wheel includes the Nature runtime, compiler and presentation modules. An isolated wheel smoke check imports them and compiles the bundled episode away from the repository checkout, so missing package files cannot be hidden by the source tree.

After rendering: inspect actual departure and nursing action; caption readability throughout; correct age transitions; no body distortions; source-to-mechanism clarity; music/voice balance; and one complete ending. Do not substitute a shot-count target or a higher automatic score for this review. Audience retention remains UNKNOWN until publication data exists.

Sources rechecked September 26, 2026:

- [NOAA harp-seal profile](https://www.fisheries.noaa.gov/species/harp-seal): nursing, blubber accumulation and the post-weaning fast.
- [DFO harp-seal profile](https://www.dfo-mpo.gc.ca/species-especes/profiles-profils/harpseal-phoquegroenland-eng.html): nursing and growth.
- [DFO research on ice dependence](https://www.dfo-mpo.gc.ca/species-especes/publications/mammals-mammiferes/cemam/2012-2014/10-eng.html): stable ice for post-weaning rest and conditional drowning risk.
- [OpenAI speech documentation](https://developers.openai.com/api/docs/guides/text-to-speech): instruction-capable speech generation.

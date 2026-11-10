"""Does this question belong to one of the channels, asked before any research is bought.

Measured cost of not asking: "Why don't Americans eat hippo meat?" spent $3.20 across four runs and
never produced a spine. Not the engine and not the budget -- the question names an ABSENCE with
parallel causes, so research returned 21 verified claims split between a 1910 congressional episode
and modern African conservation. One spine cannot be built from two stories.

TWO CHANNELS, TWO TESTS. An earlier version of this file had one: the outcome had to INVERT the
intent. That was derived from a corpus which happens to be mostly backfires, and it turned a
pattern into a law -- it would have refused the Aral Sea, where the river diversion did exactly
what it was designed to do. Cotton grew. The lake was the price, not a reversal.

    world    (broadened 2026-10-24) one deliberate human decision whose consequence is still
             unfolding today and hard to undo -- animals, chemicals, dams, reactors, bombs,
             products, designs. The paragraph below is the original, animal-only test.
             An intervention aimed at an ANIMAL POPULATION, and what happened to it afterwards.
             Hanoi's rat bounty, China's sparrows, Australia's cane toads, Hawaii's mongooses.
             The intervention must TARGET the animals: a river diversion that ruined a fishery is
             not this channel, because nobody was intervening on the fish.

    history  a state PROGRAM -- a law, decree, campaign or project -- and the harm it did. A
             programme that failed qualifies; so does one that succeeded and imposed an enormous
             cost doing it. The harm does not have to have been unforeseen: the Aral Sea's
             hydrologists knew the lake would shrink, and it is still the story.

Animals win ties. A state-run animal campaign is `world`, because otherwise `history` absorbs
almost everything and the niches collapse back into "explains the world", which is the problem the
split exists to solve.

What both require, and what hippo lacked: ONE documented intervention, bounded in time and place,
with a documented aftermath. Not an absence, not a standing condition with parallel causes.

Structure is judged deterministically and cheaply; the fit is a semantic question and gets a small
model call. The deterministic half never refuses on its own -- it has been wrong twice in this
codebase already -- it supplies signals to the call that rules.
"""
from __future__ import annotations

import json
import os
import re

FITS, NEEDS_NARROWING, NO_STORY = "fits", "needs_narrowing", "no_story"

WORLD, HISTORY, NATURE = "world", "history", "nature"
EDITORIAL_VERSION = "bolt_three_channels_v5_world_cant_undo"
CHANNELS = {
    WORLD: {
        "name": "Bolt Explains the World",
        # Broadened 2026-10-24 (operator): "human decisions that can't be undone", no longer
        # animal backfires first. Demand measured the same day: Chernobyl 1.5M, Boeing 737 MAX
        # 575K, Agent Orange 350K, OxyContin 299K against 100-250K for our invasive-species films.
        # The screen refused "Colorado River / Lake Mead" for World as a History programme.
        "banner": "HUMAN DECISIONS THAT CAN'T BE UNDONE.",
        "promise": "They did X. Now Y. -- one deliberate decision, told from today, whose "
                   "consequence is still unfolding and hard to undo.",
        "requires": "ONE named, deliberate human decision -- an animal brought in or wiped out; "
                    "a product, chemical or drug made and sold; a dam, canal, water deal or other "
                    "infrastructure built; a reactor sealed or waste stored; a bombing or "
                    "defoliation campaign; an engineering or design choice; a rule or incentive "
                    "enforced -- and a documented consequence of that decision that is STILL "
                    "UNFOLDING today and hard to undo. The consequence need not be the opposite "
                    "of the intent, and it need not be ecological",
        "examples": "Australia's cane toads; Escobar's hippos; the sealed fuel inside Chernobyl "
                    "that is reacting again; the 1922 Colorado River Compact and Lake Mead's "
                    "shortage; Boeing's MCAS and the FAA's production cap; Agent Orange and the "
                    "dioxin still being dug out at Bien Hoa; Purdue's OxyContin marketing and the "
                    "opioid settlement; the WWII bombs Germany still evacuates for",
        "excludes": "accidents with no deliberate decision behind them (Titanic, Beirut port); "
                    "finished stories whose consequence is over (Theranos, Lehman, the emu war); "
                    "unrealized proposals; general animal facts and quizzes; daily or partisan "
                    "political news; celebrity controversies",
    },
    HISTORY: {
        "name": "Bolt Explains History",
        "banner": "GOVERNMENT PLANS. HUMAN CONSEQUENCES.",
        "promise": "What governments imposed on people -- and what it cost them.",
        "requires": "one state PROGRAM -- a law, decree, campaign or project -- and documented "
                    "harm. A programme that FAILED qualifies, and so does one that SUCCEEDED at "
                    "its stated aim while imposing an enormous cost. The harm need not have been "
                    "unforeseen, and there is no requirement that the outcome invert the intent",
        "examples": "the Soviet river diversions that grew cotton and emptied the Aral Sea; the "
                    "US denaturing of industrial alcohol during Prohibition, which killed the "
                    "people it was meant to deter; Romania's Decree 770 and the orphanages it "
                    "filled",
        "excludes": "daily political news, general biographies, unrelated wars, celebrity "
                    "controversies and corporate scandals",
    },
    NATURE: {
        "name": "Bolt Explains Nature",
        "banner": "TERRIBLE PARENTS. PERFECT STRATEGY.",
        "promise": "Why [animal] is a terrible parent -- and why the young are the reason.",
        "requires": "ONE species and ONE documented behaviour toward its eggs or young, in one of "
                    "two shapes. MISTAKEN VERDICT: the behaviour was READ as neglect, cruelty, "
                    "theft or abandonment by someone on the record -- a name, a label, a "
                    "textbook, a naturalist -- and specific evidence corrected the reading. "
                    "STRANGE BEHAVIOUR: the behaviour merely LOOKS like neglect or abandonment, "
                    "and the constraint behind it and its function for the young are documented; "
                    "no accusation is attributed to anyone, because none was recorded. NO human "
                    "intervention drives either: the animal is doing what it always did",
        "examples": "Oviraptor, named 'egg thief' in 1924 for a skeleton on a nest that was its "
                    "own; the emperor penguin father who fasts through the Antarctic winter with "
                    "the egg on his feet; the giant Pacific octopus that stops eating to guard her "
                    "eggs; the Nile crocodile that carries hatchlings in the jaws it was accused "
                    "of eating them with; sand tiger shark pups that eat their siblings before "
                    "birth",
        "excludes": "general animal facts, quizzes, 'how animals raise their young' surveys with "
                    "no strange-looking behaviour at their centre, human programmes that harmed "
                    "animals (those belong to WORLD), invented motives or feelings, INVENTED "
                    "REPUTATIONS ('the lists call her the worst mother' when no list does), and "
                    "any story whose function or corrected reading is not itself documented",
    },
}

# Which narrative engines a channel's episodes may use. World is deliberately unrestricted: its
# episodes have been selected freely among the six older engines and that behaviour is measured. Nature is new and has exactly two shapes, so the selector is not offered
# a bounty engine for a penguin: an engine chosen "by how the story turns" still has to be one
# the channel contract admits.
CHANNEL_ENGINES = {
    NATURE: ("mistaken_verdict", "strange_behaviour"),
    # History (2026-10-10): the first Salem run was offered all engines, chose backfiring_solution
    # ("an incentive somebody exploits"), and failed its own setup and mechanism roles before any
    # media spend: a court admitting spectral evidence is not an exploited bounty. Backfires now
    # belong to World, and the animal engines to World and Nature; History tells a state programme
    # and its cost through the three human-history shapes.
    # 2026-10-14: History uses only COMPILED shapes. accumulating_indictment and power_reversal have
    # no event map, so a History film planned under either fell through to the Alex/Bolt
    # investigation contract and failed it (Radium Girls: "No visible evidence changes Alex's
    # belief", "Bolt useful measurement"). state_programme is the channel's own shape.
    HISTORY: ("state_programme", "almost_happened_plan"),
}

# Engines that belong to one channel. An unrestricted channel (World) is still offered every other
# engine exactly as before; it is never offered another channel's own shape, so a World rule story
# such as Hoy No Circula cannot be planned as a History programme with a verdict close.
EXCLUSIVE_ENGINES = {"state_programme": HISTORY}


def engines_for_channel(channel: str) -> tuple[str, ...] | None:
    """Allowed engine ids for a channel, or None when the channel does not restrict them."""
    return CHANNEL_ENGINES.get((channel or "").strip().lower())


def engine_admitted(engine_id: str, channel: str) -> bool:
    """May this channel's episodes use this engine? Restricted channels list theirs; every channel
    is kept off another channel's exclusive engine."""
    engine_id = (engine_id or "").strip().lower()
    channel = (channel or "").strip().lower()
    owner = EXCLUSIVE_ENGINES.get(engine_id)
    if owner is not None and owner != channel:
        return False
    allowed = engines_for_channel(channel)
    return engine_id in allowed if allowed else True


# Editorial research queue, not approved claims or a promise of a finished video.
# Engine hints describe a candidate shape; research still decides the supported structure.
TOPIC_CANDIDATES = {
    WORLD: [
        {"question": "What happened after Hanoi introduced its rat-tail bounty in 1902?",
         "engine_hint": "backfiring_solution", "status": "research_candidate"},
        {"question": "What followed China's campaign to eradicate sparrows during Four Pests?",
         "engine_hint": "removed_keystone", "status": "research_candidate"},
        {"question": "What happened after cane toads were introduced to control Australian cane beetles?",
         "engine_hint": "removed_keystone", "status": "research_candidate"},
        {"question": "What happened after mongooses were introduced to control rats in Hawaii?",
         "engine_hint": "removed_keystone", "status": "research_candidate"},
        {"question": "How did federal wolf-eradication campaigns change Yellowstone and the American West?",
         "suggested_title": "America Tried to Eliminate Its Wolves. The Landscape Changed.",
         "why": "A visible predator-removal campaign with a documented ecological aftermath.",
         "engine_hint": "removed_keystone", "status": "research_candidate"},
        {"question": "What happened after wolves were reintroduced to Yellowstone in 1995?",
         "suggested_title": "What Happened When America Put Wolves Back in Yellowstone?",
         "why": "A bounded animal intervention with unusually strong before-and-after visuals.",
         "engine_hint": "removed_keystone", "status": "research_candidate"},
        {"question": "What followed the 1890 and 1891 releases of European starlings in New York City?",
         "suggested_title": "A Few Birds Released in New York Became Millions",
         "why": "A deliberate introduction that expanded into a continent-wide animal story.",
         "engine_hint": "removed_keystone", "status": "research_candidate"},
        {"question": "How did Louisiana's nutria fur industry help establish a destructive wild population?",
         "suggested_title": "The Fur Animal That Began Eating Louisiana's Coast",
         "why": "Commercial introduction, escape and wetland damage form one visual causal chain.",
         "engine_hint": "removed_keystone", "status": "research_candidate"},
        {"question": "What happened after mosquitofish were introduced across American waterways for mosquito control?",
         "suggested_title": "America Released This Fish to Fight Mosquitoes. It Spread Instead.",
         "why": "A biological-control intervention with a clear promise and ecological tradeoffs.",
         "engine_hint": "removed_keystone", "status": "research_candidate"},
        {"question": "How did importing Asian carp for algae and waste control lead to an invasive-fish crisis?",
         "suggested_title": "The Fish Imported to Clean Ponds That Took Over American Rivers",
         "why": "A concrete control experiment whose escape created a much larger problem.",
         "engine_hint": "removed_keystone", "status": "research_candidate"},
    ],
    HISTORY: [
        {"question": "How did Soviet irrigation diversions change the Aral Sea and surrounding communities?",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did US industrial-alcohol denaturing policy harm drinkers during Prohibition?",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "What did Romania's Decree 770 impose on families, and what were its consequences?",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did federal wheat price guarantees encourage Great Plains plowing before the Dust Bowl?",
         "suggested_title": "The Farming Boom That Helped Turn the Plains to Dust",
         "why": "A specific federal incentive connects policy, behavior and environmental cost.",
         "engine_hint": "backfiring_solution", "status": "research_candidate"},
        {"question": "How did Executive Order 9066 lead to the incarceration of Japanese Americans during World War II?",
         "suggested_title": "The Order That Imprisoned American Families Without Trial",
         "why": "One wartime order, a visible enforcement system and a documented human cost.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did federal HOLC and FHA housing policy institutionalize redlining?",
         "suggested_title": "The Government Maps That Divided American Wealth",
         "why": "Maps make an abstract policy visible while the consequences persist across generations.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the Housing Act of 1949's urban-renewal program displace established neighborhoods?",
         "suggested_title": "America Called It Urban Renewal. Neighborhoods Disappeared.",
         "why": "A named program provides a clean promise, demolition and displacement sequence.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the 1956 Interstate Highway Act route highways through urban communities?",
         "suggested_title": "The Highways That Connected America and Divided Its Cities",
         "why": "Construction maps, homes and roads provide strong human-scale visual progression.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the federal Indian boarding-school system try to erase Indigenous identity?",
         "suggested_title": "The Schools Built to Erase Indigenous Identity",
         "why": "A long-running federal program with specific institutions, methods and survivors.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the Homestead Act transform western settlement and dispossess Native nations?",
         "suggested_title": "The Real Cost of America's 'Free Land'",
         "why": "One landmark law links settlement incentives to land transfer and displacement.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the Chinese Exclusion Act create America's first major federal immigration-enforcement system?",
         "suggested_title": "The Law That Built Immigration Enforcement Around Exclusion",
         "why": "A bounded law with documents, enforcement machinery and family consequences.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "What did the 1954 federal campaign known as Operation Wetback do to Mexican immigrants and US citizens?",
         "suggested_title": "America's 1954 Mass-Deportation Campaign",
         "why": "A named operation with a short timeline and documented collateral harm.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the Anti-Drug Abuse Act of 1986's sentencing rules reshape federal punishment?",
         "suggested_title": "The Drug Law That Made Unequal Sentences Automatic",
         "why": "A specific statute avoids a vague history of the entire War on Drugs.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did federal mandatory-minimum drug laws transfer sentencing power from judges to prosecutors?",
         "suggested_title": "The Sentencing Rules That Quietly Shifted Power",
         "why": "The mechanism is institutional but can be shown through one arrest-to-sentence path.",
         "engine_hint": "power_reversal", "status": "research_candidate"},
        {"question": "How did California's 1994 three-strikes law produce extreme sentences for some minor offenses?",
         "suggested_title": "When 'Three Strikes' Turned Minor Crimes Into Life Sentences",
         "why": "A simple public promise produces an escalating and understandable legal mechanism.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the 1984 federal expansion of civil asset forfeiture change policing incentives?",
         "suggested_title": "The Law That Let Police Profit From Property Seizures",
         "why": "The revenue-sharing incentive creates a strong intervention-to-behavior story.",
         "engine_hint": "backfiring_solution", "status": "research_candidate"},
        {"question": "How did federal desegregation orders encounter district resistance and accelerate white flight?",
         "suggested_title": "What Happened When School Integration Met Local Resistance",
         "why": "Court orders, district responses and family movement form a documented causal sequence.",
         "engine_hint": "power_reversal", "status": "research_candidate"},
        {"question": "How did discriminatory administration of the GI Bill limit benefits for Black veterans?",
         "suggested_title": "The GI Bill Built a Middle Class—But Not Equally",
         "why": "One popular program reveals how local administration changed who received its benefits.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did federal public-housing policy build, isolate and later demolish large housing projects?",
         "suggested_title": "Why America Built Huge Housing Projects—Then Tore Them Down",
         "why": "A visible build-to-demolition arc can connect design choices with resident experience.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the 1996 welfare-reform law change cash assistance and work requirements?",
         "suggested_title": "The Law That Remade America's Safety Net",
         "why": "A single statute allows the story to compare its promise with measurable outcomes.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the Agricultural Adjustment Act turn emergency farm relief into a durable subsidy system?",
         "suggested_title": "How Temporary Farm Relief Became Permanent Policy",
         "why": "A crisis intervention becomes a lasting system with changing winners and incentives.",
         "engine_hint": "backfiring_solution", "status": "research_candidate"},
        {"question": "How did the Renewable Fuel Standard reshape American corn, fuel and farmland?",
         "suggested_title": "The Fuel Rule That Reshaped America's Cornfields",
         "why": "One mandate connects energy policy to visible changes in farming and food markets.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the Garn-St Germain Act change savings-and-loan risk before the S&L crisis?",
         "suggested_title": "The Deregulation Bet Behind the Savings-and-Loan Crisis",
         "why": "A named law provides a concrete entry into an otherwise diffuse financial collapse.",
         "engine_hint": "backfiring_solution", "status": "research_candidate"},
        {"question": "How did federal housing and financial rules encourage risk before the subprime mortgage crisis?",
         "suggested_title": "The Incentives That Rewarded Risky Mortgages",
         "why": "The topic is high-interest but must be narrowed to supported rules during research.",
         "engine_hint": "backfiring_solution", "status": "research_candidate"},
        {"question": "Why did President Cleveland send federal troops into the 1894 Pullman Strike?",
         "suggested_title": "The Strike That Brought Federal Troops to an American Company Town",
         "why": "The federal intervention gives this labor story the state action the channel requires.",
         "engine_hint": "power_reversal", "status": "research_candidate"},
        {"question": "Why did the US Army clear the Bonus Army camp in Washington in 1932?",
         "suggested_title": "When the US Army Drove Veterans Out of Washington",
         "why": "A promised benefit, a mass protest and one government order create a compact arc.",
         "engine_hint": "power_reversal", "status": "research_candidate"},
        {"question": "How did the Palmer Raids use fear of radicalism to justify mass arrests and deportations?",
         "suggested_title": "The Raids That Turned Political Fear Into Mass Arrests",
         "why": "A defined federal campaign with vivid raids and due-process consequences.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the FBI's COINTELPRO program secretly disrupt American political movements?",
         "suggested_title": "The Secret FBI Program That Targeted Political Movements",
         "why": "One documented program connects surveillance tactics to identifiable targets and harm.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the US Public Health Service withhold effective treatment in the Tuskegee syphilis study?",
         "suggested_title": "The Government Study That Withheld Treatment for Decades",
         "why": "A bounded federal study with a devastating breach of trust and long aftermath.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did Flint's 2014 water-source switch expose residents to lead?",
         "suggested_title": "The Cost-Cutting Decision That Poisoned Flint's Water",
         "why": "One administrative decision creates a clear infrastructure and public-health chain.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "Why did public officials approve a school and neighborhood at the Love Canal waste site?",
         "suggested_title": "How a Neighborhood Was Built Beside Buried Toxic Waste",
         "why": "Government land-use decisions make the public-policy role specific and researchable.",
         "engine_hint": "accumulating_indictment", "status": "research_candidate"},
        {"question": "How did the US Forest Service's fire-suppression policy increase fuel buildup and wildfire risk?",
         "suggested_title": "America Tried to Stop Every Forest Fire. It Made the Next Ones Worse.",
         "why": "A long-running intervention has strong visual escalation and a classic unintended consequence.",
         "engine_hint": "backfiring_solution", "status": "research_candidate"},
    ],
    # "Why [animal] is a terrible parent." Every candidate names the recorded verdict it overturns;
    # a behaviour nobody ever misread is a nature fact, not an episode of this channel.
    NATURE: [
        {"question": "Why was Oviraptor named 'egg thief' for a nest that turned out to be its own?",
         "suggested_title": "The Dinosaur Named After a Mistake",
         "why": "The reference episode: a 1924 name, a 1994 embryo, a 1995 brooding cousin, and a name that never changed.",
         "engine_hint": "mistaken_verdict", "status": "research_candidate"},
        {"question": "Why does the emperor penguin leave her only egg for two months?",
         "suggested_title": "Why This Penguin Leaves Her Only Egg",
         "why": "No accusation on the record, so a strange_behaviour episode: the constraint (he cannot hunt with the egg), the function (she returns with food at hatching) and the backup (his oesophageal secretion) are all documented.",
         "engine_hint": "strange_behaviour", "status": "research_candidate"},
        {"question": "Why does the giant Pacific octopus stop eating once she lays her eggs?",
         "suggested_title": "The Mother Who Starves on Purpose",
         "why": "A documented months-long brood with a measured fast that looks like self-destruction and is the guarding itself. Research decides whether any account recorded it as such.",
         "engine_hint": "strange_behaviour", "status": "research_candidate"},
        {"question": "Why was the Nile crocodile believed to eat its own hatchlings?",
         "suggested_title": "The Crocodile Accused of Eating Its Young",
         "why": "The jaws that looked like the crime were the transport: hatchlings are carried to water and guarded for weeks.",
         "engine_hint": "mistaken_verdict", "status": "research_candidate"},
        {"question": "Why do sand tiger shark pups eat their siblings before they are born?",
         "suggested_title": "Born Having Already Killed",
         "why": "Intrauterine cannibalism documented since the 1940s, read as horror, that produces one large well-formed pup.",
         "engine_hint": "mistaken_verdict", "status": "research_candidate"},
        {"question": "Why does a kangaroo mother appear to abandon a joey in drought?",
         "suggested_title": "The Joey the Kangaroo Lets Go",
         "why": "Embryonic diapause: three young at three stages, and the pause that looks like abandonment is the reserve.",
         "engine_hint": "strange_behaviour", "status": "research_candidate"},
        {"question": "Why does the Surinam toad's back erupt with babies?",
         "suggested_title": "The Toad That Grows Its Young in Its Skin",
         "why": "A body-horror image with a documented mechanism: eggs embedded in the mother's back until they emerge as toadlets.",
         "engine_hint": "strange_behaviour", "status": "research_candidate"},
        {"question": "Why do Stegodyphus spiderlings eat their mother?",
         "suggested_title": "The Spider Mother Who Is the Last Meal",
         "why": "Matriphagy, documented and measured, looks like the young turning on the parent and is the final act of provisioning.",
         "engine_hint": "strange_behaviour", "status": "research_candidate"},
    ],
}


def editorial_catalogue() -> dict:
    """Free UI data. Corpus coverage describes format examples, never evidence about a topic."""
    import reference_corpus

    coverage = reference_corpus.coverage()
    return {"editorial_version": EDITORIAL_VERSION, "channels": [
        {"id": key, **spec, "topics": [
            {**item, "topic_channel": key, "channel": spec["name"],
             "content_format": "long", "visual_style": "illustrated_story",
             "reference_count": coverage.get(item["engine_hint"], 0)}
            for item in TOPIC_CANDIDATES[key]]}
        for key, spec in CHANNELS.items()]}

# "Why don't Americans eat hippo meat", "why isn't there a cure for X". A question about something
# that never happened has no chain of events to follow, because nothing happened.
_ABSENCE = re.compile(
    r"^\s*why\s+(?:don'?t|doesn'?t|didn'?t|aren'?t|isn'?t|hasn'?t|haven'?t|can'?t|won'?t|"
    r"do\s+we\s+not|does\s+\w+\s+not|is\s+there\s+no|are\s+there\s+no)\b", re.I)
# A year, a century, or a decade. An episode almost always carries one; a standing condition does not.
_TIME_ANCHOR = re.compile(r"\b(1[0-9]\d\d|20\d\d|\d{1,2}(?:st|nd|rd|th)\s+century|\d{4}s)\b", re.I)


def signals(question: str) -> dict:
    """Free, and advisory only. These describe the question's shape, not its worth."""
    text = (question or "").strip()
    return {"absence_framing": bool(_ABSENCE.search(text)),
            "time_anchor": bool(_TIME_ANCHOR.search(text)),
            "words": len(text.split())}


_SYSTEM = (
    "You screen questions for three documentary channels that share a house style and nothing "
    "else. Answer only about the question you are given. Return only JSON.\n\n"
    + "\n\n".join(
        f"{key.upper()} — {spec['name']}\n"
        f"  promise:  {spec['promise']}\n"
        f"  requires: {spec['requires']}\n"
        f"  examples: {spec['examples']}\n"
        f"  excludes: {spec['excludes']}"
        for key, spec in CHANNELS.items())
    + "\n\nSTILL UNFOLDING GOES TO WORLD. When the decision's consequence is still unfolding "
      "today and the film can be told from the present -- a lake still falling, fuel still "
      "reacting, bombs still being found, a cleanup still under way -- it belongs to WORLD, even "
      "when a state or a company made the decision. A state-run campaign against an animal "
      "population is WORLD too.\n"
      "HISTORY KEEPS THE PAST. A state programme judged by what it cost the people subjected to "
      "it, told as history, belongs to HISTORY. A finished story with nothing still unfolding "
      "belongs to neither WORLD nor, unless it is a state programme, HISTORY.\n"
      "NATURE TAKES ONLY WHAT ANIMALS DO. If a human programme is anywhere in the causal chain, "
      "the question belongs to WORLD or HISTORY. NATURE needs either a RECORDED misreading of "
      "the behaviour (a name, a label, a textbook line) or a behaviour that LOOKS like neglect "
      "with a documented constraint and function behind it. Never attribute an accusation "
      "nobody recorded. A behaviour that neither looks strange nor was misread is a nature "
      "fact, not an episode.")


def _prompt(question: str, found: dict, channel: str = "") -> str:
    asked = (f"The operator says this is for the {channel.upper()} channel; say so if it belongs "
             "to one of the others.\n" if channel else
             "Decide which channel it belongs to, or neither.\n")
    return (
        f'QUESTION: "{question}"\n\n{asked}'
        f"Deterministic signals (advisory, may be wrong): asks about something that did NOT happen "
        f"= {found['absence_framing']}; names a date or period = {found['time_anchor']}.\n\n"
        "Answer in order:\n"
        "1. EPISODE — for WORLD or HISTORY: does the question point at ONE documented "
        "intervention, bounded in time and place? A standing condition with many parallel causes "
        "is not one, and neither is something that never happened. For NATURE: does it point at "
        "ONE species and ONE documented behaviour toward its eggs or young that either has ONE "
        "recorded reading as neglect, cruelty, theft or abandonment, or LOOKS like one and has a "
        "documented constraint and function? Say which shape.\n"
        "2. CHANNEL — world, history, nature, or neither, by the definitions above.\n"
        "3. AFTERMATH — for WORLD or HISTORY: what documented thing happened afterwards, to the "
        "animals, the place, the people or the programme's subjects. For WORLD it must be still "
        "unfolding today (a consequence you could report on this year), not only in the past. "
        "This need NOT be the opposite of what was intended: a programme that achieved its aim at "
        "enormous cost still qualifies for HISTORY, and foreseen harm still counts. For NATURE: the documented "
        "evidence that corrected the reading, or the documented function of the behaviour for "
        "the young.\n\n"
        'Return ONLY JSON: {"episode":"the intervention or behaviour in a short phrase, or empty",'
        '"channel":"world|history|nature|neither","intent":"what was being attempted, or for '
        'NATURE the recorded verdict",'
        '"aftermath":"the documented consequence or correcting evidence, or empty",'
        '"verdict":"fits|needs_narrowing|no_story",'
        '"reason":"one sentence a person can act on",'
        '"narrower_question":"if needs_narrowing, the question that names the episode; else empty"}\n'
        "needs_narrowing when a real episode is buried inside a broader question. no_story "
        "when there is no single documented episode, or it belongs to no channel.")


def screen(question: str, *, channel: str = "", judge=None, cost_sink=None) -> dict:
    """Screen one question. Returns a verdict; refusing is the caller's decision.

    `judge(prompt, system=...)` returns the model's raw text. Unreachable or unparseable means
    UNKNOWN, not rejection: a screen that fails closed on an outage refuses good questions for
    reasons that have nothing to do with them.
    """
    found = signals(question)
    if judge is None:
        return {"verdict": "unknown", "reason": "no judge available; not screened",
                "signals": found, "screened": False}
    try:
        raw = judge(_prompt(question, found, channel), system=_SYSTEM)
        data = json.loads(re.search(r"\{.*\}", str(raw), re.S).group(0))
    except Exception as exc:                                # noqa: BLE001 - advisory by design
        return {"verdict": "unknown", "signals": found, "screened": False,
                "reason": f"screen unavailable ({type(exc).__name__}); not screened"}
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in (FITS, NEEDS_NARROWING, NO_STORY):
        verdict = "unknown"
    return {"verdict": verdict, "screened": True, "signals": found,
            "channel": str(data.get("channel", "")).strip().lower(),
            "episode": str(data.get("episode", "")).strip(),
            "intent": str(data.get("intent", "")).strip(),
            "aftermath": str(data.get("aftermath", "")).strip(),
            "narrower_question": str(data.get("narrower_question", "")).strip(),
            "reason": str(data.get("reason", "")).strip()}


def blocks(result: dict) -> bool:
    """Only a confident no_story stops a run, and only when the screen is enforced.

    `needs_narrowing` does not block: the episode is real and the operator may know exactly which
    one they mean. `unknown` never blocks -- an outage is not a verdict about a question.
    """
    return bool(result.get("screened")) and result.get("verdict") == NO_STORY and enforced()


def enforced() -> bool:
    """TOPIC_FIT=off to screen without refusing. On by default: the point is to spend nothing."""
    return os.environ.get("TOPIC_FIT", "on").strip().lower() not in ("0", "off", "false")


def report(question: str, result: dict) -> str:
    if not result.get("screened"):
        return f"[topic] {result.get('reason', 'not screened')}"
    channel = CHANNELS.get(result.get("channel", ""), {}).get("name", result.get("channel") or "—")
    lines = [f"[topic] {result['verdict'].upper()} ({channel}): {result.get('reason', '')}"]
    if result.get("episode"):
        lines.append(f"        intervention: {result['episode']}")
    if result.get("aftermath"):
        lines.append(f"        aftermath:    {result['aftermath']}")
    elif result["verdict"] != FITS:
        lines.append("        aftermath:    none found — every channel needs one documented "
                     "episode and what documentably followed or corrected it")
    if result.get("narrower_question"):
        lines.append(f'        try:       "{result["narrower_question"]}"')
    return "\n".join(lines)

"""Does this question belong to one of the channels, asked before any research is bought.

Measured cost of not asking: "Why don't Americans eat hippo meat?" spent $3.20 across four runs and
never produced a spine. Not the engine and not the budget -- the question names an ABSENCE with
parallel causes, so research returned 21 verified claims split between a 1910 congressional episode
and modern African conservation. One spine cannot be built from two stories.

TWO CHANNELS, TWO TESTS. An earlier version of this file had one: the outcome had to INVERT the
intent. That was derived from a corpus which happens to be mostly backfires, and it turned a
pattern into a law -- it would have refused the Aral Sea, where the river diversion did exactly
what it was designed to do. Cotton grew. The lake was the price, not a reversal.

    world    an intervention aimed at an ANIMAL POPULATION, and what happened to it afterwards.
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

WORLD, HISTORY = "world", "history"
EDITORIAL_VERSION = "bolt_two_channels_v2_us_history"
CHANNELS = {
    WORLD: {
        "name": "Bolt Explains the World",
        "banner": "ANIMAL CONTROL. UNEXPECTED CONSEQUENCES.",
        "promise": "What humans did to animal populations -- and what happened next.",
        "requires": "an intervention aimed at an ANIMAL POPULATION (a bounty, an eradication "
                    "campaign, a deliberate introduction, a predator-removal programme) and a "
                    "documented aftermath for that population or the ecosystem around it. The "
                    "intervention must TARGET the animals: diverting a river and ruining a "
                    "fishery is not this channel, because nobody was intervening on the fish",
        "examples": "Hanoi's 1902 rat-tail bounty and the rat farms it created; China's Four "
                    "Pests sparrow campaign; Australia's cane toads, introduced against beetles "
                    "and now the pest; Hawaii's mongooses, released for rats they barely touched",
        "excludes": "general animal facts, animal quizzes, food explainers, unrealized proposals "
                    "such as the American hippo-import plan, and environmental disasters where no "
                    "animal population was the target",
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
}

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
    "You screen questions for two documentary channels that share a house style and nothing else. "
    "Answer only about the question you are given. Return only JSON.\n\n"
    + "\n\n".join(
        f"{key.upper()} — {spec['name']}\n"
        f"  promise:  {spec['promise']}\n"
        f"  requires: {spec['requires']}\n"
        f"  examples: {spec['examples']}\n"
        f"  excludes: {spec['excludes']}"
        for key, spec in CHANNELS.items())
    + "\n\nANIMALS WIN TIES. A state-run campaign against an animal population belongs to WORLD, "
      "not HISTORY, even though a government ran it. Otherwise HISTORY absorbs almost everything "
      "and the two channels collapse back into one.")


def _prompt(question: str, found: dict, channel: str = "") -> str:
    asked = (f"The operator says this is for the {channel.upper()} channel; say so if it belongs "
             "to the other one.\n" if channel else
             "Decide which channel it belongs to, or neither.\n")
    return (
        f'QUESTION: "{question}"\n\n{asked}'
        f"Deterministic signals (advisory, may be wrong): asks about something that did NOT happen "
        f"= {found['absence_framing']}; names a date or period = {found['time_anchor']}.\n\n"
        "Answer in order:\n"
        "1. INTERVENTION — does the question point at ONE documented intervention, bounded in "
        "time and place? A standing condition with many parallel causes is not one, and neither "
        "is something that never happened.\n"
        "2. CHANNEL — world, history, or neither, by the definitions above.\n"
        "3. AFTERMATH — what documented thing happened afterwards, to the animal population or to "
        "the people subjected to the programme. This need NOT be the opposite of what was "
        "intended: a programme that achieved its aim at enormous cost still qualifies for "
        "HISTORY, and foreseen harm still counts.\n\n"
        'Return ONLY JSON: {"episode":"the intervention in a short phrase, or empty",'
        '"channel":"world|history|neither","intent":"what was being attempted",'
        '"aftermath":"the documented consequence, or empty",'
        '"verdict":"fits|needs_narrowing|no_story",'
        '"reason":"one sentence a person can act on",'
        '"narrower_question":"if needs_narrowing, the question that names the intervention; else empty"}\n'
        "needs_narrowing when a real intervention is buried inside a broader question. no_story "
        "when there is no single documented intervention, or it belongs to neither channel.")


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
        lines.append("        aftermath:    none found — both channels need one documented "
                     "intervention and what documentably followed it")
    if result.get("narrower_question"):
        lines.append(f'        try:       "{result["narrower_question"]}"')
    return "\n".join(lines)

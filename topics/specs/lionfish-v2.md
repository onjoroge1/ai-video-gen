# Spec: What Happens When Florida Gets Good at Catching Lionfish?

Lionfish v2 (operator, 2026-10-21) restated as a spec: the ChatGPT-revised narration built around
Paul Carlson, with the quotes that jobs/lionfish-v2/hand_build.py typed by hand (c70-c86) and the
older ledger claims it cites. Evidence labels follow the story-contract lane's
lionfish_v2_story_kinds fixture. The operator ruled this is not a consequence video; the import
must say so before any spend.

```json
{
 "spec_version": 1,
 "slug": "lionfish-v2",
 "channel": "world",
 "duration_sec": 300,
 "title": "What Happens When Florida Gets Good at Catching Lionfish?",
 "decision": {
  "what": "NOAA's 'Eat Lionfish' campaign: put the invader on the menu so that divers catch it and a market keeps the catching going",
  "who": "NOAA",
  "when": "2010",
  "kind": "animal_targeted",
  "cite": [
   "c31"
  ]
 },
 "consequence": {
  "what": "The better removals work, the fewer fish each trip brings back and the less a lionfish fishery can earn",
  "cite": [
   "c77",
   "c78",
   "c80"
  ]
 },
 "still_unfolding": {
  "what": "Florida divers removed a record 36,187 lionfish in the 2026 Lionfish Challenge",
  "as_of": "2026",
  "cite": [
   "c85"
  ]
 },
 "central_question": "What Happens When Florida Gets Good at Catching Lionfish?",
 "ending_answer": "Keep each reef below its own threshold: native fish recover before the last lionfish is gone, and partial removal takes 30 percent less time.",
 "human": {
  "person": "Paul Carlson, 2025 Lionfish King (Recreational Division)",
  "want": "to hunt lionfish and eat them",
  "detail": "73 dive trips, 1,542 lionfish: \"My freezer is full.\""
 },
 "forbidden_claims": [
  "eating lionfish will end the invasion",
  "lionfish can be eradicated from Florida"
 ],
 "recurring_image": "a full chest freezer of lionfish fillets",
 "render": {
  "palette": "natural",
  "music_mix": "ambient_pad"
 },
 "sources": {
  "cbs12": "https://cbs12.com/news/local/florida-divers-remove-record-36187-invasive-lionfish-in-statewide-challenge-2026-lionfish-challenge-533-participants-1468-dive-trips-may-22-september-14",
  "fwc": "https://myfwc.com/wildlifehabitats/nonnatives/marine-species/lionfish/",
  "green2012": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3296711/fullTextXML",
  "green2014": "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:10.1890/13-0979.1&resultType=core&format=xml",
  "harris": "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=DOI:10.1007/s10530-023-02998-5&resultType=core&format=xml",
  "int-res": "https://www.int-res.com/articles/meps2008/367/m367p233.pdf",
  "media": "https://media.fisheries.noaa.gov/dam-migration/lionfish_factsheet.pdf",
  "myfwc": "https://myfwc.com/news/all-news/lionfish-winners-925/",
  "myfwc2": "https://myfwc.com/fishing/saltwater/recreational/lionfish/",
  "noaa_threat": "https://oceanservice.noaa.gov/facts/lionfish.html",
  "sciencedaily": "https://sciencedaily.com/releases/2010/08/100807205021.htm",
  "uf": "https://blogs.ifas.ufl.edu/news/2023/02/19/uf-study-helps-explain-why-market-for-invasive-lionfish-remains-small/",
  "usgs": "https://nas.er.usgs.gov/queries/FactSheet.aspx?speciesID=963",
  "wgcu": "https://www.wgcu.org/environment/2025-09-23/winners-announced-in-fwcs-annual-lionfish-challenge"
 },
 "narration": [
  {
   "say": "You want dinner.",
   "part": "opening"
  },
  {
   "say": "Florida would like you to eat an invasion.",
   "claims": [
    {
     "id": "c31",
     "source": "sciencedaily",
     "quote": "NOAA has developed an \"Eat Lionfish\" campaign that brings together fishing communities, wholesalers, and chefs in an effort to broaden U.",
     "kind": "event",
     "evidence": "documented",
     "claim": "NOAA developed an 'Eat Lionfish' campaign bringing together fishing communities, wholesalers and chefs to broaden U.S. consumers' awareness of the invader."
    }
   ]
  },
  {
   "say": "Paul Carlson can recommend the fish.",
   "claims": [
    {
     "id": "c70",
     "source": "wgcu",
     "quote": "\"My freezer is full. It's better than hogfish and better than grouper. If I had a choice between a lobster and a lionfish, I'd take the lionfish,\" he said.",
     "kind": "event",
     "evidence": "documented",
     "claim": "Paul Carlson said: 'My freezer is full. It's better than hogfish and better than grouper. If I had a choice between a lobster and a lionfish, I'd take the lionfish.'"
    }
   ]
  },
  {
   "say": "In the summer of 2025, he made seventy-three dive trips and removed more than fifteen hundred lionfish.",
   "claims": [
    {
     "id": "c42",
     "source": "myfwc",
     "quote": "Paul Carlson of Palm Beach County earned the prestigious title of Lionfish King in the Recreational Division by removing 1,542 lionfish over 73 dive trips.",
     "kind": "event",
     "evidence": "documented",
     "claim": "Paul Carlson of Palm Beach County earned the title of Lionfish King in the 2025 Recreational Division by removing 1,542 lionfish over 73 dive trips."
    }
   ]
  },
  {
   "say": "His report afterward?"
  },
  {
   "say": "\"My freezer is full.\"",
   "claims": [
    "c70"
   ]
  },
  {
   "say": "The plan sounds delicious."
  },
  {
   "say": "But for people catching lionfish for a living, there's a strange problem: what happens when you get good at removing the thing you're paid to catch?",
   "claims": [
    {
     "id": "c77",
     "source": "harris",
     "quote": "However, reducing an invasive species’ population will reduce their catch rates and can make their harvest uneconomical.",
     "kind": "mechanism",
     "evidence": "interpretation",
     "claim": "Reducing an invasive species' population reduces catch rates and can make its harvest uneconomical."
    }
   ]
  },
  {
   "say": "You can see why people wanted lionfish in aquariums.",
   "claims": [
    {
     "id": "c86",
     "source": "noaa_threat",
     "quote": "Experts speculate that people have been dumping unwanted lionfish from home aquariums into the Atlantic Ocean for more than 25 years.",
     "kind": "context",
     "evidence": "interpretation",
     "claim": "Experts speculate that people have been dumping unwanted lionfish from home aquariums into the Atlantic for more than 25 years."
    }
   ]
  },
  {
   "say": "Stripes."
  },
  {
   "say": "Flowing fins."
  },
  {
   "say": "A fish dressed like it's expecting photographers."
  },
  {
   "say": "The trouble began when they turned up outside the glass.",
   "claims": [
    "c86"
   ]
  },
  {
   "say": "Lionfish are native to the Indo-Pacific.",
   "claims": [
    {
     "id": "c34",
     "source": "media",
     "quote": "In their native range, lionfish populations are controlled by predation, competition, and disease. In the Atlantic, Gulf of Mexico, and Caribbean they encounter few predators and are capable of reproduction year-round in warm waters.",
     "kind": "mechanism",
     "evidence": "interpretation",
     "claim": "In their native range lionfish populations are controlled by predation, competition and disease, but in the Atlantic, Gulf of Mexico and Caribbean they encounter few predators and can reproduce year-round in warm waters."
    }
   ]
  },
  {
   "say": "The aquarium trade is the most likely way they reached the Atlantic.",
   "claims": [
    {
     "id": "c01",
     "source": "usgs",
     "quote": "Means of Introduction: The most probable explanation for the arrival of lionfishes in the Atlantic Ocean is via the aquarium trade (Whitfield et al.",
     "kind": "mechanism",
     "evidence": "interpretation",
     "claim": "The most probable explanation for the arrival of lionfishes in the Atlantic Ocean is via the aquarium trade."
    }
   ]
  },
  {
   "say": "Here, they found small fish to eat and very few predators to keep their numbers down.",
   "claims": [
    "c34",
    {
     "id": "c08",
     "source": "usgs",
     "quote": "Other than cannibalism, there are few documented natural predators of the lionfish.",
     "kind": "context",
     "evidence": "documented",
     "claim": "Other than cannibalism, there are few documented natural predators of the lionfish."
    }
   ]
  },
  {
   "say": "And those small fish matter."
  },
  {
   "say": "Some, like parrotfish, graze on the seaweed that can overgrow coral.",
   "claims": [
    {
     "id": "c81",
     "source": "usgs",
     "quote": "In addition, lionfish have the potential to decrease the abundance of ecologically important species such as parrotfish and other herbivorous fishes that keep seaweeds and macroalgae from overgrowing corals.",
     "kind": "context",
     "evidence": "interpretation",
     "claim": "Lionfish can decrease parrotfish and other herbivorous fishes that keep seaweeds and macroalgae from overgrowing corals."
    }
   ]
  },
  {
   "say": "Others are food for larger native fish.",
   "claims": [
    {
     "id": "c82",
     "source": "usgs",
     "quote": "The reduction in recruitment of coral-reef fishes suggests that lionfish may also compete with native piscivores by monopolizing this important food resource.",
     "kind": "context",
     "evidence": "interpretation",
     "claim": "By taking young reef fish, lionfish may compete with native fish-eating predators for this food resource."
    }
   ]
  },
  {
   "say": "In one five-week experiment, reefs with a single lionfish gained, on average, nearly eighty percent fewer young native fish than reefs without one.",
   "claims": [
    {
     "id": "c07",
     "source": "usgs",
     "quote": ", accumulation of new juvenile fishes via settlement of larvae) was reduced by 79% on reefs with a single lionfish compared to reefs with no lionfish.",
     "kind": "outcome",
     "evidence": "documented",
     "claim": "Over a five-week experiment, net recruitment of juvenile fishes was reduced by 79% on reefs with a single lionfish compared to reefs with no lionfish."
    },
    {
     "id": "c20",
     "source": "int-res",
     "quote": "Lionfish caused significant reductions in the recruitment of native fishes by an average of 79% over the 5 wk duration of the experiment.",
     "kind": "outcome",
     "evidence": "documented",
     "claim": "In a controlled experiment, lionfish caused significant reductions in the recruitment of native fishes by an average of 79% over the 5-week duration."
    }
   ]
  },
  {
   "say": "One fish."
  },
  {
   "say": "A very busy mouth."
  },
  {
   "say": "So NOAA set out to put that mouth on the menu.",
   "part": "attempt",
   "claims": [
    "c31"
   ]
  },
  {
   "say": "Its Eat Lionfish campaign brought together fishers, wholesalers and chefs.",
   "claims": [
    "c31"
   ]
  },
  {
   "say": "And no fishing license is needed to spear one.",
   "claims": [
    {
     "id": "c17",
     "source": "myfwc2",
     "quote": "A recreational fishing license is not required for recreational fishers targeting lionfish while using a pole spear, a Hawaiian Sling, a handheld net or any spearing device that is specifically designed and marketed exclusively for lionfish.",
     "kind": "context",
     "evidence": "documented",
     "claim": "A recreational fishing license is not required for recreational fishers targeting lionfish while using a pole spear, a Hawaiian Sling, a handheld net or any spearing device designed and marketed exclusively for lionfish."
    }
   ]
  },
  {
   "say": "The idea: divers catch the invader, chefs turn it into dinner, and a market keeps the catching going.",
   "claims": [
    "c31"
   ]
  },
  {
   "say": "Government advice you could serve with lemon."
  },
  {
   "say": "So for a diver, there is something satisfying about such a clear task.",
   "claims": [
    {
     "id": "c71",
     "source": "wgcu",
     "quote": "\"I just love killing lionfish, it sounds horrible, because it's so beautiful, but I love hunting them, getting them.\"",
     "kind": "event",
     "evidence": "documented",
     "claim": "Carlson said he loves hunting lionfish."
    }
   ]
  },
  {
   "say": "Picture yourself underwater."
  },
  {
   "say": "A lionfish hovers against the reef."
  },
  {
   "say": "You get close, line up your spear, and make the catch.",
   "claims": [
    "c17"
   ]
  },
  {
   "say": "Carefully: those spines carry venom.",
   "claims": [
    {
     "id": "c14",
     "source": "fwc",
     "quote": "Lionfish have 18 venomous spines that are used defensively against predators.",
     "kind": "context",
     "evidence": "documented",
     "claim": "Lionfish have 18 venomous spines that are used defensively against predators."
    }
   ]
  },
  {
   "say": "Into the collecting bag."
  },
  {
   "say": "On to the next fish."
  },
  {
   "say": "You can see your progress."
  },
  {
   "say": "Every fish you bring up is one fewer predator on that reef."
  },
  {
   "say": "Across Florida, those catches add up: the 2026 Lionfish Challenge removed a record 36,187 fish.",
   "claims": [
    {
     "id": "c85",
     "source": "cbs12",
     "quote": "Florida divers removed 36,187 invasive lionfish from state waters during this year’s Florida Fish and Wildlife Conservation Commission Lionfish Challenge, setting a record for the statewide tournament, according to FWC.",
     "kind": "event",
     "evidence": "documented",
     "claim": "Florida divers removed a record 36,187 lionfish in the 2026 FWC Lionfish Challenge."
    }
   ]
  },
  {
   "say": "But the competition ends.",
   "part": "complication",
   "claims": [
    "c85"
   ]
  },
  {
   "say": "The fish keep breeding.",
   "claims": [
    {
     "id": "c13",
     "source": "fwc",
     "quote": "Lionfish can spawn every four days in warmer climates.",
     "kind": "mechanism",
     "evidence": "documented",
     "claim": "Lionfish can spawn every four days in warmer climates."
    }
   ]
  },
  {
   "say": "Why?"
  },
  {
   "say": "In warm water, a lionfish can spawn about every four days.",
   "claims": [
    "c13"
   ]
  },
  {
   "say": "Their young drift on ocean currents, so the reef you cleared is still connected to the rest of the sea.",
   "claims": [
    {
     "id": "c83",
     "source": "green2012",
     "quote": "Lionfish were first reported off the southeast coast of Florida in the 1980s and have since become established to varying extents across the entire Caribbean region via larval dispersal in ocean currents [2] .",
     "kind": "mechanism",
     "evidence": "documented",
     "claim": "Lionfish became established across the Caribbean via larval dispersal in ocean currents."
    }
   ]
  },
  {
   "say": "And the fish aren't all waiting at convenient depths.",
   "claims": [
    {
     "id": "c10",
     "source": "usgs",
     "quote": ", wrecks) at depths from just a few inches of water to over 300 m.",
     "kind": "context",
     "evidence": "documented",
     "claim": "Lionfish inhabit natural reef and artificial structure at depths from just a few inches of water to over 300 m."
    }
   ]
  },
  {
   "say": "Lionfish also live hundreds of feet down, beyond the reach of ordinary recreational dives.",
   "claims": [
    "c10",
    {
     "id": "c49",
     "source": "uf",
     "quote": "fishers generally need to dive fairly deep, often past 130 feet, which requires trained and experienced divers.",
     "kind": "mechanism",
     "evidence": "interpretation",
     "claim": "UF researcher Holden Harris noted that to find high lionfish densities fishers generally need to dive fairly deep, often past 130 feet, which requires trained and experienced divers."
    }
   ]
  },
  {
   "say": "Your appetite can be enormous."
  },
  {
   "say": "Your time underwater cannot."
  },
  {
   "say": "That is what sits behind Paul's seventy-three trips: find the fish, bring them up, go out again.",
   "part": "development",
   "claims": [
    "c42"
   ]
  },
  {
   "say": "Paul loves the hunt, and he competed for fun.",
   "claims": [
    "c71",
    "c42"
   ]
  },
  {
   "say": "But now put yourself on a commercial boat, trying to earn a living from the catch.",
   "claims": [
    {
     "id": "c48",
     "source": "uf",
     "quote": "the profit margins for commercially harvested lionfish are relatively low. This may explain why many commercial fishers aren’t targeting the species.",
     "kind": "outcome",
     "evidence": "model",
     "claim": "A UF study showed that under current economic conditions the profit margins for commercially harvested lionfish are relatively low, which may explain why many commercial fishers aren't targeting the species."
    }
   ]
  },
  {
   "say": "What does each trip cost?"
  },
  {
   "say": "Fuel, and the time you spend searching instead of catching.",
   "claims": [
    "c48"
   ]
  },
  {
   "say": "Then suppose the removals work.",
   "claims": [
    "c77"
   ]
  },
  {
   "say": "There are fewer lionfish on the reef.",
   "claims": [
    "c77"
   ]
  },
  {
   "say": "Good news, until you try to fill the next order.",
   "claims": [
    "c77"
   ]
  },
  {
   "say": "Now, you search longer.",
   "claims": [
    "c77"
   ]
  },
  {
   "say": "You bring back fewer fish.",
   "claims": [
    "c77"
   ]
  },
  {
   "say": "Researchers who modelled a lionfish fishery in the northeastern Gulf of Mexico found its potential profits were already slim.",
   "claims": [
    {
     "id": "c78",
     "source": "harris",
     "quote": "Our models projected that a stable OAE fishery could develop, but that the potential profits in the fishery were relatively small.",
     "kind": "outcome",
     "evidence": "model",
     "claim": "A bioeconomic model of lionfish on artificial reefs in the northeastern Gulf of Mexico projected that potential profits in the fishery were relatively small."
    },
    {
     "id": "c79",
     "source": "harris",
     "quote": "We examined this apparent paradox with a bioeconomic case study of invasive lionfish (Pterois volitans) on artificial reefs in the northeastern Gulf of Mexico (nGOM).",
     "kind": "context",
     "evidence": "documented",
     "claim": "The study was a bioeconomic case study of invasive lionfish on artificial reefs in the northeastern Gulf of Mexico."
    }
   ]
  },
  {
   "say": "So the plan can run out of profit long before the ocean runs out of lionfish.",
   "claims": [
    {
     "id": "c80",
     "source": "uf",
     "quote": "We also note that reducing lionfish stocks over time through commercial fishing would make the fishery less economically sustainable.",
     "kind": "outcome",
     "evidence": "interpretation",
     "claim": "UF researchers noted that reducing lionfish stocks over time through commercial fishing would make the fishery less economically sustainable."
    },
    "c77"
   ]
  },
  {
   "say": "So what do you do?",
   "part": "ending"
  },
  {
   "say": "Keep paying people to search for the very last one?"
  },
  {
   "say": "Researchers tested that question on 24 small reefs in the Bahamas for 18 months.",
   "claims": [
    {
     "id": "c72",
     "source": "green2014",
     "quote": "monitoring the consequences for native fish populations on 24 Bahamian patch reefs over 18 months.",
     "kind": "context",
     "evidence": "documented",
     "claim": "Researchers monitored the consequences of lionfish removal for native fish on 24 Bahamian patch reefs over 18 months."
    }
   ]
  },
  {
   "say": "Where they kept lionfish below the level expected to harm the local fish, the weight of native prey fish rose by 50 to 70 percent.",
   "claims": [
    {
     "id": "c73",
     "source": "green2014",
     "quote": "On reefs where lionfish were kept below threshold densities, native prey fish biomass increased by 50–70%.",
     "kind": "outcome",
     "evidence": "documented",
     "claim": "On reefs where lionfish were kept below threshold densities, native prey fish biomass increased by 50-70%."
    }
   ]
  },
  {
   "say": "The surprising part: removing just enough lionfish to stay below each reef's threshold produced gains similar to removing them all, and took about 30 percent less time.",
   "claims": [
    {
     "id": "c74",
     "source": "green2014",
     "quote": "Crucially, similar gains in prey fish biomass were realized on reefs subjected to partial and full removal of lionfish, but partial removals took 30% less time to implement.",
     "kind": "outcome",
     "evidence": "documented",
     "claim": "Similar gains in prey fish biomass came from partial and full removal of lionfish, but partial removals took 30% less time."
    },
    {
     "id": "c75",
     "source": "green2014",
     "quote": "Reductions in density of 25–92%, depending on the reef, were required to suppress lionfish below levels predicted to overconsume prey.",
     "kind": "outcome",
     "evidence": "model",
     "claim": "Reductions in lionfish density of 25-92%, depending on the reef, were required to suppress lionfish below levels predicted to overconsume prey."
    }
   ]
  },
  {
   "say": "The native fish could benefit before the last lionfish was gone.",
   "claims": [
    "c74"
   ]
  },
  {
   "say": "Instead, the effort gets a more practical target: work out how much removal each reef needs, then keep that effort going.",
   "claims": [
    {
     "id": "c76",
     "source": "green2014",
     "quote": "However, our model provides a method for setting reef-specific targets for population control using local monitoring data.",
     "kind": "context",
     "evidence": "model",
     "claim": "The researchers' model provides a method for setting reef-specific targets for lionfish control using local monitoring data."
    },
    "c75"
   ]
  },
  {
   "say": "It won't work the same everywhere.",
   "claims": [
    "c76"
   ]
  },
  {
   "say": "You have to count the native fish, not just the catch.",
   "claims": [
    "c76"
   ]
  },
  {
   "say": "And dinner won't pay for every trip.",
   "claims": [
    "c48"
   ]
  },
  {
   "say": "Competitions give divers another reason to join in.",
   "claims": [
    "c85"
   ]
  },
  {
   "say": "Paul won Florida's Lionfish King title for his summer's work.",
   "claims": [
    "c42"
   ]
  },
  {
   "say": "He told a reporter he'd take lionfish over lobster.",
   "claims": [
    "c70"
   ]
  },
  {
   "say": "What did Paul get out of it?"
  },
  {
   "say": "A hunt he enjoys, and a title."
  },
  {
   "say": "Seventy-three trips, and a full freezer."
  },
  {
   "say": "But the bigger prize is what those trips can leave on a reef: young native fish with a chance to grow up."
  },
  {
   "say": "That's the part of a full freezer you never see."
  }
 ]
}
```

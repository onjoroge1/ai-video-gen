# HotD S3E3 — 18-asset minimum viable package (spec §8)

| # | Asset | How made | Cost |
|---|---|---|---|
| 1-11 | Heraldic character cards | code-drawn template + generated sigil | $0 |
| 12-16 | Location plates | gpt-image-2 matte paintings | $0.53 total |
| 17-18 | Strategic map · Ormund deception route | code-drawn annotation over the supplied Westeros map | $0 |

Plus 6 reusable heraldic sigils (`sigils/`) tinted per faction at composite time.

## IP posture — unchanged from S3E2
No character likenesses, no episode footage, no actor named in any prompt. Characters are represented
by **house heraldry + role + status**, which is what a politics explainer actually needs. Locations are
original stylised matte paintings ("no recognisable faces, not resembling any film or television
production"). Follows spec §9: "Prefer original stylized visuals and diagrams over continuous episode
footage."

## Spec §9 compliance
- One card template for every character; faction / role / status beneath each name. ✔
- Status wording exact: `missing`, `decoy · not the prince`, `crowned · not anointed`,
  `captive · exposed the decoy`, `at large with Ormund`. ✔
- The false Daeron uses a **cracked slashed mask, never a dragon** — cannot be misread as the prince. ✔
- Tessarion is never shown in Team Black's possession (Daeron's card states "rides Tessarion",
  faction Green, "at large with Ormund"). ✔
- Team Black = crimson/gold; Hightower = muted green-gold; Faith = pale gold. ✔

## Still to build (beyond the minimum 18)
8 dragon cards, ~11 further locations, 7 more infographics (government dashboard, three-powers diagram,
rat-banquet causal chain, show-vs-book timeline, winner scoreboard), and 20+ supporting/memory
characters. All character cards are one row of data each in `hotd_assets.CHARACTERS`.

## Regenerate
    /opt/homebrew/bin/python3 hotd_assets.py        # cards + infographics (free, instant)
    /opt/homebrew/bin/python3 hotd_gen_assets.py    # sigils + locations (reuses existing files)

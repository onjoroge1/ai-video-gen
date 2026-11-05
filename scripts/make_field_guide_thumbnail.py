#!/usr/bin/env python3
"""Overlay a Can't Undo Field Guide headline and "YOU" arrow on a painted picture ($0).

  python scripts/make_field_guide_thumbnail.py jobs/lionfish-v2/thumbs_field_guide/hybrid/bg.png \
      out.jpg --headline "WRONG OCEAN" --you 0.174,0.572 --focus-y 0.48 \
      --transcript jobs/lionfish-v2/transcript.txt

The picture should already show one giant animal and one tiny person with calm space at the top
for the headline. --transcript refuses a headline number the film never speaks.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import field_guide_thumbnail as ft  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("picture")
    ap.add_argument("out")
    ap.add_argument("--headline", required=True, help="two words, or 'A / B'")
    ap.add_argument("--you", help="person position x,y as 0-1 fractions of the 1280x720 frame")
    ap.add_argument("--side", choices=("left", "right"), default="left")
    ap.add_argument("--focus-y", type=float, default=0.5)
    ap.add_argument("--transcript")
    args = ap.parse_args()
    if args.transcript:
        import backfire_packaging as bp
        with open(args.transcript) as handle:
            if not bp.numbers_supported(args.headline, handle.read()):
                print(f"headline number is not spoken in {args.transcript}: {args.headline!r}")
                return 2
    you = tuple(float(v) for v in args.you.split(",")) if args.you else None
    print(ft.compose(args.picture, args.out, headline=args.headline, you_at=you, side=args.side,
                     focus_y=args.focus_y))
    return 0


if __name__ == "__main__":
    sys.exit(main())

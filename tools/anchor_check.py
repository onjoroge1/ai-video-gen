"""Render every muzzle anchor as a crosshair on its plate, side by side, so a human can see whether
the constants are right. Eight of nine were wrong the first time because they were never looked at."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw
from sim import physics_scenes as PS

def main(out):
    seen, order = {}, []
    for sid, (stem, wk, mz) in PS.SCENES.items():
        if stem in seen: continue
        seen[stem] = (sid, mz); order.append(stem)
    ims = []
    for stem in order:
        sid, mz = seen[stem]
        im = Image.open(f"{PS.CLEAN}/{stem}.png").convert("RGB").resize((640, 1138))
        d = ImageDraw.Draw(im); x, y = mz[0]*640, mz[1]*1138
        d.line([(x-52,y),(x+52,y)], fill=(255,40,40), width=5)
        d.line([(x,y-52),(x,y+52)], fill=(255,40,40), width=5)
        d.ellipse([x-16,y-16,x+16,y+16], outline=(255,40,40), width=5)
        d.text((12,12), f"{sid} ({mz[0]:.3f},{mz[1]:.3f})", fill=(255,240,120))
        ims.append(im)
    sh = Image.new("RGB", (420*len(ims), 747))
    for i, im in enumerate(ims): sh.paste(im.resize((420,747)), (420*i, 0))
    sh.save(out); print(f"{len(ims)} anchors -> {out}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "anchors.png")

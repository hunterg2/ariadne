"""Make a folder of small PNGs that look like generator output, for manual
testing and the browser tests.

    py -3 scripts/make_sample_library.py OUT_DIR [COUNT]

Every file carries an A1111-style "parameters" chunk (prompt, negative,
steps, sampler, CFG, seed, size, model), so the index has something to
read and search. Colours and subjects vary per image so tiles can be told
apart. Nothing here imports from tests/.
"""

import os
import random
import sys

from PIL import Image, ImageDraw, PngImagePlugin

SUBJECTS = ["a red fox", "a castle at dusk", "a dragon over mountains", "a rainy street",
            "an orange cat", "a sailing ship", "a lighthouse", "a forest path",
            "a city skyline", "a teacup", "an owl", "a mountain lake"]
MODELS = ["realvisXL_v4", "juggernautXL_v9", "dreamshaper_8"]
SAMPLERS = ["Euler a", "DPM++ 2M Karras", "DDIM"]


def make_png(path, index, width=96, height=72):
    rnd = random.Random(index)
    subject = SUBJECTS[index % len(SUBJECTS)]
    seed = 100000 + index * 7919
    im = Image.new("RGB", (width, height),
                   (rnd.randint(40, 220), rnd.randint(40, 220), rnd.randint(40, 220)))
    draw = ImageDraw.Draw(im)
    draw.rectangle([4, 4, width - 5, height - 5], outline=(255, 255, 255))
    draw.ellipse([width // 3, height // 4, 2 * width // 3, 3 * height // 4],
                 fill=(rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255)))
    draw.text((8, height - 16), f"#{index:03d}", fill=(255, 255, 255))
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters",
                  f"{subject}, highly detailed, sample {index}\nNegative prompt: blurry, lowres\n"
                  f"Steps: {20 + index % 15}, Sampler: {SAMPLERS[index % len(SAMPLERS)]}, "
                  f"CFG scale: {5 + index % 5}, Seed: {seed}, Size: {width}x{height}, "
                  f"Model: {MODELS[index % len(MODELS)]}")
    im.save(path, pnginfo=info)
    return path


def main(argv):
    if not argv:
        sys.exit("usage: make_sample_library.py OUT_DIR [COUNT]")
    out = argv[0]
    count = int(argv[1]) if len(argv) > 1 else 24
    os.makedirs(out, exist_ok=True)
    for i in range(count):
        make_png(os.path.join(out, f"sample_{i:03d}.png"), i)
    print(f"{count} images in {out}")


if __name__ == "__main__":
    main(sys.argv[1:])

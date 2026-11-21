"""Build Chives' investor monograms from letter shapes; keep existing card URLs stable."""
from hashlib import sha256
from pathlib import Path
import json

from PIL import Image, ImageDraw

CARDS = Path(__file__).resolve().parents[1] / "presets/investor-styles"
SOURCE = "https://github.com/xionglaoshi/chives/blob/main/scripts/render-investor-marks.py"
LICENCE = "https://github.com/xionglaoshi/chives/blob/main/LICENSE"

# Five columns per row. Artwork is drawn from these coordinates, without a font or photograph.
GLYPHS = {
    "A": [14, 17, 17, 31, 17, 17, 17], "B": [30, 17, 17, 30, 17, 17, 30],
    "C": [15, 16, 16, 16, 16, 16, 15], "D": [28, 18, 17, 17, 17, 18, 28],
    "E": [31, 16, 16, 30, 16, 16, 31], "F": [31, 16, 16, 30, 16, 16, 16],
    "G": [15, 16, 16, 23, 17, 17, 15], "H": [17, 17, 17, 31, 17, 17, 17],
    "I": [31, 4, 4, 4, 4, 4, 31], "J": [7, 2, 2, 2, 2, 18, 12],
    "K": [17, 18, 20, 24, 20, 18, 17], "L": [16, 16, 16, 16, 16, 16, 31],
    "M": [17, 27, 21, 21, 17, 17, 17], "N": [17, 25, 25, 21, 19, 19, 17],
    "O": [14, 17, 17, 17, 17, 17, 14], "P": [30, 17, 17, 30, 16, 16, 16],
    "Q": [14, 17, 17, 17, 21, 18, 13], "R": [30, 17, 17, 30, 20, 18, 17],
    "S": [15, 16, 16, 14, 1, 1, 30], "T": [31, 4, 4, 4, 4, 4, 4],
    "U": [17, 17, 17, 17, 17, 17, 14], "V": [17, 17, 17, 17, 17, 10, 4],
    "W": [17, 17, 17, 21, 21, 27, 17], "X": [17, 17, 10, 4, 10, 17, 17],
    "Y": [17, 17, 10, 4, 4, 4, 4], "Z": [31, 1, 2, 4, 8, 16, 31],
}
PALETTES = [
    ("#102b26", "#b7f4c2", "#61b995"), ("#1b283a", "#c8e5ff", "#7cacc5"),
    ("#2b2131", "#f0d4e6", "#b387af"), ("#303021", "#eee6ac", "#aba374"),
    ("#173038", "#b7f1ec", "#68aaa9"), ("#35261f", "#f6dbc2", "#c09274"),
]


def render(person, path):
    names = person["englishName"].upper().split()
    letters = names[0][0] + names[-1][0]
    background, ink, accent = PALETTES[sha256(person["id"].encode()).digest()[0] % len(PALETTES)]
    image = Image.new("RGB", (288, 288), background)
    draw = ImageDraw.Draw(image)
    draw.line([(25, 58), (25, 27), (57, 27)], fill=accent, width=4)
    draw.line([(231, 261), (263, 261), (263, 230)], fill=accent, width=4)
    # Three blades echo the Chives mark at the foot of the card.
    for x, height in [(118, 12), (137, 20), (156, 16)]:
        draw.polygon([(x, 235), (x - 4, 235 - height), (x + 6, 235 - height - 4), (x + 8, 235)], fill=accent)
    for index, letter in enumerate(letters):
        for row, mask in enumerate(GLYPHS[letter]):
            for col in range(5):
                if mask & (16 >> col):
                    x = 56 + index * 96 + col * 16
                    y = 86 + row * 16
                    draw.rectangle((x, y, x + 15, y + 15), fill=ink)
    image.save(path, "JPEG", quality=94, subsampling=0)


def main():
    catalog = CARDS / "catalog.json"
    data = json.loads(catalog.read_text())
    marks = [person for person in data["people"] if person.get("portraitSource") == SOURCE]
    if not marks:
        return
    for person in marks:
        path = CARDS / person["portrait"]
        render(person, path)
        person.update(portraitSha256=sha256(path.read_bytes()).hexdigest(),
                      portraitSource=SOURCE, portraitCredit="Chives",
                      portraitLicense="PolyForm Noncommercial 1.0.0", portraitLicenseUrl=LICENCE,
                      portraitModification="根据姓名首字母和 Chives 像素字形绘制。",
                      webReleaseEligible=True, releaseNote="本地与公开版本均使用 Chives 人物标识。")
    catalog.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

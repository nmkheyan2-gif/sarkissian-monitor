import difflib
import re

import requests
from bs4 import BeautifulSoup

URLS = [
    "https://www.sarkissian.ru/catalog/koltsa/serebro/nefrit/",
    "https://www.sarkissian.ru/catalog/sergi/turmalin/",
]

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
}


def extract_visible_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


NUM_FETCHES = 5

for URL in URLS:
    print(f"\n{'='*70}")
    print(f"URL: {URL}")
    texts = []
    for i in range(NUM_FETCHES):
        r = requests.get(URL, headers=headers, timeout=20)
        texts.append(extract_visible_text(r.text))
        print(f"  Fetch {i+1}/{NUM_FETCHES} ավարտված ({len(texts[-1])} նիշ)")

    all_same = True
    for i in range(1, NUM_FETCHES):
        if texts[0] != texts[i]:
            all_same = False
            diff = list(difflib.unified_diff(
                texts[0].splitlines(), texts[i].splitlines(),
                lineterm="", n=0,
                fromfile="Fetch 1", tofile=f"Fetch {i+1}"
            ))
            print(f"\n❗ Fetch 1 vs Fetch {i+1}: {len(diff)} տարբերվող տող")
            for line in diff:
                print(line[:200])

    if all_same:
        print("✅ Բոլոր 5 fetch-երը 100% նույնական են։")

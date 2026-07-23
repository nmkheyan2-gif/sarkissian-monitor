import requests

URL = "https://www.sarkissian.ru/catalog/sergi/turmalin/"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
}

MARKERS = ["Танзанит", "Итальянский замок", "Каб. Овал"]

r = requests.get(URL, headers=headers, timeout=20)
html = r.text

print(f"URL: {URL}")
print(f"Ընդհանուր երկարությունը: {len(html)} նիշ\n")

for marker in MARKERS:
    idx = html.find(marker)
    if idx == -1:
        print(f"'{marker}' չի գտնվել այս fetch-ում\n")
        continue
    start = max(0, idx - 800)
    end = min(len(html), idx + 200)
    print(f"{'='*70}")
    print(f"Մարկեր՝ '{marker}' (դիրքը՝ {idx})")
    print(f"{'='*70}")
    print(html[start:end])
    print()

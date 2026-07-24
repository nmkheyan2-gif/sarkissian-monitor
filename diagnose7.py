import requests
from bs4 import BeautifulSoup, NavigableString

URL = "https://youtube.com/"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
}

MARKERS = ["Популярные украшения", "Похожие украшения"]

r = requests.get(URL, headers=headers, timeout=20)
soup = BeautifulSoup(r.text, "html.parser")


def describe_ancestors(node, max_levels=10):
    lines = []
    current = node.parent if isinstance(node, NavigableString) else node
    level = 0
    while current is not None and level < max_levels:
        if hasattr(current, "name") and current.name:
            attrs = current.attrs if hasattr(current, "attrs") else {}
            cls = attrs.get("class")
            _id = attrs.get("id")
            desc = f"<{current.name}"
            if _id:
                desc += f" id='{_id}'"
            if cls:
                desc += f" class='{' '.join(cls) if isinstance(cls, list) else cls}'"
            desc += ">"
            lines.append(desc)
        current = current.parent
        level += 1
    return lines


for marker in MARKERS:
    print(f"{'='*70}")
    print(f"Մարկեր՝ '{marker}'")
    print(f"{'='*70}")
    found = soup.find_all(string=lambda s, m=marker: s and m in s)
    if not found:
        print("  Չի գտնվել այս fetch-ում (գուցե այլ էջում է հայտնվում)\n")
        continue
    for idx, node in enumerate(found):
        print(f"  --- Հանդիպում #{idx + 1} ---")
        ancestors = describe_ancestors(node)
        for a in ancestors:
            print("   ", a)
    print()

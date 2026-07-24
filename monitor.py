import difflib
import os
import re
import time

import requests
from bs4 import BeautifulSoup

KARTA_URL = "https://www.sarkissian.ru/karta-sayta/"
SNAPSHOT_DIR = "snapshots"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TELEGRAM_LIMIT = 3500  # մի փոքր marge Telegram-ի 4096 նիշանոց սահմանից
PAGE_TIMEOUT = 20       # նախկինում 10 վրկ էր, մեծացրինք մեծ էջերի համար
MAX_RETRIES = 3         # timeout/կապի սխալի դեպքում քանի անգամ փորձել
RETRY_BACKOFF = 3       # վրկ, ամեն retry-ի հետ աճում է (3, 6, 9...)

# Widget-ներ, որոնց ՆԵՐՍԻ բովանդակությունը randomly փոխվում է ժամանակի
# ընթացքում (cache-ի պատճառով) և մեզ համար noise է, բայց որոնց ԱՌԿԱՅՈՒԹՅՈՒՆԸ
# ինքնին (կա՞, թե՞ ոչ էջում) կարևոր ազդանշան է, որ պետք է հետևել։
WIDGET_SELECTORS = {
    "menuTop": "nav.menuTop",              # ամբողջ mega-menu (նավ. + ապրանքային preview)
    "bx_filter_block": "div.bx-filter-block",  # Bitrix Smart Filter widget
}


def strip_php_array_dumps(text):
    """
    Հեռացնում է PHP-ի var_dump/print_r style array leak-երը (Array( ... ))
    տող-ըստ-տող parsing-ով, ճիշտ հաշվելով nested փակագծերի խորությունը։
    Ավելի հուսալի է, քան regex-ը, քանի որ ճիշտ է մշակում ցանկացած
    խորությամբ nested array-ներ (նախորդ non-greedy regex-ը թողնում էր
    բեկորներ խորը nested structure-ների դեպքում)։
    """
    lines = text.split("\n")
    result = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "Array" and i + 1 < len(lines) and lines[i + 1].strip() == "(":
            depth = 0
            i += 1
            while i < len(lines):
                stripped = lines[i].strip()
                if stripped == "(":
                    depth += 1
                elif stripped == ")":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            continue
        result.append(lines[i])
        i += 1
    return "\n".join(result)


def extract_page_data(html):
    """
    Վերադարձնում է dict՝
    - "text": էջի իրական, տեսանելի տեքստը (առանց noise widget-երի ներսի)
    - "flags": string, որը կոդավորում է հայտնի widget-երի առկայությունը
               (օրինակ՝ "menuCat=1;bx_filter_block=0")
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    flag_parts = []
    for name, selector in WIDGET_SELECTORS.items():
        present = bool(soup.select(selector))
        flag_parts.append(f"{name}={int(present)}")
        for tag in soup.select(selector):
            tag.decompose()
    flags = ";".join(flag_parts)
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    joined = "\n".join(lines)
    joined = strip_php_array_dumps(joined)
    return {"text": joined, "flags": flags}


def fetch_with_retry(url, headers):
    """
    Փորձում է fetch անել URL-ը մինչև MAX_RETRIES անգամ, timeout/կապի
    սխալի դեպքում սպասելով աճող ընդմիջումով (3, 6, 9 վրկ) նախքան
    հաջորդ փորձը։ Վերադարձնում է response-ը կամ վերբարձրացնում է
    վերջին սխալը, եթե բոլոր փորձերը ձախողվեն։
    """
    last_exception = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return requests.get(url, headers=headers, timeout=PAGE_TIMEOUT)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exception = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                print(f"  Փորձ {attempt}/{MAX_RETRIES} ձախողվեց ({e}), սպասում ենք {wait} վրկ...")
                time.sleep(wait)
    raise last_exception
def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram token/chat_id սահմանված չէ, հաղորդագրություն չի ուղարկվում։")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        if resp.status_code != 200:
            print(f"Telegram սխալ: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Telegram ուղարկելիս սխալ: {e}")


def build_text_diff_message(url, old_text, new_text):
    """Ցույց է տալիս կոնկրետ թե ինչ տողեր են ավելացվել/հեռացվել։"""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=0))
    added = [l[1:].strip() for l in diff if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:].strip() for l in diff if l.startswith("-") and not l.startswith("---")]

    message = ""
    if added:
        message += "➕ Ավելացվել է.\n" + "\n".join(f"  {l}" for l in added) + "\n\n"
    if removed:
        message += "➖ Հեռացվել է.\n" + "\n".join(f"  {l}" for l in removed) + "\n\n"

    return message.strip()


def build_flags_diff_message(old_flags, new_flags):
    """Ցույց է տալիս, թե որ widget-ն է հայտնվել/անհետացել էջից։"""
    old_map = dict(part.split("=") for part in old_flags.split(";") if part)
    new_map = dict(part.split("=") for part in new_flags.split(";") if part)

    lines = []
    for name in WIDGET_SELECTORS:
        old_val = old_map.get(name)
        new_val = new_map.get(name)
        if old_val != new_val:
            if old_val == "1" and new_val == "0":
                lines.append(f"  ⚠️ '{name}' widget-ը ՀԵՌԱՑԵԼ Է էջից")
            elif old_val == "0" and new_val == "1":
                lines.append(f"  ⚠️ '{name}' widget-ը ՀԱՅՏՆՎԵԼ Է էջում")
    return "\n".join(lines)


def run_full_audit():
    print("1. Սկսվում է կայքի քարտեզի ներբեռնումը...")
    if not os.path.exists(SNAPSHOT_DIR):
        os.makedirs(SNAPSHOT_DIR)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }

    changed_messages = []

    try:
        response = fetch_with_retry(KARTA_URL, headers)
        print(f"Քարտեզի էջի պատասխանի կոդը: {response.status_code}")
        if response.status_code != 200:
            print("Սխալ: Հնարավոր չեղավ բեռնել քարտեզի էջը:")
            return

        html_content = response.text
        found_paths = re.findall(
            r'href="(/[^"]+|https://www\.sarkissian\.ru/[^"]*)"', html_content)

        urls = set()
        for path in found_paths:
            if path.startswith("http"):
                urls.add(path)
            else:
                urls.add(f"https://www.sarkissian.ru{path}")
        urls = list(urls)
        print(f"Գտնված էջերի ընդհանուր քանակը: {len(urls)}")

        if not urls:
            print("Հղումներ չգտնվեցին:")
            return

        for url in urls:
            if any(ext in url for ext in ['.jpg', '.png', '.pdf', '.css', '.js', 'tel:', 'mailto:']):
                continue

            print(f"Ստուգվում է՝ {url}")
            try:
                page_res = fetch_with_retry(url, headers)
                if page_res.status_code == 200:
                    current = extract_page_data(page_res.text)

                    safe_filename = (
                        url.replace("https://", "")
                        .replace("http://", "")
                        .replace("/", "_")
                        .strip("_")
                    )
                    if not safe_filename:
                        safe_filename = "index"

                    snapshot_file = os.path.join(
                        SNAPSHOT_DIR, f"{safe_filename}.txt")

                    # Snapshot ֆայլի 1-ին տողը flags-երն է, մնացածը՝ բովանդակությունը
                    file_contents = f"###FLAGS:{current['flags']}\n{current['text']}"

                    if os.path.exists(snapshot_file):
                        with open(snapshot_file, "r", encoding="utf-8") as f:
                            old_raw = f.read()

                        if old_raw.startswith("###FLAGS:"):
                            old_flags, _, old_text = old_raw.partition("\n")
                            old_flags = old_flags[len("###FLAGS:"):]
                        else:
                            # Հին ֆորմատ (flags-ից առաջ) - flags-երը անհայտ են,
                            # այնպես համարում ենք, որ չեն փոխվել
                            old_flags = current["flags"]
                            old_text = old_raw

                        content_changed = old_text != current["text"]
                        flags_changed = old_flags != current["flags"]

                        if content_changed or flags_changed:
                            print(f"Փոփոխություն հայտնաբերվեց՝ {url}")
                            msg = f"🔔 Փոփոխություն՝ {url}\n\n"
                            if flags_changed:
                                msg += build_flags_diff_message(old_flags, current["flags"]) + "\n\n"
                            if content_changed:
                                msg += build_text_diff_message(url, old_text, current["text"])
                            changed_messages.append(msg.strip())
                            with open(snapshot_file, "w", encoding="utf-8") as f:
                                f.write(file_contents)
                    else:
                        with open(snapshot_file, "w", encoding="utf-8") as f:
                            f.write(file_contents)
                        print(f"Պահպանվեց (առաջին անգամ)՝ {safe_filename}.txt")

            except Exception as e:
                print(f"Սխալ {url} էջը ստուգելիս: {e}")
                continue

            time.sleep(0.3)  # փոքր ուշացում՝ սերվերը շատ արագ չծանրաբեռնելու համար

        if changed_messages:
            print(f"\nԸնդամենը {len(changed_messages)} էջ է իրապես փոփոխված համարվել։")
            batch = ""
            for msg in changed_messages:
                if len(msg) > TELEGRAM_LIMIT:
                    msg = msg[:TELEGRAM_LIMIT] + "\n... (կրճատված)"
                if len(batch) + len(msg) + 2 > TELEGRAM_LIMIT:
                    send_telegram_message(batch)
                    batch = ""
                batch += msg + "\n\n"
            if batch.strip():
                send_telegram_message(batch)
        else:
            print("Փոփոխություններ չեն հայտնաբերվել։")

        print("Աուդիտն հաջողությամբ ավարտվեց:")

    except Exception as e:
        print(f"Ընդհանուր սխալ սկրիպտում: {e}")
        send_telegram_message(f"Մոնիտորինգի սկրիպտում սխալ առաջացավ: {e}")


if __name__ == "__main__":
    run_full_audit()

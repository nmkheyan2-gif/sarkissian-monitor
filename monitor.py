import difflib
import os
import re

import requests
from bs4 import BeautifulSoup

KARTA_URL = "https://www.sarkissian.ru/karta-sayta/"
SNAPSHOT_DIR = "snapshots"  # այստեղ այժմ պահվում է տեսանելի տեքստը, ոչ թե hash

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TELEGRAM_LIMIT = 3500  # մի փոքր marge Telegram-ի 4096 նիշանոց սահմանից


def extract_visible_text(html):
    """
    Հանում է էջի իրական, տեսանելի տեքստը՝ ամբողջությամբ հեռացնելով
    <script>, <style>, <noscript> tag-երը։ Սա ինքնաբերաբար լուծում է
    Bitrix-ի դինամիկ token-ների (nocache, SERVER_TIME, bitrix_sessid)
    խնդիրը, քանի որ դրանք բոլորը գտնվում են <script> tag-երի մեջ,
    որոնք այստեղ ամբողջությամբ դեն են նետվում։
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


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


def build_diff_message(url, old_text, new_text):
    """
    Կառուցում է մարդամոտ հաղորդագրություն, որը ցույց է տալիս կոնկրետ
    թե ինչ տողեր են ավելացվել և ինչ տողեր են հեռացվել։
    """
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=0))
    added = [l[1:].strip() for l in diff if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:].strip() for l in diff if l.startswith("-") and not l.startswith("---")]

    message = f"🔔 Փոփոխություն՝ {url}\n\n"
    if added:
        message += "➕ Ավելացվել է.\n" + "\n".join(f"  {l}" for l in added) + "\n\n"
    if removed:
        message += "➖ Հեռացվել է.\n" + "\n".join(f"  {l}" for l in removed) + "\n\n"

    return message.strip()


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
        response = requests.get(KARTA_URL, headers=headers, timeout=15)
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
                page_res = requests.get(url, headers=headers, timeout=10)
                if page_res.status_code == 200:
                    current_text = extract_visible_text(page_res.text)

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

                    if os.path.exists(snapshot_file):
                        with open(snapshot_file, "r", encoding="utf-8") as f:
                            old_text = f.read()

                        if old_text != current_text:
                            print(f"Փոփոխություն հայտնաբերվեց՝ {url}")
                            diff_message = build_diff_message(url, old_text, current_text)
                            changed_messages.append(diff_message)
                            with open(snapshot_file, "w", encoding="utf-8") as f:
                                f.write(current_text)
                    else:
                        with open(snapshot_file, "w", encoding="utf-8") as f:
                            f.write(current_text)
                        print(f"Պահպանվեց (առաջին անգամ)՝ {safe_filename}.txt")

            except Exception as e:
                print(f"Սխալ {url} էջը ստուգելիս: {e}")
                continue

        if changed_messages:
            print(f"\nԸնդամենը {len(changed_messages)} էջ է իրապես փոփոխված համարվել։")
            # Ամեն փոփոխված էջի համար ուղարկում ենք առանձին հաղորդագրություն
            # (կամ խմբավորում ենք մինչև Telegram-ի սահմանաչափը)
            batch = ""
            for msg in changed_messages:
                if len(msg) > TELEGRAM_LIMIT:
                    # Այս կոնկրետ էջի diff-ը ինքնին շատ մեծ է, կրճատում ենք
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

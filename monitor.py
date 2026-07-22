import hashlib
import os
import re
import requests

KARTA_URL = "https://www.sarkissian.ru/karta-sayta/"
SNAPSHOT_DIR = "snapshots"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def clean_html_for_hashing(html):
    """
    Հեռացնում է Bitrix CMS-ի ինքնաբերաբար ներարկվող դինամիկ արժեքները
    (nocache timestamp, SERVER_TIME, bitrix_sessid), որոնք փոխվում են
    ամեն request-ի ժամանակ՝ անկախ իրական բովանդակության փոփոխությունից։
    Առանց սրա՝ hash-ը երբեք կայուն չի մնում։
    """
    html = re.sub(r'nocache=\d+', 'nocache=X', html)
    html = re.sub(r"'SERVER_TIME':'\d+'", "'SERVER_TIME':'X'", html)
    html = re.sub(r"'bitrix_sessid':'[a-f0-9]+'", "'bitrix_sessid':'X'", html)
    return html


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


def run_full_audit():
    print("1. Սկսվում է կայքի քարտեզի ներբեռնումը...")
    if not os.path.exists(SNAPSHOT_DIR):
        os.makedirs(SNAPSHOT_DIR)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }

    changed_pages = []

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
                    current_html = page_res.text
                    cleaned_html = clean_html_for_hashing(current_html)
                    current_hash = hashlib.md5(
                        cleaned_html.encode("utf-8")
                    ).hexdigest()

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
                        with open(snapshot_file, "r") as f:
                            old_hash = f.read().strip()

                        if old_hash != current_hash:
                            print(f"Փոփոխություն հայտնաբերվեց՝ {url}")
                            changed_pages.append(url)
                            with open(snapshot_file, "w") as f:
                                f.write(current_hash)
                    else:
                        with open(snapshot_file, "w") as f:
                            f.write(current_hash)
                        print(f"Պահպանվեց (առաջին անգամ)՝ {safe_filename}.txt")

            except Exception as e:
                print(f"Սխալ {url} էջը ստուգելիս: {e}")
                continue

        if changed_pages:
            header = "Կայքում փոփոխություններ են հայտնաբերվել.\n\n"
            body = "\n".join(changed_pages)
            full_message = header + body

            TELEGRAM_LIMIT = 4000  # մի փոքր marge 4096-ի սահմանից

            if len(full_message) <= TELEGRAM_LIMIT:
                send_telegram_message(full_message)
            else:
                # Երկար ցուցակը բաժանում ենք մի քանի հաղորդագրության
                chunk = header
                part_num = 1
                for url in changed_pages:
                    if len(chunk) + len(url) + 1 > TELEGRAM_LIMIT:
                        send_telegram_message(f"[{part_num}] " + chunk)
                        part_num += 1
                        chunk = ""
                    chunk += url + "\n"
                if chunk.strip():
                    send_telegram_message(f"[{part_num}] " + chunk)

                print(f"⚠️ Ընդամենը {len(changed_pages)} էջ է փոփոխված համարվել "
                      f"(հաղորդագրությունը բաժանվեց {part_num} մասի)")
        else:
            print("Փոփոխություններ չեն հայտնաբերվել։")

        print("Աուդիտն հաջողությամբ ավարտվեց:")

    except Exception as e:
        print(f"Ընդհանուր սխալ սկրիպտում: {e}")
        send_telegram_message(f"Մոնիտորինգի սկրիպտում սխալ առաջացավ: {e}")


if __name__ == "__main__":
    run_full_audit()

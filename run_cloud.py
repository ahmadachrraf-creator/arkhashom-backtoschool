"""
Arkhashom Back to School - single-bot cloud runner for GitHub Actions.
Rotates one category per run, posts up to MAX_POSTS from it.
"""
import os
import re
import json
import time
from datetime import datetime

from scraper_backtoschool import AmazonScraper
from ai_caption import CaptionGenerator
from telegram_poster import TelegramPoster
from posted_history import PostedHistory

DATA_DIR = "data"

# --- Config from environment ---
BOT_TOKEN         = os.environ["BOT_TOKEN"]
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "@arkhashomoffers")
AFFILIATE_TAG     = os.environ.get("AFFILIATE_TAG", "arkhashom-21")
BANNER_PATH       = os.environ.get("BANNER_PATH", "arkhashom_banner_backtoschool.png")
MAX_POSTS         = int(os.environ.get("MAX_POSTS_PER_RUN", "5"))
MIN_DISCOUNT      = int(os.environ.get("MIN_DISCOUNT", "15"))

CATEGORIES = [
    "deals", "bts_hub", "backpacks", "trolley_bags", "pencil_cases",
    "pens", "pencils", "notebooks", "office_supplies", "files_folders",
    "markers_highlighters", "colouring", "rulers_geometry",
    "erasers_sharpeners", "glue_scissors", "staplers_punch",
    "sticky_notes", "printing_paper", "calculators", "whiteboards",
    "art_supplies", "lunch_boxes", "water_bottles", "school_uniform",
    "school_shoes", "study_desks", "desk_chairs", "desk_lamps",
    "dorm_essentials", "books", "laptops", "tablets", "headphones",
    "printers", "storage_drives", "accessories", "laptop_bags",
    "kids_clothing", "kids_shoes", "biscuits", "juice",
    "chips_snacks", "breakfast",
]


def get_next_category():
    """Read the rotation index, return the next category, and save updated index."""
    index_file = os.path.join(DATA_DIR, "category_index.json")
    idx = 0
    if os.path.exists(index_file):
        try:
            with open(index_file, "r") as f:
                data = json.load(f)
                idx = data.get("next_index", 0)
        except (json.JSONDecodeError, IOError):
            idx = 0

    if idx >= len(CATEGORIES):
        idx = 0

    category = CATEGORIES[idx]

    with open(index_file, "w") as f:
        json.dump({"next_index": idx + 1, "last_run": datetime.now().isoformat(),
                   "last_category": category}, f, indent=2)

    return category, idx


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    category, idx = get_next_category()

    sep = "=" * 60
    print(sep)
    print("  ARKHASHOM BACK TO SCHOOL BOT")
    ts = datetime.now().isoformat(timespec="seconds")
    print(f"  {ts}")
    print(f"  Channel: {TELEGRAM_CHAT_ID}  |  Tag: {AFFILIATE_TAG}")
    print(f"  Category: {category} ({idx+1}/{len(CATEGORIES)})")
    print(f"  Max posts: {MAX_POSTS}  |  Min discount: {MIN_DISCOUNT}%")
    print(sep)
    print()

    history_file = os.path.join(DATA_DIR, "posted_history.json")
    screenshot   = os.path.join(DATA_DIR, "screenshot.png")
    buttons_file = os.path.join(DATA_DIR, "buttons_store.json")

    scraper = AmazonScraper(
        headless=True,
        affiliate_tag=AFFILIATE_TAG,
        banner_path=BANNER_PATH,
        banner_text="Arkhashom Back to School",
        force_arabic=True,
    )
    captioner = CaptionGenerator(GEMINI_API_KEY)
    poster = TelegramPoster(BOT_TOKEN, TELEGRAM_CHAT_ID)
    poster.buttons_store.file_path = buttons_file
    poster.buttons_store.config = poster.buttons_store._load()
    history = PostedHistory(history_file)

    ok, conn_info = poster.test_connection()
    if not ok:
        print(f"Telegram failed: {conn_info}")
        scraper.close()
        return
    bot_name = conn_info.get("username", "?")
    print(f"@{bot_name} connected -> {TELEGRAM_CHAT_ID}")

    print(f"Discovering from category: {category}...")
    urls = scraper.discover_product_urls([category], max_per_category=30)
    fresh = history.filter_unposted(urls)
    print(f"   {len(fresh)} fresh candidates")

    posted = 0
    opens = 0
    max_opens = 25

    for url in fresh:
        if posted >= MAX_POSTS or opens >= max_opens:
            break

        opens += 1
        pinfo = scraper.get_product_info(url)
        if not pinfo.get("title") or not pinfo.get("current_price"):
            continue

        d = str(pinfo.get("discount_pct") or "")
        m = re.search(r"\d+", d)
        pct = int(m.group(0)) if m else 0
        if pct == 0:
            cur = re.sub(r"[^\d]", "", str(pinfo.get("current_price") or ""))
            lst = re.sub(r"[^\d]", "", str(pinfo.get("list_price") or ""))
            if cur and lst and int(lst) > int(cur) > 0:
                pct = round((1 - int(cur) / int(lst)) * 100)

        if pct < MIN_DISCOUNT:
            continue

        title_short = pinfo["title"][:55]
        print(f"   OK: {title_short} [{pct}% off]")

        if not scraper.capture_product_screenshot(url, screenshot):
            img_url = pinfo.get("image_url")
            if not img_url or not scraper.download_image(img_url, screenshot):
                continue

        if not os.path.exists(screenshot) or os.path.getsize(screenshot) == 0:
            continue

        if history.has_posted(url):
            print("   Already posted - skip")
            continue

        caption = captioner.generate(pinfo)
        affiliate_url = pinfo.get("affiliate_url") or pinfo.get("url")
        ok_post, res = poster.post_product(screenshot, caption, affiliate_url)
        if ok_post:
            print(f"   Posted (id {res})")
            history.mark_posted(url, pinfo["title"])
            posted += 1
            time.sleep(3)

    if posted == 0 and fresh:
        print(f"No deals >= {MIN_DISCOUNT}% - trying best available...")
        for url in fresh[:5]:
            if history.has_posted(url):
                continue
            pinfo = scraper.get_product_info(url)
            if pinfo.get("title") and pinfo.get("current_price"):
                if scraper.capture_product_screenshot(url, screenshot):
                    caption = captioner.generate(pinfo)
                    ok_post, res = poster.post_product(screenshot, caption,
                                                       pinfo.get("affiliate_url") or url)
                    if ok_post:
                        history.mark_posted(url, pinfo.get("title", ""))
                        posted += 1
                        break

    scraper.close()
    print()
    print(sep)
    print(f"  DONE - Category: {category} | Posted {posted}/{MAX_POSTS}")
    next_cat = CATEGORIES[(idx+1) % len(CATEGORIES)]
    print(f"  Next run will scan: {next_cat}")
    print(sep)


if __name__ == "__main__":
    main()

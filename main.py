# ============================================================
# Telegram Fashion News Bot — @irfashionnews
# Version:    14.0 — Production Cloud Function
# Runtime:    Python 3.12 / Appwrite Cloud Functions
# Timeout:    120 seconds
#
# ENV VARS REQUIRED (set in Appwrite Function Settings):
#   TELEGRAM_BOT_TOKEN
#   TELEGRAM_CHANNEL_ID
#   APPWRITE_ENDPOINT
#   APPWRITE_PROJECT_ID
#   APPWRITE_API_KEY
#   APPWRITE_DATABASE_ID
#   APPWRITE_COLLECTION_ID  (default: "fashion_db")
#
# DB SCHEMA (fashion_db collection):
#   $id            auto/manual (title_hash[:36])
#   link           string  1000  required, indexed
#   title          string  500
#   published_at   datetime
#   feed_url       string  500
#   source_type    string  20
#   title_hash     string  64   indexed
#   content_hash   string  64   indexed
#   category       string  50
#   trend_score    integer
#   post_hour      integer
#   domain_hash    string  64   indexed
#   $createdAt     auto
#   $updatedAt     auto
#
# DEDUP: title_hash = SHA-256(sorted normalized title tokens)
#        content_hash = SHA-256(normalized title, unsorted)
#        Both EXCLUDE description (it changes across fetches)
#        Document ID = title_hash[:36] → 409 on conflict
#        Save BEFORE Telegram post → zero race window
#
# FLOW:
#   Phase 1: Parallel feed fetch with retry (budget: 25s)
#   Phase 2: Batch load existing hashes from DB (budget: 5s)
#   Phase 3: Filter + dedup in-memory (instant)
#   Phase 4: Save-then-post for ALL new items (budget: ~75s)
# ============================================================

import os
import re
import asyncio
import hashlib
import random
import requests
import feedparser

from datetime import datetime, timedelta, timezone
from time import monotonic, sleep
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from telegram import Bot, InputMediaPhoto, LinkPreviewOptions
from telegram.error import TelegramError


# ═══════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION
# ═══════════════════════════════════════════════════════════

# All 23 brand feeds with metadata
BRAND_FEEDS: list[dict] = [
    {"url": "https://lafemmeroje.com/feed/",
     "brand": "La Femme Roje | لا فم روژ",
     "tag": "#LaFemmeRoje #لافم_روژ",
     "category": "women",
     "source_type": "brand"},

    {"url": "https://salian.ir/feed/",
     "brand": "Salian | سالیان",
     "tag": "#Salian #سالیان",
     "category": "women",
     "source_type": "brand"},

    {"url": "https://celebon.com/feed/",
     "brand": "Celebon | سلبون",
     "tag": "#Celebon #سلبون",
     "category": "unisex",
     "source_type": "brand"},

    {"url": "https://siawood.com/feed/",
     "brand": "Siawood | سیاوود",
     "tag": "#Siawood #سیاوود",
     "category": "men",
     "source_type": "brand"},

    {"url": "https://naghmehkiumarsi.com/feed/",
     "brand": "Naghmeh Kiumarsi | نغمه کیومرثی",
     "tag": "#NaghmehKiumarsi #نغمه_کیومرثی",
     "category": "designer",
     "source_type": "brand"},

    {"url": "https://pooshmode.com/feed/",
     "brand": "Poosh | پوش",
     "tag": "#Poosh #پوش_مد",
     "category": "women",
     "source_type": "brand"},

    {"url": "https://kimiamode.com/feed/",
     "brand": "Kimia | کیمیا",
     "tag": "#Kimia #کیمیا_مد",
     "category": "women",
     "source_type": "brand"},

    {"url": "https://mihanomomosa.com/feed/",
     "brand": "Mihano Momosa | میهانو موموسا",
     "tag": "#MihanoMomosa #میهانو_موموسا",
     "category": "designer",
     "source_type": "brand"},

    {"url": "https://taghcheh.com/feed/",
     "brand": "Taghcheh | طاقچه",
     "tag": "#Taghcheh #طاقچه",
     "category": "marketplace",
     "source_type": "brand"},

    {"url": "https://parmimanto.com/feed/",
     "brand": "Parmi Manto | پارمی مانتو",
     "tag": "#ParmiManto #پارمی_مانتو",
     "category": "women",
     "source_type": "brand"},

    {"url": "https://banoosara.com/feed/",
     "brand": "Banoo Sara | بانو سارا",
     "tag": "#BanooSara #بانو_سارا",
     "category": "women",
     "source_type": "brand"},

    {"url": "https://roshanakmode.com/feed/",
     "brand": "Roshanak | رشنک",
     "tag": "#Roshanak #رشنک",
     "category": "women",
     "source_type": "brand"},

    {"url": "https://bodyspinner.com/feed/",
     "brand": "Bodyspinner | بادی اسپینر",
     "tag": "#Bodyspinner #بادی_اسپینر",
     "category": "activewear",
     "source_type": "brand"},

    {"url": "https://garoudi.com/feed/",
     "brand": "Garoudi | گارودی",
     "tag": "#Garoudi #گارودی",
     "category": "leather",
     "source_type": "brand"},

    {"url": "https://hacoupian.com/feed/",
     "brand": "Hacoupian | هاکوپیان",
     "tag": "#Hacoupian #هاکوپیان",
     "category": "men",
     "source_type": "brand"},

    {"url": "https://holidayfashion.ir/feed/",
     "brand": "Holiday | هالیدی",
     "tag": "#Holiday #هالیدی",
     "category": "unisex",
     "source_type": "brand"},

    {"url": "https://lcman.ir/feed/",
     "brand": "LC Man | ال سی من",
     "tag": "#LCMan #ال_سی_من",
     "category": "men",
     "source_type": "brand"},

    {"url": "https://narbon.ir/feed/",
     "brand": "Narbon | ناربن",
     "tag": "#Narbon #ناربن",
     "category": "women",
     "source_type": "brand"},

    {"url": "https://narian.ir/feed/",
     "brand": "Narian | ناریان",
     "tag": "#Narian #ناریان",
     "category": "women",
     "source_type": "brand"},

    {"url": "https://patanjameh.com/feed/",
     "brand": "Patan Jameh | پاتان جامه",
     "tag": "#PatanJameh #پاتان_جامه",
     "category": "traditional",
     "source_type": "brand"},

    {"url": "https://medopia.ir/feed/",
     "brand": "Medopia | مدوپیا",
     "tag": "#Medopia #مدوپیا",
     "category": "aggregator",
     "source_type": "aggregator"},

    {"url": "https://www.digistyle.com/mag/feed/",
     "brand": "Digistyle | دیجی‌استایل",
     "tag": "#Digistyle #دیجی_استایل",
     "category": "aggregator",
     "source_type": "aggregator"},

    {"url": "https://www.chibepoosham.com/feed/",
     "brand": "Chi Be Poosham | چی بپوشم",
     "tag": "#ChibePooosham #چی_بپوشم",
     "category": "aggregator",
     "source_type": "aggregator"},
]

# ── Fashion keywords ──
POSITIVE_KEYWORDS = [
    'مد', 'فشن', 'استایل', 'زیبایی', 'لباس', 'پوشاک',
    'طراحی لباس', 'ترند', 'کلکسیون', 'برند', 'سیزن',
    'آرایش', 'مانتو', 'پیراهن', 'کت', 'شلوار', 'کیف',
    'کفش', 'اکسسوری', 'جواهر', 'طلا', 'عطر', 'نگین',
    'پالتو', 'ست لباس', 'مزون', 'خیاطی', 'بافت', 'تونیک',
    'بلوز', 'دامن', 'شنل', 'کاپشن', 'جوراب', 'روسری',
    'پارچه', 'طرح', 'دوخت', 'برند ایرانی', 'محصول جدید',
    'fashion', 'style', 'beauty', 'clothing', 'trend',
    'outfit', 'couture', 'collection', 'lookbook', 'brand',
    'wardrobe', 'luxury', 'designer', 'new arrival', 'product',
    'coat', 'dress', 'blouse', 'skirt', 'jacket', 'accessory',
]

NEGATIVE_KEYWORDS = [
    'فیلم', 'سینما', 'سریال', 'بازیگر', 'کارگردان', 'اسکار',
    'صبحانه', 'رژیم غذایی', 'طرز تهیه', 'دستور پخت', 'آشپزی',
    'اپل', 'گوگل', 'آیفون', 'سامسونگ', 'تکنولوژی', 'گیم',
    'فوتبال', 'والیبال', 'ورزش', 'تیم ملی', 'لیگ',
    'بورس', 'ارز', 'دلار', 'سکه', 'بیت کوین', 'اقتصاد',
    'انتخابات', 'سیاسی', 'مجلس', 'دولت', 'وزیر',
    'زلزله', 'سیل', 'آتش سوزی', 'تصادف', 'حادثه', 'کشته',
]

FIXED_HASHTAGS = (
    "#مد #استایل #ترند #برند_ایرانی #فشن_ایرانی "
    "#fashion #IranianFashion #style"
)

# ── Limits ──
MAX_DESC_CHARS       = 350
MAX_IMAGES           = 5
CAPTION_MAX          = 1020
MAX_ITEMS_PER_FEED   = 5     # adjustable per feed
PUBLISH_BATCH_SIZE   = 25    # max total posts per run

# ── Timeouts (seconds) ──
GLOBAL_DEADLINE_SEC  = 110
FEED_FETCH_TIMEOUT   = 8
FEEDS_TOTAL_TIMEOUT  = 25
PAGE_TIMEOUT         = 6
DB_TIMEOUT           = 5

# ── Retry ──
FEED_MAX_RETRIES     = 2
FEED_RETRY_BASE      = 0.5

# ── Time window ──
HOURS_THRESHOLD      = 168   # 7 days

# ── Posting delays ──
ALBUM_CAPTION_DELAY  = 2.5
STICKER_DELAY        = 1.5
INTER_POST_DELAY     = 2.0

# ── Image filtering ──
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
IMAGE_BLOCKLIST  = [
    'doubleclick', 'googletagmanager', 'googlesyndication',
    'facebook.com/tr', 'analytics', 'pixel', 'beacon',
    'tracking', 'counter', 'stat.', 'stats.',
]

# ── Stickers ──
FASHION_STICKERS = [
    "CAACAgIAAxkBAAIBmGRx1yRFMVhVqVXLv_dAAXJMOdFNAAIUAAOVgnkAAVGGBbBjxbg4LwQ",
    "CAACAgIAAxkBAAIBmWRx1yRqy9JkN2DmV_Z2sRsKdaTjAAIVAAOVgnkAAc8R3q5p5-AELAQ",
    "CAACAgIAAxkBAAIBmmRx1yS2T2gfLqJQX9oK6LZqp1HIAAIWAAO0yXAAAV0MzCRF3ZRILAQ",
    "CAACAgIAAxkBAAIBm2Rx1ySiJV4dVeTuCTc-RfFDnfQpAAIXAAO0yXAAAA3Vm7IiJdisLAQ",
    "CAACAgIAAxkBAAIBnGRx1yT_jVlWt5xPJ7BO9aQ4JvFaAAIYAAO0yXAAAA0k9GZDQpLcLAQ",
]


# ═══════════════════════════════════════════════════════════
# SECTION 2 — MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

async def main(event=None, context=None):
    _t0 = monotonic()

    def _time_left() -> float:
        return GLOBAL_DEADLINE_SEC - (monotonic() - _t0)

    _log("══════════════════════════════════════════")
    _log("Fashion Bot v14.0 — Production")
    _log(f"Time: {datetime.now(timezone.utc).isoformat()}")
    _log(f"Feeds: {len(BRAND_FEEDS)} | Max/feed: {MAX_ITEMS_PER_FEED} | "
         f"Batch: {PUBLISH_BATCH_SIZE}")
    _log("══════════════════════════════════════════")

    # ── Load config from env vars ──
    config = _load_config()
    if not config:
        return {"status": "error", "reason": "missing_env_vars"}

    bot = Bot(token=config["token"])
    db  = _AppwriteDB(
        endpoint      = config["endpoint"],
        project       = config["project"],
        key           = config["key"],
        database_id   = config["database_id"],
        collection_id = config["collection_id"],
    )

    now            = datetime.now(timezone.utc)
    time_threshold = now - timedelta(hours=HOURS_THRESHOLD)
    loop           = asyncio.get_event_loop()

    stats = {
        "feeds_ok":       0,
        "feeds_fail":     0,
        "feeds_retry":    0,
        "entries_total":  0,
        "skip_time":      0,
        "skip_filter":    0,
        "skip_dupe":      0,
        "posted":         0,
        "errors":         0,
        "db_timeout":     False,
    }

    # ════════════════════════════════════════════════════
    # PHASE 1: Fetch all 23 feeds in parallel
    # ════════════════════════════════════════════════════
    fetch_budget = min(FEEDS_TOTAL_TIMEOUT, _time_left() - 60)
    if fetch_budget < 5:
        _log("Not enough time for feeds", level="WARN")
        return _response(stats)

    _log(f"\n[PHASE 1] Fetching {len(BRAND_FEEDS)} feeds "
         f"(budget={fetch_budget:.1f}s)")

    try:
        all_items = await asyncio.wait_for(
            _fetch_all_parallel(loop, stats),
            timeout=fetch_budget,
        )
    except asyncio.TimeoutError:
        _log("Feed fetch timed out — using partial", level="WARN")
        all_items = []

    stats["entries_total"] = len(all_items)
    _log(f"[PHASE 1] Done: {len(all_items)} entries from "
         f"{stats['feeds_ok']}/{len(BRAND_FEEDS)} feeds "
         f"({stats['feeds_fail']} failed, {stats['feeds_retry']} retries) "
         f"[{_time_left():.1f}s left]")

    if not all_items:
        _log("No entries found. Exiting.")
        return _response(stats)

    # Sort newest first
    all_items.sort(
        key=lambda x: x["pub_date"] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    # ════════════════════════════════════════════════════
    # PHASE 2: Load existing hashes from DB (ONE call)
    # ════════════════════════════════════════════════════
    known_title_hashes:   set[str] = set()
    known_content_hashes: set[str] = set()
    known_links:          set[str] = set()

    db_budget = min(DB_TIMEOUT, _time_left() - 50)
    if db_budget > 2:
        _log(f"\n[PHASE 2] Loading DB state (budget={db_budget:.1f}s)")
        try:
            raw_records = await asyncio.wait_for(
                loop.run_in_executor(None, db.load_recent, 1000),
                timeout=db_budget,
            )
            for rec in raw_records:
                th = rec.get("title_hash", "")
                ch = rec.get("content_hash", "")
                lk = rec.get("link", "")
                if th:
                    known_title_hashes.add(th)
                if ch:
                    known_content_hashes.add(ch)
                if lk:
                    known_links.add(lk)

            _log(f"[PHASE 2] Done: {len(raw_records)} records → "
                 f"{len(known_title_hashes)} title_hashes, "
                 f"{len(known_content_hashes)} content_hashes, "
                 f"{len(known_links)} links "
                 f"[{_time_left():.1f}s left]")
        except asyncio.TimeoutError:
            stats["db_timeout"] = True
            _log("DB load timed out — fallback to 409-based dedup",
                 level="WARN")
        except Exception as e:
            stats["db_timeout"] = True
            _log(f"DB load error: {e}", level="ERROR")
    else:
        _log("No budget for DB load", level="WARN")

    # In-process dedup set (prevents same-run duplicates)
    posted_hashes: set[str] = set()

    # ════════════════════════════════════════════════════
    # PHASE 3: Filter + Dedup + Post ALL new items
    # ════════════════════════════════════════════════════
    _log(f"\n[PHASE 3] Processing {len(all_items)} entries "
         f"(max {PUBLISH_BATCH_SIZE} posts)")

    for item in all_items:
        # ── Budget check ──
        if _time_left() < 15:
            _log(f"Time budget low ({_time_left():.1f}s) — stopping")
            break

        # ── Batch limit ──
        if stats["posted"] >= PUBLISH_BATCH_SIZE:
            _log(f"Batch limit ({PUBLISH_BATCH_SIZE}) reached")
            break

        title       = item["title"]
        link        = item["link"]
        desc        = item["desc"]
        pub_date    = item["pub_date"]
        brand_name  = item["brand"]
        brand_tag   = item["tag"]
        feed_url    = item["feed_url"]
        category    = item["category"]
        source_type = item["source_type"]
        entry_obj   = item["entry"]
        brand_short = brand_name.split("|")[0].strip()

        # ── Time filter ──
        if pub_date and pub_date < time_threshold:
            stats["skip_time"] += 1
            continue

        # ── Fashion relevance filter ──
        if not _is_fashion(title, desc, feed_url, brand_name):
            stats["skip_filter"] += 1
            _log(f"  [SKIP:filter] [{brand_short}] {title[:50]}")
            continue

        # ── Compute hashes ──
        title_hash   = _make_title_hash(title)
        content_hash = _make_content_hash(title)
        domain_hash  = _make_domain_hash(feed_url)

        # ── Dedup 1: in-process (same run) ──
        if title_hash in posted_hashes:
            stats["skip_dupe"] += 1
            continue

        # ── Dedup 2: title_hash from DB ──
        if title_hash in known_title_hashes:
            stats["skip_dupe"] += 1
            _log(f"  [SKIP:dupe:title_hash] [{brand_short}] {title[:45]}")
            continue

        # ── Dedup 3: content_hash from DB ──
        if content_hash in known_content_hashes:
            stats["skip_dupe"] += 1
            _log(f"  [SKIP:dupe:content_hash] [{brand_short}] {title[:45]}")
            continue

        # ── Dedup 4: link from DB ──
        if link in known_links:
            stats["skip_dupe"] += 1
            _log(f"  [SKIP:dupe:link] [{brand_short}] {title[:45]}")
            continue

        _log(f"\n  [NEW] [{brand_short}] {title[:55]}")

        # ── Trend score ──
        trend_score = _calc_trend_score(title, desc, brand_name)

        # ── Post hour ──
        post_hour = now.hour

        # ── Published at ISO ──
        pub_iso = pub_date.isoformat() if pub_date else now.isoformat()

        # ════════════════════════════════════════
        # SAVE TO DB BEFORE POSTING (atomic dedup)
        # ════════════════════════════════════════
        save_budget = min(DB_TIMEOUT, _time_left() - 10)
        if save_budget < 1:
            _log("No time for DB save — stopping", level="WARN")
            break

        try:
            saved = await asyncio.wait_for(
                loop.run_in_executor(
                    None, db.save,
                    link, title, title_hash, content_hash,
                    feed_url, pub_iso, source_type, category,
                    trend_score, post_hour, domain_hash,
                ),
                timeout=save_budget,
            )
        except asyncio.TimeoutError:
            _log(f"  DB save timed out [{brand_short}]", level="WARN")
            stats["errors"] += 1
            continue

        if not saved:
            _log(f"  DB rejected (409/error) — already exists")
            stats["skip_dupe"] += 1
            continue

        # Mark in local dedup sets
        posted_hashes.add(title_hash)
        known_title_hashes.add(title_hash)
        known_content_hashes.add(content_hash)
        known_links.add(link)

        # ════════════════════════════════════════
        # COLLECT IMAGES
        # ════════════════════════════════════════
        image_urls: list[str] = []
        img_budget = min(PAGE_TIMEOUT, _time_left() - 8)
        if img_budget > 2:
            try:
                image_urls = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, _collect_images, entry_obj, link
                    ),
                    timeout=img_budget,
                )
            except asyncio.TimeoutError:
                _log("  Image scrape timed out", level="WARN")
                image_urls = []

        # ════════════════════════════════════════
        # BUILD CAPTION
        # ════════════════════════════════════════
        caption = _build_caption(
            title=title,
            desc=desc,
            link=link,
            brand_name=brand_name,
            brand_tag=brand_tag,
            pub_date=pub_date,
        )

        # ════════════════════════════════════════
        # POST TO TELEGRAM
        # ════════════════════════════════════════
        tg_budget = min(15, _time_left() - 3)
        if tg_budget < 4:
            _log("No time for Telegram — stopping", level="WARN")
            break

        try:
            success = await asyncio.wait_for(
                _post_to_telegram(
                    bot, config["chat_id"], image_urls, caption
                ),
                timeout=tg_budget,
            )
        except asyncio.TimeoutError:
            _log("  Telegram post timed out", level="WARN")
            success = False

        if success:
            stats["posted"] += 1
            _log(f"  [POSTED #{stats['posted']}] [{brand_short}] "
                 f"{title[:50]}")

            # Inter-post delay (avoid Telegram flood)
            if (_time_left() > 8
                    and stats["posted"] < PUBLISH_BATCH_SIZE):
                await asyncio.sleep(INTER_POST_DELAY)
        else:
            stats["errors"] += 1
            _log(f"  [FAIL] [{brand_short}] {title[:50]}", level="ERROR")

    # ════════════════════════════════════════════════════
    # SUMMARY
    # ════════════════════════════════════════════════════
    elapsed = monotonic() - _t0
    _log(f"\n{'═' * 50}")
    _log(f"SUMMARY ({elapsed:.1f}s / {GLOBAL_DEADLINE_SEC}s)")
    _log(f"{'═' * 50}")
    _log(f"Feeds     : {stats['feeds_ok']} ok | "
         f"{stats['feeds_fail']} fail | "
         f"{stats['feeds_retry']} retries")
    _log(f"Entries   : {stats['entries_total']} total")
    _log(f"Skip/time : {stats['skip_time']}")
    _log(f"Skip/filter: {stats['skip_filter']}")
    _log(f"Skip/dupe : {stats['skip_dupe']}")
    _log(f"Posted    : {stats['posted']}")
    _log(f"Errors    : {stats['errors']}")
    if stats["db_timeout"]:
        _log("DB timeout occurred — dedup may be incomplete",
             level="WARN")
    _log(f"{'═' * 50}")

    return _response(stats)


def _response(stats: dict) -> dict:
    return {
        "status":        "success",
        "posted":        stats.get("posted", 0),
        "feeds_ok":      stats.get("feeds_ok", 0),
        "feeds_fail":    stats.get("feeds_fail", 0),
        "entries_total": stats.get("entries_total", 0),
        "skip_dupe":     stats.get("skip_dupe", 0),
        "skip_filter":   stats.get("skip_filter", 0),
        "errors":        stats.get("errors", 0),
    }


def _log(msg: str, level: str = "INFO"):
    print(f"[{level}] {msg}")


# ═══════════════════════════════════════════════════════════
# SECTION 3 — PARALLEL FEED FETCHER WITH RETRY
# ═══════════════════════════════════════════════════════════

async def _fetch_all_parallel(
    loop: asyncio.AbstractEventLoop, stats: dict,
) -> list[dict]:
    """Fetch all 23 feeds simultaneously."""
    tasks = [
        loop.run_in_executor(None, _fetch_one_feed, info, stats)
        for info in BRAND_FEEDS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items: list[dict] = []
    for i, result in enumerate(results):
        brand = BRAND_FEEDS[i]["brand"].split("|")[0].strip()
        if isinstance(result, Exception):
            _log(f"  {brand}: unhandled error: {result}", level="ERROR")
            stats["feeds_fail"] += 1
        elif result is None:
            stats["feeds_fail"] += 1
        elif result:
            all_items.extend(result)
            stats["feeds_ok"] += 1
        else:
            # Empty list = feed worked but 0 entries
            stats["feeds_ok"] += 1

    return all_items


def _fetch_one_feed(feed_info: dict, stats: dict) -> list[dict] | None:
    """Blocking. Retries up to FEED_MAX_RETRIES with backoff."""
    url         = feed_info["url"]
    brand_name  = feed_info["brand"]
    brand_tag   = feed_info["tag"]
    category    = feed_info.get("category", "unknown")
    source_type = feed_info.get("source_type", "brand")
    brand_short = brand_name.split("|")[0].strip()
    last_error  = None

    for attempt in range(FEED_MAX_RETRIES):
        try:
            resp = requests.get(
                url,
                timeout=FEED_FETCH_TIMEOUT,
                headers={
                    "User-Agent":
                        "Mozilla/5.0 (compatible; FashionBot/14.0)",
                    "Accept":
                        "application/rss+xml, application/xml, */*",
                },
            )

            if resp.status_code == 404:
                _log(f"  [FEED] {brand_short}: 404 Not Found",
                     level="WARN")
                return []

            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                if attempt < FEED_MAX_RETRIES - 1:
                    stats["feeds_retry"] += 1
                    _log(f"  [FEED] {brand_short}: {last_error} "
                         f"— retry {attempt + 1}", level="WARN")
                    sleep(FEED_RETRY_BASE * (2 ** attempt))
                    continue
                _log(f"  [FEED] {brand_short}: {last_error} "
                     f"after {FEED_MAX_RETRIES} attempts", level="ERROR")
                return None

            feed = feedparser.parse(resp.content)
            if feed.bozo and not feed.entries:
                _log(f"  [FEED] {brand_short}: Malformed feed",
                     level="WARN")
                return []

            items = []
            for entry in feed.entries[:MAX_ITEMS_PER_FEED]:
                title = _clean(entry.get("title", ""))
                link  = _clean(entry.get("link", ""))
                if not title or not link:
                    continue

                raw_html = (
                    entry.get("summary")
                    or entry.get("description")
                    or ""
                )
                desc     = _truncate(
                    _strip_html(raw_html), MAX_DESC_CHARS
                )
                pub_date = _parse_date(entry)

                items.append({
                    "title":       title,
                    "link":        link,
                    "desc":        desc,
                    "pub_date":    pub_date,
                    "brand":       brand_name,
                    "tag":         brand_tag,
                    "feed_url":    url,
                    "category":    category,
                    "source_type": source_type,
                    "entry":       entry,
                })

            retry_note = f" (retry {attempt})" if attempt > 0 else ""
            _log(f"  [FEED] {brand_short}: "
                 f"{len(items)} entries{retry_note}")
            return items

        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection: {str(e)[:60]}"
        except requests.exceptions.Timeout:
            last_error = "Timeout"
        except Exception as e:
            _log(f"  [FEED] {brand_short}: {str(e)[:80]}",
                 level="ERROR")
            return None

        if attempt < FEED_MAX_RETRIES - 1:
            stats["feeds_retry"] += 1
            _log(f"  [FEED] {brand_short}: {last_error} "
                 f"— retry {attempt + 1}", level="WARN")
            sleep(FEED_RETRY_BASE * (2 ** attempt))

    _log(f"  [FEED] {brand_short}: Failed after "
         f"{FEED_MAX_RETRIES} attempts: {last_error}", level="ERROR")
    return None


# ═══════════════════════════════════════════════════════════
# SECTION 4 — APPWRITE DATABASE CLIENT
# ═══════════════════════════════════════════════════════════

class _AppwriteDB:
    """
    Raw HTTP client for Appwrite REST API.

    Collection: fashion_db
    All field names match EXACTLY:
      link, title, published_at, feed_url, source_type,
      title_hash, content_hash, category, trend_score,
      post_hour, domain_hash
    """

    def __init__(self, endpoint, project, key,
                 database_id, collection_id):
        self._url = (
            f"{endpoint}/databases/{database_id}"
            f"/collections/{collection_id}/documents"
        )
        self._headers = {
            "Content-Type":       "application/json",
            "X-Appwrite-Project": project,
            "X-Appwrite-Key":     key,
        }

    def load_recent(self, limit: int = 1000) -> list[dict]:
        """
        Batch load recent documents.
        Returns list of dicts with title_hash, content_hash, link.
        Single HTTP call — no per-article queries.
        """
        all_docs = []
        offset = 0
        batch_size = min(limit, 100)  # Appwrite max per request

        while offset < limit:
            try:
                resp = requests.get(
                    self._url,
                    headers=self._headers,
                    params={
                        "limit":  str(batch_size),
                        "offset": str(offset),
                    },
                    timeout=DB_TIMEOUT,
                )
                if resp.status_code != 200:
                    _log(f"DB load: HTTP {resp.status_code}",
                         level="WARN")
                    break

                data = resp.json()
                docs = data.get("documents", [])
                if not docs:
                    break

                for d in docs:
                    all_docs.append({
                        "title_hash":   d.get("title_hash", ""),
                        "content_hash": d.get("content_hash", ""),
                        "link":         d.get("link", ""),
                    })

                if len(docs) < batch_size:
                    break  # No more pages

                offset += batch_size

            except requests.exceptions.Timeout:
                raise  # Let caller handle
            except Exception as e:
                _log(f"DB load error: {e}", level="ERROR")
                break

        return all_docs

    def save(
        self,
        link: str,
        title: str,
        title_hash: str,
        content_hash: str,
        feed_url: str,
        published_at: str,
        source_type: str,
        category: str,
        trend_score: int,
        post_hour: int,
        domain_hash: str,
    ) -> bool:
        """
        Save with title_hash[:36] as document ID.
        409 Conflict = already exists (atomic dedup).

        ALL fields match exact Appwrite column names.
        """
        doc_id = title_hash[:36]

        payload = {
            "documentId": doc_id,
            "data": {
                "link":         link[:1000],
                "title":        title[:500],
                "title_hash":   title_hash[:64],
                "content_hash": content_hash[:64],
                "feed_url":     feed_url[:500],
                "published_at": published_at,
                "source_type":  source_type[:20],
                "category":     category[:50],
                "trend_score":  trend_score,
                "post_hour":    post_hour,
                "domain_hash":  domain_hash[:64],
            },
        }

        try:
            resp = requests.post(
                self._url,
                headers=self._headers,
                json=payload,
                timeout=DB_TIMEOUT,
            )

            if resp.status_code in (200, 201):
                _log("  [DB] Saved ✓")
                return True

            if resp.status_code == 409:
                _log("  [DB] 409 — duplicate (already exists)")
                return False

            _log(f"  [DB] Save failed: HTTP {resp.status_code}: "
                 f"{resp.text[:200]}", level="WARN")
            return False

        except Exception as e:
            _log(f"  [DB] Save error: {e}", level="WARN")
            return False

    def check_exists(self, field: str, value: str) -> bool:
        """
        Check if a document with field=value exists.
        Used as fallback — prefer in-memory checks.
        """
        try:
            resp = requests.get(
                self._url,
                headers=self._headers,
                params={
                    "queries[]": f'equal("{field}", ["{value}"])',
                    "limit": "1",
                },
                timeout=DB_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json().get("total", 0) > 0
            return False
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════
# SECTION 5 — CONFIG LOADER (all from env vars)
# ═══════════════════════════════════════════════════════════

def _load_config() -> dict | None:
    """
    All credentials come from environment variables.
    Set these in Appwrite Function Settings:
      TELEGRAM_BOT_TOKEN
      TELEGRAM_CHANNEL_ID
      APPWRITE_ENDPOINT
      APPWRITE_PROJECT_ID
      APPWRITE_API_KEY
      APPWRITE_DATABASE_ID
      APPWRITE_COLLECTION_ID
    """
    cfg = {
        "token":         os.environ.get("TELEGRAM_BOT_TOKEN"),
        "chat_id":       os.environ.get("TELEGRAM_CHANNEL_ID"),
        "endpoint":      os.environ.get("APPWRITE_ENDPOINT",
                                        "https://fra.cloud.appwrite.io/v1"),
        "project":       os.environ.get("APPWRITE_PROJECT_ID"),
        "key":           os.environ.get("APPWRITE_API_KEY"),
        "database_id":   os.environ.get("APPWRITE_DATABASE_ID"),
        "collection_id": os.environ.get("APPWRITE_COLLECTION_ID",
                                        "fashion_db"),
    }

    missing = [k for k, v in cfg.items() if not v]
    if missing:
        _log(f"Missing env vars: {missing}", level="ERROR")
        _log("Set these in Appwrite Function → Settings → "
             "Environment Variables", level="ERROR")
        return None

    _log(f"Config loaded: endpoint={cfg['endpoint']} "
         f"project={cfg['project'][:8]}... "
         f"db={cfg['database_id'][:8]}... "
         f"collection={cfg['collection_id']}")
    return cfg


# ═══════════════════════════════════════════════════════════
# SECTION 6 — TEXT + HASH UTILITIES
# ═══════════════════════════════════════════════════════════

def _clean(text: str) -> str:
    return (text or "").strip()


def _strip_html(html: str) -> str:
    """Safe HTML stripping — never crashes."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "iframe"]):
            tag.decompose()
        return " ".join(soup.get_text(separator=" ").split())
    except Exception:
        # Regex fallback for malformed HTML
        try:
            return re.sub(r"<[^>]+>", " ", html).strip()
        except Exception:
            return html.strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_space = cut.rfind(" ")
    if last_space > limit * 0.8:
        cut = cut[:last_space]
    return cut + "…"


def _normalize_for_hash(title: str) -> str:
    """
    Normalize title for hashing.
    - Lowercase
    - Remove ZWNJ and zero-width chars
    - Persian character normalization
    - Remove punctuation
    - Sort tokens (order-independent)
    """
    if not title:
        return ""
    t = title.lower().strip()
    # Remove zero-width chars
    t = re.sub(r"[\u200c\u200d\u200e\u200f\ufeff]", "", t)
    # Persian normalization
    t = t.replace("ي", "ی").replace("ك", "ک")
    t = t.replace("ة", "ه").replace("ؤ", "و")
    t = t.replace("إ", "ا").replace("أ", "ا")
    t = t.replace("ئ", "ی").replace("ى", "ی")
    # Remove diacritics
    t = re.sub(r"[\u064B-\u065F\u0670]", "", t)
    # Remove punctuation, keep letters + numbers
    t = re.sub(r"[^\w\s\u0600-\u06FF]", " ", t)
    # Sort tokens for order-independence
    tokens = sorted(t.split())
    return " ".join(tokens)


def _make_title_hash(title: str) -> str:
    """
    PRIMARY dedup key.
    SHA-256 of sorted normalized title tokens.
    Description EXCLUDED — it varies across fetches.
    """
    canonical = _normalize_for_hash(title)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _make_content_hash(title: str) -> str:
    """
    SECONDARY hash for analytics.
    SHA-256 of normalized title (unsorted, preserving order).
    Also excludes description.
    """
    t = title.lower().strip()
    t = re.sub(r"[\u200c\u200d\u200e\u200f\ufeff]", "", t)
    t = t.replace("ي", "ی").replace("ك", "ک")
    t = t.replace("ة", "ه")
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def _make_domain_hash(feed_url: str) -> str:
    """SHA-256 of feed domain for grouping."""
    try:
        domain = urlparse(feed_url).netloc.lower()
    except Exception:
        domain = feed_url
    return hashlib.sha256(domain.encode("utf-8")).hexdigest()


def _parse_date(entry) -> datetime | None:
    for field in ("published_parsed", "updated_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return None


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


# ═══════════════════════════════════════════════════════════
# SECTION 7 — FASHION FILTER + TREND SCORE
# ═══════════════════════════════════════════════════════════

def _is_fashion(
    title: str, desc: str, feed_url: str, brand_name: str,
) -> bool:
    """
    Returns True if content is fashion-relevant.
    Brand feeds get leniency: brand name in content = pass.
    """
    combined = (title + " " + desc).lower()

    # Hard reject
    for kw in NEGATIVE_KEYWORDS:
        if kw in combined:
            return False

    # Positive keyword match
    for kw in POSITIVE_KEYWORDS:
        if kw in combined:
            return True

    # Brand name leniency (for brand-specific feeds)
    brand_parts = [
        p.strip().lower()
        for p in brand_name.replace("|", " ").split()
        if len(p.strip()) >= 4
    ]
    for part in brand_parts:
        if part in combined:
            return True

    # Domain signal
    try:
        domain = urlparse(feed_url).netloc.replace(
            "www.", ""
        ).lower()
        if domain and domain.split(".")[0] in combined:
            return True
    except Exception:
        pass

    return False


def _calc_trend_score(
    title: str, desc: str, brand_name: str,
) -> int:
    """Simple keyword-density score. Stored for analytics."""
    combined = (title + " " + desc).lower()
    score = 0

    for kw in POSITIVE_KEYWORDS:
        if kw in combined:
            score += 1

    brand_parts = [
        p.strip().lower()
        for p in brand_name.replace("|", " ").split()
        if len(p.strip()) >= 4
    ]
    for part in brand_parts:
        if part in combined:
            score += 2

    high_value = [
        'کلکسیون', 'collection', 'new arrival',
        'محصول جدید', 'ترند', 'trend', 'lookbook',
    ]
    title_lower = title.lower()
    for kw in high_value:
        if kw in title_lower:
            score += 3

    return min(score, 100)


# ═══════════════════════════════════════════════════════════
# SECTION 8 — IMAGE COLLECTION
# ═══════════════════════════════════════════════════════════

def _collect_images(entry, article_url: str) -> list[str]:
    """Blocking — called via run_in_executor."""
    images: list[str] = []
    seen:   set[str]  = set()

    def _add(url: str) -> None:
        url = (url or "").strip()
        if not url or not url.startswith("http") or url in seen:
            return
        lower = url.lower()
        if any(b in lower for b in IMAGE_BLOCKLIST):
            return
        base = lower.split("?")[0]
        has_ext = any(base.endswith(e) for e in IMAGE_EXTENSIONS)
        has_kw = any(
            w in lower for w in
            ["image", "photo", "img", "picture", "media",
             "cdn", "upload", "product", "wp-content"]
        )
        if not has_ext and not has_kw:
            return
        seen.add(url)
        images.append(url)

    # 1. Enclosures
    enclosures = entry.get("enclosures", [])
    if (not enclosures and hasattr(entry, "enclosure")
            and entry.enclosure):
        enclosures = [entry.enclosure]
    for enc in enclosures:
        if isinstance(enc, dict):
            mime = enc.get("type", "")
            href = enc.get("href") or enc.get("url", "")
        else:
            mime = getattr(enc, "type", "")
            href = (getattr(enc, "href", "")
                    or getattr(enc, "url", ""))
        if mime.startswith("image/") and href:
            _add(href)

    # 2. media:content
    for m in entry.get("media_content", []):
        u = (m.get("url", "") if isinstance(m, dict)
             else getattr(m, "url", ""))
        med = (m.get("medium", "") if isinstance(m, dict)
               else getattr(m, "medium", ""))
        if (med == "image"
                or any(u.lower().endswith(e)
                       for e in IMAGE_EXTENSIONS)):
            _add(u)

    # 3. media:thumbnail
    for t in entry.get("media_thumbnail", []):
        u = (t.get("url", "") if isinstance(t, dict)
             else getattr(t, "url", ""))
        _add(u)

    # 4. <img> in description
    if len(images) < MAX_IMAGES:
        raw = (
            entry.get("summary")
            or entry.get("description")
            or (entry.get("content") or [{}])[0].get("value", "")
        )
        if raw:
            try:
                soup = BeautifulSoup(raw, "lxml")
                for img in soup.find_all("img"):
                    for attr in ("src", "data-src",
                                 "data-lazy-src", "data-original"):
                        s = img.get(attr, "")
                        if s and s.startswith("http"):
                            _add(s)
                            break
                    if len(images) >= MAX_IMAGES:
                        break
            except Exception:
                pass

    # 5. og:image fallback
    if not images:
        og = _fetch_og_image(article_url)
        if og:
            _add(og)

    result = images[:MAX_IMAGES]
    _log(f"  [IMG] {len(result)} images collected")
    return result


def _fetch_og_image(url: str) -> str | None:
    """Fetch article page for og:image. Blocking."""
    try:
        resp = requests.get(
            url, timeout=PAGE_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        for prop in ("og:image", "twitter:image"):
            tag = (
                soup.find("meta", property=prop)
                or soup.find("meta", attrs={"name": prop})
            )
            if tag:
                c = tag.get("content", "").strip()
                if c.startswith("http"):
                    return c
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
# SECTION 9 — CAPTION BUILDER
# ═══════════════════════════════════════════════════════════

def _build_caption(
    title: str,
    desc: str,
    link: str,
    brand_name: str,
    brand_tag: str,
    pub_date: datetime | None = None,
) -> str:
    """
    Magazine-style caption:
      🏷️ Brand Name
      💠 <b>Title</b>
      ─────────────
      Description
      📅 Publication date
      🔗 Link | 🆔 @irfashionnews
      #hashtags
    """
    safe_brand = _escape_html(brand_name.strip())
    safe_title = _escape_html(title.strip())
    safe_desc  = _escape_html(desc.strip())
    hashtag_line = f"{brand_tag} {FIXED_HASHTAGS}"

    # Format publication date
    date_line = ""
    if pub_date:
        try:
            date_str = pub_date.strftime("%Y-%m-%d %H:%M UTC")
            date_line = f"📅 {date_str}"
        except Exception:
            pass

    parts = [
        f"🏷️ {safe_brand}",
        f"💠 <b>{safe_title}</b>",
        "─────────────",
    ]

    if safe_desc:
        parts.append(safe_desc)

    if date_line:
        parts.append(date_line)

    parts.append(
        f'🔗 <a href="{link}">ادامه مطلب</a> | 🆔 @irfashionnews'
    )
    parts.append(hashtag_line)

    caption = "\n\n".join(parts)

    # Trim description if over limit
    if len(caption) > CAPTION_MAX:
        overflow = len(caption) - CAPTION_MAX
        if safe_desc:
            safe_desc = safe_desc[
                :max(0, len(safe_desc) - overflow - 5)
            ] + "…"
            # Rebuild
            parts_trimmed = [
                f"🏷️ {safe_brand}",
                f"💠 <b>{safe_title}</b>",
                "─────────────",
            ]
            if safe_desc:
                parts_trimmed.append(safe_desc)
            if date_line:
                parts_trimmed.append(date_line)
            parts_trimmed.append(
                f'🔗 <a href="{link}">ادامه مطلب</a> | '
                f'🆔 @irfashionnews'
            )
            parts_trimmed.append(hashtag_line)
            caption = "\n\n".join(parts_trimmed)

    return caption


# ═══════════════════════════════════════════════════════════
# SECTION 10 — TELEGRAM POSTING
# ═══════════════════════════════════════════════════════════

async def _post_to_telegram(
    bot: Bot,
    chat_id: str,
    image_urls: list[str],
    caption: str,
) -> bool:
    """
    Post flow:
      ① Images (no caption) → anchor_id
      ② Sleep(2.5s)
      ③ Caption message (reply to anchor)
      ④ Sleep(1.5s)
      ⑤ Sticker (non-fatal)
    """
    anchor_msg_id: int | None = None

    # ── ① Images ──
    if len(image_urls) >= 2:
        try:
            media = [
                InputMediaPhoto(media=url)
                for url in image_urls[:MAX_IMAGES]
            ]
            sent = await bot.send_media_group(
                chat_id=chat_id,
                media=media,
                disable_notification=True,
            )
            anchor_msg_id = sent[-1].message_id
            _log(f"  [TG] ① Album: {len(sent)} images "
                 f"anchor={anchor_msg_id}")
        except TelegramError as e:
            _log(f"  [TG] ① Album failed: {e} — trying single",
                 level="WARN")
            if image_urls:
                try:
                    s = await bot.send_photo(
                        chat_id=chat_id,
                        photo=image_urls[0],
                        disable_notification=True,
                    )
                    anchor_msg_id = s.message_id
                    _log(f"  [TG] ① Fallback photo "
                         f"anchor={anchor_msg_id}")
                except TelegramError as e2:
                    _log(f"  [TG] ① Fallback photo failed: {e2}",
                         level="WARN")

    elif len(image_urls) == 1:
        try:
            s = await bot.send_photo(
                chat_id=chat_id,
                photo=image_urls[0],
                disable_notification=True,
            )
            anchor_msg_id = s.message_id
            _log(f"  [TG] ① Photo anchor={anchor_msg_id}")
        except TelegramError as e:
            _log(f"  [TG] ① Photo failed: {e}", level="WARN")

    else:
        _log("  [TG] ① No images — standalone caption")

    # ── ② Delay ──
    if anchor_msg_id is not None:
        await asyncio.sleep(ALBUM_CAPTION_DELAY)

    # ── ③ Caption ──
    try:
        kwargs = {
            "chat_id":              chat_id,
            "text":                 caption,
            "parse_mode":           "HTML",
            "link_preview_options": LinkPreviewOptions(
                is_disabled=True
            ),
            "disable_notification": True,
        }
        if anchor_msg_id is not None:
            kwargs["reply_to_message_id"] = anchor_msg_id

        await bot.send_message(**kwargs)

        label = (f"reply_to={anchor_msg_id}"
                 if anchor_msg_id else "standalone")
        _log(f"  [TG] ③ Caption sent ({label})")

    except TelegramError as e:
        _log(f"  [TG] ③ Caption FAILED: {e}", level="ERROR")
        return False

    # ── ④⑤ Sticker (non-fatal) ──
    if FASHION_STICKERS:
        await asyncio.sleep(STICKER_DELAY)
        try:
            await bot.send_sticker(
                chat_id=chat_id,
                sticker=random.choice(FASHION_STICKERS),
                disable_notification=True,
            )
            _log("  [TG] ⑤ Sticker sent")
        except TelegramError as e:
            _log(f"  [TG] ⑤ Sticker failed (non-fatal): {e}",
                 level="WARN")

    return True


# ═══════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(main())

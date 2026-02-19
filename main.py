# ============================================================
# Telegram Fashion News Bot — @irfashionnews
# Version:    10.1 — Persian Fashion Feed
# Runtime:    Python 3.12 / Appwrite Cloud Functions
# Timeout:    120 seconds
#
# POST FLOW (guaranteed order):
#   ① Fetch RSS feeds → collect candidates
#   ② Filter by fashion relevance
#   ③ Check Appwrite DB for duplicates (link + hash)
#   ④ Extract 1–5 images
#   ⑤ send_media_group(all images, NO caption)
#      → anchor_id = last_sent_message.message_id
#   ⑥ asyncio.sleep(2.5s)
#   ⑦ send_message(caption, reply_to=anchor_id)
#      → reply dependency = protocol-level order guarantee
#   ⑧ asyncio.sleep(1.5s)
#   ⑨ send_sticker(random) [non-fatal]
#   ⑩ Save record to Appwrite DB
#
# DUPLICATE PROTECTION:
#   - Exact URL match
#   - SHA256(title + description[:150]) content hash
#   - Both checked BEFORE any Telegram call
#
# CAPTION FORMAT (HTML, magazine style):
#   💠 Bold Title
#   ─────────────
#   Short description (≤ 350 chars)
#
#   🔗 ادامه مطلب | 🆔 @irfashionnews
#
#   #مد #استایل #ترند #فشن_ایرانی #زیبایی #fashion #style
# ============================================================

import os
import asyncio
import hashlib
import random
import re
import requests
import feedparser

from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup
from telegram import Bot, InputMediaPhoto, LinkPreviewOptions
from telegram.error import TelegramError


# ═══════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION
# ═══════════════════════════════════════════════════════════

RSS_FEEDS = [
    "https://medopia.ir/feed/",
    "https://www.digistyle.com/mag/feed/",
    "https://www.chibepoosham.com/feed/",
    "https://www.tarahanelebas.com/feed/",
    "https://www.persianpood.com/feed/",
    "https://www.zibamoon.com/feed/",
    "https://www.elsana.com/feed/",
    "https://www.beytoote.com/rss/fashion",
    "https://www.namnak.com/rss/fashion",
    "https://www.roozaneh.net/rss/fashion",
    "https://www.bartarinha.ir/rss/fashion",
    "https://www.zoomit.ir/feed/category/fashion-beauty/",
    "https://fararu.com/rss/category/مد-زیبایی",
    "https://www.digikala.com/mag/feed/?category=مد-و-زیبایی",
]

# ── Must match at least ONE to pass ──
POSITIVE_KEYWORDS = [
    # Persian
    'مد', 'فشن', 'استایل', 'زیبایی', 'لباس', 'پوشاک',
    'طراحی لباس', 'ترند', 'کلکسیون', 'برند', 'سیزن',
    'آرایش', 'مانتو', 'پیراهن', 'کت', 'شلوار', 'کیف',
    'کفش', 'اکسسوری', 'جواهر', 'طلا', 'عطر', 'نگین',
    'پالتو', 'ست لباس', 'مزون', 'خیاطی', 'بافت',
    # English
    'fashion', 'style', 'beauty', 'clothing', 'trend',
    'outfit', 'couture', 'runway', 'lookbook', 'textile',
    'wardrobe', 'luxury', 'brand', 'collection', 'designer',
    'chanel', 'dior', 'gucci', 'prada', 'zara', 'h&m',
    'streetwear', 'accessory', 'jewelry', 'fragrance',
]

# ── ANY match = hard reject ──
NEGATIVE_KEYWORDS = [
    'فیلم', 'سینما', 'سریال', 'بازیگر', 'کارگردان', 'اسکار',
    'صبحانه', 'رژیم غذایی', 'طرز تهیه', 'دستور پخت', 'آشپزی',
    'اپل', 'گوگل', 'آیفون', 'سامسونگ', 'تکنولوژی', 'گیم',
    'فوتبال', 'والیبال', 'ورزش', 'تیم ملی', 'لیگ', 'مسابقه',
    'بورس', 'ارز', 'دلار', 'سکه', 'بیت کوین', 'اقتصاد',
    'انتخابات', 'سیاسی', 'مجلس', 'دولت', 'وزیر', 'رئیس جمهور',
    'زلزله', 'سیل', 'آتش سوزی', 'تصادف', 'حادثه', 'کشته',
]

# ── Fixed hashtag block — always last line of caption ──
FIXED_HASHTAGS = (
    "#مد #استایل #ترند #فشن_ایرانی #زیبایی "
    "#fashion #style #luxury"
)

# ── Limits ──
MAX_DESCRIPTION_CHARS = 350
MAX_IMAGES            = 5
CAPTION_MAX           = 1020    # Telegram caption/message hard limit

# ── Timeouts (seconds) ──
FEED_TIMEOUT          = 10
PAGE_TIMEOUT          = 8
DB_TIMEOUT            = 6
HOURS_THRESHOLD       = 48

# ── Posting delays (seconds) ──
ALBUM_CAPTION_DELAY   = 2.5     # between album and caption
STICKER_DELAY         = 1.5     # between caption and sticker

# ── Valid image file extensions ──
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

# ── Image URL blocklist (ads, trackers) ──
IMAGE_BLOCKLIST = [
    'doubleclick', 'googletagmanager', 'googlesyndication',
    'facebook.com/tr', 'analytics', 'pixel', 'beacon',
    'tracking', 'counter', 'stat.', 'stats.',
]

# ── Fashion stickers ──
# Replace with real file_ids obtained from @RawDataBot or getUpdates API.
# Send any sticker to your bot, then call:
#   GET https://api.telegram.org/bot<TOKEN>/getUpdates
# Copy: result[0].message.sticker.file_id
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
    print("[INFO] ══════════════════════════════════════")
    print("[INFO] Fashion News Bot v10.1 started")
    print(f"[INFO] {datetime.now(timezone.utc).isoformat()}")
    print("[INFO] ══════════════════════════════════════")

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

    stats = {
        "checked":   0,
        "skip_time": 0,
        "skip_filt": 0,
        "skip_dupe": 0,
        "posted":    False,
    }

    for feed_url in RSS_FEEDS:
        if stats["posted"]:
            break

        print(f"\n[FEED] {feed_url}")
        entries = _fetch_feed(feed_url)
        if not entries:
            continue

        for entry in entries:
            if stats["posted"]:
                break

            stats["checked"] += 1

            # ── Parse basic fields ──
            title = _clean(entry.get("title", ""))
            link  = _clean(entry.get("link",  ""))
            if not title or not link:
                continue

            # ── Time filter ──
            pub_date = _parse_date(entry)
            if pub_date and pub_date < time_threshold:
                stats["skip_time"] += 1
                continue

            # ── Clean description ──
            raw_html = (
                entry.get("summary")
                or entry.get("description")
                or ""
            )
            desc = _truncate(
                _strip_html(raw_html),
                MAX_DESCRIPTION_CHARS,
            )

            # ── Fashion relevance filter ──
            if not _is_fashion(title, desc):
                stats["skip_filt"] += 1
                print(f"[SKIP:filter] {title[:65]}")
                continue

            # ── Duplicate check (STRICT — before any Telegram call) ──
            content_hash = _make_hash(title, desc)
            if db.is_duplicate(link, content_hash):
                stats["skip_dupe"] += 1
                print(f"[SKIP:dupe]   {title[:65]}")
                continue

            print(f"[INFO] Candidate: {title[:65]}")

            # ── Collect images ──
            image_urls = _collect_images(entry, link)

            # ── Build caption ──
            caption = _build_caption(title, desc, link)

            # ── Post to Telegram ──
            success = await _post_to_telegram(
                bot        = bot,
                chat_id    = config["chat_id"],
                image_urls = image_urls,
                caption    = caption,
            )

            if success:
                stats["posted"] = True
                print(f"[SUCCESS] Posted: {title[:65]}")

                # Save AFTER confirmed post
                db.save(
                    link         = link,
                    title        = title,
                    content_hash = content_hash,
                    created_at   = now.isoformat(),
                )

    # ── Summary ──
    print("\n[INFO] ─────────── SUMMARY ───────────")
    print(f"[INFO] Checked   : {stats['checked']}")
    print(f"[INFO] Skip/time : {stats['skip_time']}")
    print(f"[INFO] Skip/filt : {stats['skip_filt']}")
    print(f"[INFO] Skip/dupe : {stats['skip_dupe']}")
    print(f"[INFO] Posted    : {stats['posted']}")
    print("[INFO] ──────────────────────────────")

    return {"status": "success", "posted": stats["posted"]}


# ═══════════════════════════════════════════════════════════
# SECTION 3 — CONFIG LOADER
# ═══════════════════════════════════════════════════════════

def _load_config() -> dict | None:
    cfg = {
        "token":         os.environ.get("TELEGRAM_BOT_TOKEN"),
        "chat_id":       os.environ.get("TELEGRAM_CHANNEL_ID"),
        "endpoint":      os.environ.get("APPWRITE_ENDPOINT",
                                        "https://cloud.appwrite.io/v1"),
        "project":       os.environ.get("APPWRITE_PROJECT_ID"),
        "key":           os.environ.get("APPWRITE_API_KEY"),
        "database_id":   os.environ.get("APPWRITE_DATABASE_ID"),
        "collection_id": os.environ.get("APPWRITE_COLLECTION_ID", "history"),
    }
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        print(f"[ERROR] Missing env vars: {missing}")
        return None
    return cfg


# ═══════════════════════════════════════════════════════════
# SECTION 4 — APPWRITE DATABASE CLIENT
#
# Uses raw requests — no Appwrite SDK required.
# Same database and collection as the original project.
# Checks: link (exact URL) + content_hash (SHA256).
# Both must be absent for the article to be posted.
# ═══════════════════════════════════════════════════════════

class _AppwriteDB:

    def __init__(self, endpoint, project, key, database_id, collection_id):
        self._url = (
            f"{endpoint}/databases/{database_id}"
            f"/collections/{collection_id}/documents"
        )
        self._headers = {
            "Content-Type":       "application/json",
            "X-Appwrite-Project": project,
            "X-Appwrite-Key":     key,
        }

    # ── Public interface ──

    def is_duplicate(self, link: str, content_hash: str) -> bool:
        """
        Strict duplicate check.
        Returns True if EITHER link OR content_hash already exists.
        On DB error, returns False (do not block posting on network issues).
        """
        return (
            self._field_exists("link",         link[:500])
            or self._field_exists("content_hash", content_hash)
        )

    def save(self, link: str, title: str,
             content_hash: str, created_at: str) -> bool:
        """Save a new post record after successful Telegram delivery."""
        doc_id = hashlib.md5(link.encode()).hexdigest()[:20]
        try:
            resp = requests.post(
                self._url,
                headers=self._headers,
                json={
                    "documentId": doc_id,
                    "data": {
                        "link":         link[:500],
                        "title":        title[:300],
                        "content_hash": content_hash,
                        "created_at":   created_at,
                    },
                },
                timeout=DB_TIMEOUT,
            )
            ok = resp.status_code in (200, 201)
            if ok:
                print("[DB] Record saved.")
            else:
                print(f"[WARN] DB save {resp.status_code}: {resp.text[:120]}")
            return ok
        except requests.RequestException as e:
            print(f"[WARN] DB save error: {e}")
            return False

    # ── Internal ──

    def _field_exists(self, field: str, value: str) -> bool:
        """
        Query Appwrite REST for any document where field = value.
        Returns True if found, False if not found or on error.
        """
        try:
            resp = requests.get(
                self._url,
                headers=self._headers,
                params={
                    "queries[]": f'equal("{field}", ["{value}"])',
                    "limit":     1,
                },
                timeout=DB_TIMEOUT,
            )
            if resp.status_code == 200:
                found = resp.json().get("total", 0) > 0
                if found:
                    print(f"[DB] Duplicate found by {field}.")
                return found
            print(f"[WARN] DB query {resp.status_code} ({field}): {resp.text[:80]}")
            return False
        except requests.RequestException as e:
            print(f"[WARN] DB query error ({field}): {e}")
            return False


# ═══════════════════════════════════════════════════════════
# SECTION 5 — RSS FEED FETCHER
# ═══════════════════════════════════════════════════════════

def _fetch_feed(url: str) -> list:
    """
    Fetch RSS via requests with timeout, then parse with feedparser.
    Returns list of entries, or [] on any failure.
    """
    try:
        resp = requests.get(
            url,
            timeout=FEED_TIMEOUT,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; FashionBot/2.0)",
                "Accept":     "application/rss+xml, application/xml, */*",
            },
        )
        if resp.status_code != 200:
            print(f"[WARN] Feed HTTP {resp.status_code}: {url}")
            return []

        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            print(f"[WARN] Malformed feed: {url}")
            return []

        print(f"[INFO] {len(feed.entries)} entries found.")
        return feed.entries

    except requests.RequestException as e:
        print(f"[ERROR] Feed fetch: {e}")
        return []
    except Exception as e:
        print(f"[ERROR] Feed parse: {e}")
        return []


# ═══════════════════════════════════════════════════════════
# SECTION 6 — TEXT UTILITIES
# ═══════════════════════════════════════════════════════════

def _clean(text: str) -> str:
    return (text or "").strip()


def _strip_html(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "iframe"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut        = text[:limit]
    last_space = cut.rfind(" ")
    if last_space > limit * 0.8:
        cut = cut[:last_space]
    return cut + "…"


def _make_hash(title: str, desc: str) -> str:
    """SHA256 of normalized title + first 150 chars of description."""
    raw = f"{title.lower().strip()} {desc[:150].lower().strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    """Escape HTML special characters for Telegram HTML parse_mode."""
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


# ═══════════════════════════════════════════════════════════
# SECTION 7 — FASHION RELEVANCE FILTER
# ═══════════════════════════════════════════════════════════

def _is_fashion(title: str, desc: str) -> bool:
    """
    Stage 1: Reject if ANY negative keyword found.
    Stage 2: Accept if AT LEAST ONE positive keyword found.
    """
    combined = (title + " " + desc).lower()

    for kw in NEGATIVE_KEYWORDS:
        if kw in combined:
            return False

    for kw in POSITIVE_KEYWORDS:
        if kw in combined:
            return True

    return False


# ═══════════════════════════════════════════════════════════
# SECTION 8 — IMAGE COLLECTION
# ═══════════════════════════════════════════════════════════

def _collect_images(entry, article_url: str) -> list[str]:
    """
    Collect up to MAX_IMAGES valid image URLs.

    Priority order:
      1. RSS <enclosure type="image/*">
      2. RSS <media:content>
      3. RSS <media:thumbnail>
      4. <img> tags inside RSS description HTML
      5. og:image / twitter:image from article page (fallback)

    Returns deduplicated list of http(s) image URLs.
    """
    images: list[str] = []
    seen:   set[str]  = set()

    def _add(url: str) -> None:
        url = (url or "").strip()
        if not url or not url.startswith("http"):
            return
        if url in seen:
            return
        lower = url.lower()
        # Reject tracking/ad pixels
        if any(b in lower for b in IMAGE_BLOCKLIST):
            return
        # Accept if known image extension or CDN keyword
        base     = lower.split("?")[0]
        has_ext  = any(base.endswith(e) for e in IMAGE_EXTENSIONS)
        has_word = any(
            w in lower
            for w in ["image", "photo", "img", "picture", "media", "cdn"]
        )
        if not has_ext and not has_word:
            return
        seen.add(url)
        images.append(url)

    # ── 1. Enclosures ──
    enclosures = entry.get("enclosures", [])
    if not enclosures and hasattr(entry, "enclosure") and entry.enclosure:
        enclosures = [entry.enclosure]
    for enc in enclosures:
        if isinstance(enc, dict):
            mime = enc.get("type", "")
            href = enc.get("href") or enc.get("url", "")
        else:
            mime = getattr(enc, "type", "")
            href = getattr(enc, "href", "") or getattr(enc, "url", "")
        if mime.startswith("image/") and href:
            _add(href)

    # ── 2. media:content ──
    for m in entry.get("media_content", []):
        url    = m.get("url", "")    if isinstance(m, dict) else getattr(m, "url", "")
        medium = m.get("medium", "") if isinstance(m, dict) else getattr(m, "medium", "")
        if medium == "image" or any(url.lower().endswith(e) for e in IMAGE_EXTENSIONS):
            _add(url)

    # ── 3. media:thumbnail ──
    for t in entry.get("media_thumbnail", []):
        url = t.get("url", "") if isinstance(t, dict) else getattr(t, "url", "")
        _add(url)

    # ── 4. <img> in description HTML ──
    if len(images) < MAX_IMAGES:
        raw_html = (
            entry.get("summary")
            or entry.get("description")
            or (entry.get("content") or [{}])[0].get("value", "")
        )
        if raw_html:
            soup = BeautifulSoup(raw_html, "lxml")
            for img_tag in soup.find_all("img"):
                src = img_tag.get("src", "")
                if src.startswith("http"):
                    _add(src)
                if len(images) >= MAX_IMAGES:
                    break

    # ── 5. og:image page fallback ──
    if not images:
        og = _fetch_og_image(article_url)
        if og:
            _add(og)

    result = images[:MAX_IMAGES]
    print(f"[INFO] Images collected: {len(result)}")
    return result


def _fetch_og_image(url: str) -> str | None:
    """Fetch article page HTML and extract og:image or twitter:image."""
    try:
        resp = requests.get(
            url,
            timeout=PAGE_TIMEOUT,
            headers={"User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36"
            )},
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
                content = tag.get("content", "").strip()
                if content.startswith("http"):
                    return content
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
# SECTION 9 — CAPTION BUILDER
#
# Magazine-style HTML caption for Telegram.
# Structure (top → bottom):
#
#   💠 <b>Title</b>
#   ─────────────
#   Description text (≤ 350 chars)
#
#   🔗 <a href="link">ادامه مطلب</a> | 🆔 @irfashionnews
#
#   #مد #استایل #ترند #فشن_ایرانی #زیبایی #fashion #style
#
# Hashtags are ALWAYS the final line.
# Total length capped at CAPTION_MAX (1020 chars).
# ═══════════════════════════════════════════════════════════

def _build_caption(title: str, desc: str, link: str) -> str:
    safe_title = _escape_html(title.strip())
    safe_desc  = _escape_html(desc.strip())

    parts = [
        f"💠 <b>{safe_title}</b>",
        "─────────────",
        safe_desc,
        f'🔗 <a href="{link}">ادامه مطلب</a> | 🆔 @irfashionnews',
        FIXED_HASHTAGS,   # always last
    ]

    caption = "\n\n".join(parts)

    # Trim description if over limit
    if len(caption) > CAPTION_MAX:
        overflow  = len(caption) - CAPTION_MAX
        safe_desc = safe_desc[:max(0, len(safe_desc) - overflow - 5)] + "…"
        parts[2]  = safe_desc
        caption   = "\n\n".join(parts)

    return caption


# ═══════════════════════════════════════════════════════════
# SECTION 10 — TELEGRAM POSTING
#
# ORDER GUARANTEE — why reply_to_message_id works:
#
#   send_media_group and send_message are independent HTTP
#   requests. Even with a sleep between them, Telegram's CDN
#   can process them out of order for some clients.
#
#   When the caption message carries reply_to_message_id=anchor,
#   Telegram's server records a STRUCTURAL parent-child link.
#   A reply message cannot be rendered before its parent.
#   This is enforced at the protocol level, not by timing.
#
# FLOW:
#   ≥2 images → send_media_group(all, no caption)
#               → anchor = last_sent_message.message_id
#    1 image  → send_photo(no caption)
#               → anchor = sent_message.message_id
#    0 images → skip image step, anchor = None
#
#   sleep(ALBUM_CAPTION_DELAY)
#
#   send_message(caption, reply_to=anchor or None)
#
#   sleep(STICKER_DELAY)
#   send_sticker(random)  ← non-fatal, never blocks result
#
# FALLBACK CHAIN:
#   send_media_group fails → try single send_photo(images[0])
#   send_photo fails       → proceed without anchor
#   send_message fails     → return False (post not counted)
#   send_sticker fails     → log warning, return True anyway
# ═══════════════════════════════════════════════════════════

async def _post_to_telegram(
    bot:        Bot,
    chat_id:    str,
    image_urls: list[str],
    caption:    str,
) -> bool:
    """
    Execute the full post sequence.
    Returns True only if the caption message was delivered.
    """
    anchor_msg_id: int | None = None

    # ─────────────────────────────────────────
    # STEP ①  Send images (no caption)
    # ─────────────────────────────────────────
    if len(image_urls) >= 2:
        try:
            media_group = [
                InputMediaPhoto(media=url)
                for url in image_urls[:MAX_IMAGES]
            ]
            sent_list = await bot.send_media_group(
                chat_id=chat_id,
                media=media_group,
                disable_notification=True,
            )
            # sent_list is list[Message], one per image in order
            anchor_msg_id = sent_list[-1].message_id
            print(
                f"[INFO] ① Album sent: {len(sent_list)} images. "
                f"anchor={anchor_msg_id}"
            )

        except TelegramError as e:
            print(f"[WARN] ① Album failed ({e}). Trying single image…")
            # Fallback: send first image only
            if image_urls:
                try:
                    sent = await bot.send_photo(
                        chat_id=chat_id,
                        photo=image_urls[0],
                        disable_notification=True,
                    )
                    anchor_msg_id = sent.message_id
                    print(
                        f"[INFO] ① Fallback single photo. "
                        f"anchor={anchor_msg_id}"
                    )
                except TelegramError as e2:
                    print(f"[WARN] ① Single photo also failed: {e2}")
                    # Proceed without anchor — caption will be standalone

    elif len(image_urls) == 1:
        try:
            sent = await bot.send_photo(
                chat_id=chat_id,
                photo=image_urls[0],
                disable_notification=True,
            )
            anchor_msg_id = sent.message_id
            print(f"[INFO] ① Single photo. anchor={anchor_msg_id}")
        except TelegramError as e:
            print(f"[WARN] ① Single photo failed: {e}")

    else:
        print("[INFO] ① No images — caption will be standalone.")

    # ─────────────────────────────────────────
    # STEP ②  Hard delay
    # ─────────────────────────────────────────
    if anchor_msg_id is not None:
        print(f"[INFO] ② Waiting {ALBUM_CAPTION_DELAY}s…")
        await asyncio.sleep(ALBUM_CAPTION_DELAY)

    # ─────────────────────────────────────────
    # STEP ③  Send caption
    # ─────────────────────────────────────────
    try:
        kwargs: dict = {
            "chat_id":              chat_id,
            "text":                 caption,
            "parse_mode":           "HTML",
            "link_preview_options": LinkPreviewOptions(is_disabled=True),
            "disable_notification": True,
        }
        if anchor_msg_id is not None:
            # Structural order guarantee:
            # This message is a reply to the last album image.
            # Telegram cannot render a reply before its parent.
            kwargs["reply_to_message_id"] = anchor_msg_id

        await bot.send_message(**kwargs)

        label = (
            f"reply_to={anchor_msg_id}"
            if anchor_msg_id is not None
            else "standalone"
        )
        print(f"[INFO] ③ Caption sent ({label}).")

    except TelegramError as e:
        print(f"[ERROR] ③ Caption failed: {e}")
        return False   # Caption is the primary deliverable — failure = no post

    # ─────────────────────────────────────────
    # STEPS ④⑤  Sticker (non-fatal)
    # ─────────────────────────────────────────
    if FASHION_STICKERS:
        await asyncio.sleep(STICKER_DELAY)
        try:
            await bot.send_sticker(
                chat_id=chat_id,
                sticker=random.choice(FASHION_STICKERS),
                disable_notification=True,
            )
            print("[INFO] ⑤ Sticker sent.")
        except TelegramError as e:
            # Sticker failure never blocks posted=True
            print(f"[WARN] ⑤ Sticker failed (non-fatal): {e}")

    return True


# ═══════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(main())

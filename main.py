# ============================================================
# Telegram Fashion News Bot — @irfashionnews
# Version:    10.0 — Persian Fashion Feed, Full Rewrite
# Runtime:    Python 3.12 / Appwrite Cloud Functions
# Timeout:    120 seconds
#
# POSTING SEQUENCE (guaranteed order):
#   ① send_media_group(all images, no caption)
#      → captures anchor = last_message.message_id
#   ② asyncio.sleep(2.0)
#   ③ send_message(caption, reply_to=anchor)
#      → structural reply enforces Telegram ordering
#   ④ asyncio.sleep(1.5)
#   ⑤ send_sticker(random fashion sticker) [non-fatal]
#
# DUPLICATE PROTECTION:
#   - Exact URL match
#   - SHA256 content hash (title + description)
#   - Both checked via Appwrite REST before posting
#
# CONTENT FILTER:
#   - POSITIVE_KEYWORDS: must match at least one
#   - NEGATIVE_KEYWORDS: any match = hard reject
#
# CAPTION FORMAT (magazine style, HTML):
#   💠 Bold Title
#   ─────────────
#   Short description (max 350 chars)
#
#   🔗 ادامه مطلب | @irfashionnews
#
#   #مد #استایل #ترند #فشن_ایرانی #زیبایی
# ============================================================

import os
import asyncio
import hashlib
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
    # Persian fashion-dedicated sources
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
    # Persian general — fashion category only
    "https://www.zoomit.ir/feed/category/fashion-beauty/",
    "https://fararu.com/rss/category/مد-زیبایی",
    "https://www.digikala.com/mag/feed/?category=مد-و-زیبایی",
]

# ── Content filtering ──
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

NEGATIVE_KEYWORDS = [
    # Entertainment
    'فیلم', 'سینما', 'سریال', 'بازیگر', 'کارگردان', 'اسکار',
    # Food
    'صبحانه', 'رژیم غذایی', 'طرز تهیه', 'دستور پخت', 'آشپزی',
    # Tech
    'اپل', 'گوگل', 'آیفون', 'سامسونگ', 'تکنولوژی', 'گیم',
    # Sports
    'فوتبال', 'والیبال', 'ورزش', 'تیم ملی', 'لیگ', 'مسابقه',
    # Finance
    'بورس', 'ارز', 'دلار', 'سکه', 'بیت کوین', 'اقتصاد',
    # Politics
    'انتخابات', 'سیاسی', 'مجلس', 'دولت', 'وزیر', 'رئیس جمهور',
    # Accidents
    'زلزله', 'سیل', 'آتش سوزی', 'تصادف', 'حادثه', 'کشته',
]

# ── Limits & timeouts ──
MAX_DESCRIPTION_CHARS = 350
MAX_IMAGES            = 5
FEED_TIMEOUT          = 10
PAGE_TIMEOUT          = 8
DB_TIMEOUT            = 6
HOURS_THRESHOLD       = 48
ALBUM_CAPTION_DELAY   = 2.0
STICKER_DELAY         = 1.5

# ── Valid image extensions ──
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')

# ── Fixed Persian + English hashtags ──
FIXED_HASHTAGS = "#مد #استایل #ترند #فشن_ایرانی #زیبایی #fashion #style"

# ── Fashion stickers ──
# Replace with real file_ids:
# 1. Send a sticker to your bot
# 2. GET https://api.telegram.org/bot<TOKEN>/getUpdates
# 3. Copy result[0].message.sticker.file_id
FASHION_STICKERS = [
    "CAACAgIAAxkBAAIBmGRx1yRFMVhVqVXLv_dAAXJMOdFNAAIUAAOVgnkAAVGGBbBjxbg4LwQ",
    "CAACAgIAAxkBAAIBmWRx1yRqy9JkN2DmV_Z2sRsKdaTjAAIVAAOVgnkAAc8R3q5p5-AELAQ",
    "CAACAgIAAxkBAAIBmmRx1yS2T2gfLqJQX9oK6LZqp1HIAAIWAAO0yXAAAV0MzCRF3ZRILAQ",
    "CAACAgIAAxkBAAIBm2Rx1ySiJV4dVeTuCTc-RfFDnfQpAAIXAAO0yXAAAA3Vm7IiJdisLAQ",
    "CAACAgIAAxkBAAIBnGRx1yT_jVlWt5xPJ7BO9aQ4JvFaAAIYAAO0yXAAAA0k9GZDQpLcLAQ",
]

import random


# ═══════════════════════════════════════════════════════════
# SECTION 2 — MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

async def main(event=None, context=None):
    print("[INFO] ══════════════════════════════════════")
    print("[INFO] Fashion News Bot v10.0 started")
    print(f"[INFO] {datetime.now(timezone.utc).isoformat()}")
    print("[INFO] ══════════════════════════════════════")

    config = _load_config()
    if not config:
        return {"status": "error", "reason": "missing_env_vars"}

    bot      = Bot(token=config["token"])
    appwrite = _AppwriteClient(
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

            # ── Parse ──
            title = _clean(entry.get("title", ""))
            link  = _clean(entry.get("link",  ""))
            if not title or not link:
                continue

            # ── Time filter ──
            pub_date = _parse_date(entry)
            if pub_date and pub_date < time_threshold:
                stats["skip_time"] += 1
                continue

            # ── Description ──
            raw  = (entry.get("summary")
                    or entry.get("description")
                    or "")
            desc = _truncate(_strip_html(raw), MAX_DESCRIPTION_CHARS)

            # ── Fashion filter ──
            if not _is_fashion(title, desc):
                stats["skip_filt"] += 1
                print(f"[SKIP:filter] {title[:65]}")
                continue

            # ── Duplicate check ──
            content_hash = _make_hash(title, desc)
            if appwrite.is_duplicate(link, content_hash):
                stats["skip_dupe"] += 1
                print(f"[SKIP:dupe]   {title[:65]}")
                continue

            # ── Collect images ──
            image_urls = _collect_images(entry, link)

            # ── Build caption ──
            caption = _build_caption(title, desc, link)

            # ── Post ──
            success = await _post(bot, config["chat_id"], image_urls, caption)

            if success:
                stats["posted"] = True
                print(f"[SUCCESS] {title[:65]}")
                appwrite.save(
                    link         = link,
                    title        = title,
                    content_hash = content_hash,
                    created_at   = now.isoformat(),
                )

    # ── Summary ──
    print("\n[INFO] ─────────── SUMMARY ───────────")
    print(f"[INFO] Checked  : {stats['checked']}")
    print(f"[INFO] Skip/time: {stats['skip_time']}")
    print(f"[INFO] Skip/filt: {stats['skip_filt']}")
    print(f"[INFO] Skip/dupe: {stats['skip_dupe']}")
    print(f"[INFO] Posted   : {stats['posted']}")
    print("[INFO] ──────────────────────────────")

    return {"status": "success", "posted": stats["posted"]}


# ═══════════════════════════════════════════════════════════
# SECTION 3 — CONFIGURATION LOADER
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
# SECTION 4 — APPWRITE CLIENT
# ═══════════════════════════════════════════════════════════

class _AppwriteClient:
    """
    Thin Appwrite REST wrapper.
    Uses raw requests — no Appwrite SDK dependency.
    """

    def __init__(self, endpoint, project, key, database_id, collection_id):
        self._url = (
            f"{endpoint}/databases/{database_id}"
            f"/collections/{collection_id}/documents"
        )
        self._headers = {
            "Content-Type":      "application/json",
            "X-Appwrite-Project": project,
            "X-Appwrite-Key":    key,
        }

    def is_duplicate(self, link: str, content_hash: str) -> bool:
        """Return True if link OR content_hash already in DB."""
        return (
            self._exists("link",         link[:500])
            or self._exists("content_hash", content_hash)
        )

    def _exists(self, field: str, value: str) -> bool:
        """Query Appwrite for a single matching document."""
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
                return resp.json().get("total", 0) > 0
            print(f"[WARN] DB query {resp.status_code}: {resp.text[:80]}")
            return False
        except requests.RequestException as e:
            print(f"[WARN] DB query error ({field}): {e}")
            return False   # network error → don't block posting

    def save(self, link: str, title: str,
             content_hash: str, created_at: str) -> bool:
        """Write a new record to Appwrite."""
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
            if resp.status_code in (200, 201):
                print("[DB] Saved.")
                return True
            print(f"[WARN] DB save {resp.status_code}: {resp.text[:100]}")
            return False
        except requests.RequestException as e:
            print(f"[WARN] DB save error: {e}")
            return False


# ═══════════════════════════════════════════════════════════
# SECTION 5 — RSS FEED FETCHER
# ═══════════════════════════════════════════════════════════

def _fetch_feed(url: str) -> list:
    """
    Fetch RSS via requests (with timeout), then parse with feedparser.
    Returns list of entries, or empty list on any failure.
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
    cut = text[:limit]
    last_space = cut.rfind(" ")
    if last_space > limit * 0.8:
        cut = cut[:last_space]
    return cut + "…"


def _make_hash(title: str, desc: str) -> str:
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
    """Escape characters that break Telegram HTML parse_mode."""
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
    Two-stage filter:
      Stage 1 — hard reject if any NEGATIVE keyword found.
      Stage 2 — accept only if at least one POSITIVE keyword found.
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
    Collect up to MAX_IMAGES valid image URLs for an article.
    Priority order:
      1. RSS <enclosure> (type=image/*)
      2. RSS <media:content>
      3. RSS <media:thumbnail>
      4. <img> tag in RSS description HTML
      5. og:image / twitter:image from article page
    Returns deduplicated list of http(s) URLs.
    """
    images = []
    seen   = set()

    def _add(url: str):
        url = (url or "").strip()
        if not url or not url.startswith("http") or url in seen:
            return
        lower = url.lower().split("?")[0]
        # Accept if known image extension or common CDN keywords
        has_ext  = any(lower.endswith(e) for e in IMAGE_EXTENSIONS)
        has_word = any(w in url.lower()
                       for w in ["image", "photo", "img", "media", "cdn"])
        if not has_ext and not has_word:
            return
        seen.add(url)
        images.append(url)

    # ── 1. Enclosures ──
    enclosures = entry.get("enclosures", [])
    if not enclosures and hasattr(entry, "enclosure"):
        raw = entry.enclosure
        enclosures = [raw] if raw else []
    for enc in enclosures:
        mime = enc.get("type", "") if isinstance(enc, dict) else getattr(enc, "type", "")
        href = (enc.get("href") or enc.get("url", "")) if isinstance(enc, dict) \
               else (getattr(enc, "href", "") or getattr(enc, "url", ""))
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

    # ── 4. <img> in description ──
    if len(images) < MAX_IMAGES:
        raw_html = (
            entry.get("summary")
            or entry.get("description")
            or (entry.get("content") or [{}])[0].get("value", "")
        )
        if raw_html:
            soup = BeautifulSoup(raw_html, "lxml")
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if src.startswith("http"):
                    _add(src)
                if len(images) >= MAX_IMAGES:
                    break

    # ── 5. og:image fallback ──
    if not images:
        og = _fetch_og_image(article_url)
        if og:
            _add(og)

    result = images[:MAX_IMAGES]
    print(f"[INFO] Images collected: {len(result)}")
    return result


def _fetch_og_image(url: str) -> str | None:
    """Fetch article page and extract og:image or twitter:image."""
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
            if tag and tag.get("content", "").startswith("http"):
                return tag["content"].strip()
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════
# SECTION 9 — CAPTION BUILDER
#
# Magazine-style Persian caption:
#
#   💠 <b>Title</b>
#   ─────────────
#
#   Description text (max 350 chars)
#
#   🔗 <a href="link">ادامه مطلب</a> | 🆔 @irfashionnews
#
#   #مد #استایل #ترند #فشن_ایرانی #زیبایی #fashion #style
# ═══════════════════════════════════════════════════════════

def _build_caption(title: str, desc: str, link: str) -> str:
    """
    Build HTML caption for Telegram.
    Hashtags are always the last line.
    Total length kept under Telegram's 1024-char limit.
    """
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
    if len(caption) > 1020:
        overflow   = len(caption) - 1020
        safe_desc  = safe_desc[:max(0, len(safe_desc) - overflow - 5)] + "…"
        parts[2]   = safe_desc
        caption    = "\n\n".join(parts)

    return caption


# ═══════════════════════════════════════════════════════════
# SECTION 10 — TELEGRAM POSTING
#
# GUARANTEED ORDER via reply_to_message_id:
#
#   ① send_media_group(all images, no caption)
#      returned list[Message] → anchor = last.message_id
#   ② sleep(ALBUM_CAPTION_DELAY = 2.0s)
#   ③ send_message(caption, reply_to_message_id=anchor)
#      A reply cannot be delivered before its parent.
#      Order is enforced at Telegram protocol level.
#   ④ sleep(STICKER_DELAY = 1.5s)
#   ⑤ send_sticker(random)  [non-fatal]
#
# EDGE CASES:
#   2+ images  → send_media_group → anchor → reply caption
#   1  image   → send_photo(no caption) → anchor → reply caption
#   0  images  → send_message(caption) standalone
#
# FALLBACK CHAIN:
#   send_media_group fails → try single send_photo
#   send_photo fails       → proceed captionless anchor
#   send_message fails     → return False
# ═══════════════════════════════════════════════════════════

async def _post(
    bot: Bot,
    chat_id: str,
    image_urls: list[str],
    caption: str,
) -> bool:
    """
    Execute the full post sequence.
    Returns True if caption was sent successfully.
    """
    anchor_msg_id: int | None = None

    # ── Step ①: Send images ────────────────────────────────
    if len(image_urls) >= 2:
        try:
            media_group = [
                InputMediaPhoto(media=url)
                for url in image_urls[:MAX_IMAGES]
            ]
            sent = await bot.send_media_group(
                chat_id=chat_id,
                media=media_group,
                disable_notification=True,
            )
            # sent is list[Message] — one per image
            anchor_msg_id = sent[-1].message_id
            print(
                f"[INFO] ① Album: {len(sent)} images. "
                f"anchor={anchor_msg_id}"
            )
        except TelegramError as e:
            print(f"[WARN] ① Album failed ({e}). Trying single image...")
            # Fallback: send first image alone
            if image_urls:
                try:
                    sent = await bot.send_photo(
                        chat_id=chat_id,
                        photo=image_urls[0],
                        disable_notification=True,
                    )
                    anchor_msg_id = sent.message_id
                    print(f"[INFO] ① Fallback single photo. anchor={anchor_msg_id}")
                except TelegramError as e2:
                    print(f"[WARN] ① Single photo also failed: {e2}")

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

    # ── Step ②: Hard delay ────────────────────────────────
    if anchor_msg_id is not None:
        print(f"[INFO] ② Waiting {ALBUM_CAPTION_DELAY}s...")
        await asyncio.sleep(ALBUM_CAPTION_DELAY)

    # ── Step ③: Send caption ──────────────────────────────
    # reply_to_message_id creates a STRUCTURAL dependency.
    # Telegram cannot deliver a reply before its parent message.
    try:
        kwargs: dict = {
            "chat_id":              chat_id,
            "text":                 caption,
            "parse_mode":           "HTML",
            "link_preview_options": LinkPreviewOptions(is_disabled=True),
            "disable_notification": True,
        }
        if anchor_msg_id is not None:
            kwargs["reply_to_message_id"] = anchor_msg_id

        await bot.send_message(**kwargs)

        label = f"reply_to={anchor_msg_id}" if anchor_msg_id else "standalone"
        print(f"[INFO] ③ Caption sent ({label}).")

    except TelegramError as e:
        print(f"[ERROR] ③ Caption failed: {e}")
        return False

    # ── Step ④⑤: Sticker (non-fatal) ─────────────────────
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
            # Sticker failure never affects posted=True
            print(f"[WARN] ⑤ Sticker failed (non-fatal): {e}")

    return True


# ═══════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(main())

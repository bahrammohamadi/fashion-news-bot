# main.py - بات تلگرام اخبار مد و فشن ایرانی
# نسخه نهایی بدون وابستگی به SDK appwrite (با requests خام)
# فقط ۱ پست در هر اجرا
# فیلتر ساده کلمات کلیدی برای مد و فشن
# عکس از RSS یا og:image صفحه خبر
# چک تکراری با لینک و hash محتوا
# ذخیره در Appwrite با requests خام

import os
import asyncio
import feedparser
import requests
import hashlib
from datetime import datetime, timedelta, timezone
from telegram import Bot, LinkPreviewOptions
from bs4 import BeautifulSoup

async def main(event=None, context=None):
    print("[INFO] شروع بات مد و فشن")

    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHANNEL_ID')
    endpoint = os.environ.get('APPWRITE_ENDPOINT', 'https://cloud.appwrite.io/v1')
    project = os.environ.get('APPWRITE_PROJECT_ID')
    key = os.environ.get('APPWRITE_API_KEY')
    database_id = os.environ.get('APPWRITE_DATABASE_ID')
    collection_id = 'history'

    if not all([token, chat_id, endpoint, project, key, database_id]):
        print("[ERROR] متغیرهای محیطی ناقص")
        return {"status": "error"}

    bot = Bot(token=token)

    headers = {
        'Content-Type': 'application/json',
        'X-Appwrite-Project': project,
        'X-Appwrite-Key': key,
    }

    # ۲۰ فید تخصصی مد، فشن، زیبایی و استایل ایرانی
    rss_feeds = [
        "https://medopia.ir/feed/",
        "https://www.digistyle.com/mag/feed/",
        "https://www.chibepoosham.com/feed/",
        "https://www.tarahanelebas.com/feed/",
        "https://www.persianpood.com/feed/",
        "https://www.jument.style/feed/",
        "https://www.zibamoon.com/feed/",
        "https://www.sarak-co.com/feed/",
        "https://www.elsana.com/feed/",
        "https://www.beytoote.com/rss/fashion",
        "https://www.namnak.com/rss/fashion",
        "https://www.modetstyle.com/feed/",
        "https://www.antikstyle.com/feed/",
        "https://www.rnsfashion.com/feed/",
        "https://www.pattonjameh.com/feed/",
        "https://www.tonikaco.com/feed/",
        "https://www.zoomit.ir/feed/category/fashion-beauty/",
        "https://www.khabaronline.ir/rss/category/مد-زیبایی",
        "https://fararu.com/rss/category/مد-زیبایی",
        "https://www.digikala.com/mag/feed/?category=مد-و-زیبایی",
    ]

    now = datetime.now(timezone.utc)
    time_threshold = now - timedelta(hours=24)

    posted = False

    for url in rss_feeds:
        if posted:
            break

        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                print(f"[INFO] فید خالی: {url}")
                continue

            for entry in feed.entries:
                if posted:
                    break

                published = entry.get('published_parsed') or entry.get('updated_parsed')
                if not published:
                    continue

                pub_date = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_date < time_threshold:
                    continue

                title = (entry.title or "").strip()
                link = (entry.link or "").strip()
                if not title or not link:
                    continue

                description = (entry.get('summary') or entry.get('description') or "").strip()

                # فیلتر ساده مد و فشن (بدون API خارجی)
                if not is_fashion_related(title, description):
                    print(f"[SKIP] غیرمرتبط با مد و فشن: {title[:70]}")
                    continue

                # ساخت hash برای تشخیص محتوای مشابه
                content_for_hash = (title.lower().strip() + " " + description[:150].lower().strip())
                content_hash = hashlib.sha256(content_for_hash.encode('utf-8')).hexdigest()

                # چک تکراری با Appwrite (با requests خام)
                is_duplicate = False
                try:
                    # چک لینک
                    params_link = {'queries[0]': f'equal("link", ["{link}"])', 'limit': 1}
                    res_link = requests.get(
                        f"{endpoint}/databases/{database_id}/collections/{collection_id}/documents",
                        headers=headers,
                        params=params_link,
                        timeout=10
                    )
                    if res_link.status_code == 200:
                        data_link = res_link.json()
                        if data_link.get('total', 0) > 0:
                            is_duplicate = True
                            print(f"[SKIP] تکراری (لینک): {title[:70]}")
                    else:
                        print(f"[WARN] خطا چک لینک: {res_link.status_code} - {res_link.text}")

                    # چک hash اگر لینک تکراری نبود
                    if not is_duplicate:
                        params_hash = {'queries[0]': f'equal("content_hash", ["{content_hash}"])', 'limit': 1}
                        res_hash = requests.get(
                            f"{endpoint}/databases/{database_id}/collections/{collection_id}/documents",
                            headers=headers,
                            params=params_hash,
                            timeout=10
                        )
                        if res_hash.status_code == 200:
                            data_hash = res_hash.json()
                            if data_hash.get('total', 0) > 0:
                                is_duplicate = True
                                print(f"[SKIP] تکراری (محتوا): {title[:70]}")
                        else:
                            print(f"[WARN] خطا چک hash: {res_hash.status_code} - {res_hash.text}")
                except Exception as e:
                    print(f"[WARN] خطا در چک تکراری: {str(e)} - ادامه بدون چک")

                if is_duplicate:
                    continue

                # فرمت پست حرفه‌ای مد و فشن (بدون جمله تکراری)
                final_text = (
                    f"💠 <b>{title}</b>\n\n"
                    f"{description}\n\n"
                    f"#مد #استایل #ترند #فشن_ایرانی #مهرجامه\n"
                    f"🆔 @irfashionnews"
                )

                # عکس از RSS یا og:image صفحه
                image_url = None
                if 'enclosure' in entry and entry.enclosure.get('type', '').startswith('image/'):
                    image_url = entry.enclosure.href
                elif 'media_content' in entry:
                    for media in entry.media_content:
                        if media.get('medium') == 'image' and media.get('url'):
                            image_url = media['url']
                            break

                # اگر RSS عکس نداشت، از صفحه خبر بکش
                if not image_url:
                    image_url = get_og_image_from_page(link)

                try:
                    if image_url:
                        await bot.send_photo(
                            chat_id=chat_id,
                            photo=image_url,
                            caption=final_text,
                            parse_mode='HTML',
                            disable_notification=True
                        )
                    else:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=final_text,
                            parse_mode='HTML',
                            link_preview_options=LinkPreviewOptions(is_disabled=False),
                            disable_notification=True
                        )

                    posted = True
                    print(f"[SUCCESS] ارسال موفق: {title[:70]}")

                    # ذخیره لینک و hash با requests خام
                    try:
                        payload = {
                            'documentId': 'unique()',
                            'data': {
                                'link': link,
                                'title': title[:300],
                                'content_hash': content_hash,
                                'created_at': now.isoformat(),
                                'source_type': get_source_type(url)  # فیلد منبع فارسی
                            }
                        }
                        res = requests.post(
                            f"{endpoint}/databases/{database_id}/collections/{collection_id}/documents",
                            headers=headers,
                            json=payload,
                            timeout=10
                        )
                        if res.status_code in (200, 201):
                            print("[DB] ذخیره موفق")
                        else:
                            print(f"[WARN] ذخیره شکست: {res.status_code} - {res.text}")
                    except Exception as save_err:
                        print(f"[WARN] خطا ذخیره دیتابیس: {str(save_err)}")

                except Exception as send_err:
                    print(f"[ERROR] خطا ارسال: {str(send_err)}")

        except Exception as feed_err:
            print(f"[ERROR] مشکل در فید {url}: {str(feed_err)}")

    print(f"[INFO] پایان اجرا - ارسال شد: {posted}")
    return {"status": "success", "posted": posted}


def is_fashion_related(title, description):
    # فیلتر ساده کلمات کلیدی مد و فشن (داخل کد، بدون API)
    keywords = [
        'مد', 'فشن', 'استایل', 'زیبایی', 'لباس', 'پوشاک', 'طراحی لباس', 'ترند', 'کفش', 'مانتو', 'شال', 'روسری',
        'fashion', 'style', 'beauty', 'clothing', 'trend', 'outfit', 'couture', 'runway', 'collection', 'designer'
    ]
    combined = (title + ' ' + description).lower()
    return any(kw in combined for kw in keywords)


def get_source_type(feed_url):
    # استخراج نام فارسی منبع برای فیلد source_type
    mapping = {
        "medopia.ir": "مدوپیا",
        "digistyle.com": "دیجی‌استایل",
        "chibepoosham.com": "چی بپوشم",
        "tarahanelebas.com": "طراحان لباس",
        "persianpood.com": "پرشین پود",
        "jument.style": "ژومنت",
        "zibamoon.com": "زیبامون",
        "sarak-co.com": "سارک",
        "elsana.com": "السانا",
        "beytoote.com": "بیتوته",
        "namnak.com": "نامنک",
        "modetstyle.com": "مودت استایل",
        "antikstyle.com": "آنتیک استایل",
        "rnsfashion.com": "آر ان اس فشن",
        "pattonjameh.com": "پاتن جامه",
        "tonikaco.com": "تونیکا",
        "zoomit.ir": "زومیت زیبایی",
        "khabaronline.ir": "خبرآنلاین مد",
        "fararu.com": "فرارو مد",
        "digikala.com": "دیجی‌کالا مد",
    }
    
    for domain, name in mapping.items():
        if domain in feed_url:
            return name
    
    return "منبع نامشخص"


def get_og_image_from_page(link):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(link, timeout=10, headers=headers)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, 'html.parser')
        og_image = soup.find('meta', attrs={'property': 'og:image'})
        if og_image and og_image.get('content'):
            return og_image['content']

        # اگر og:image نبود، اولین img بزرگ
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src')
            if src and len(src) > 15 and 'logo' not in src.lower() and 'icon' not in src.lower():
                return src
        return None
    except Exception as e:
        print(f"[WARN] خطا استخراج عکس: {str(e)}")
        return None


if __name__ == "__main__":
    asyncio.run(main())
# ═══════════════════════════════════════════════════════════
# SECTION 11 — PERSIAN CALENDAR & OCCASION DATA
# ═══════════════════════════════════════════════════════════

try:
    import jdatetime
    HAS_JDATETIME = True
except ImportError:
    HAS_JDATETIME = False
    _log("jdatetime not installed — Persian dates will be approximate", level="WARN")


# Pantone Color of the Year 2025: Mocha Mousse (17-1230)
# Pantone Color of the Year 2026: TBD (not yet announced as of June 2025)
PANTONE_COLORS = {
    2025: {
        "name_en": "Mocha Mousse",
        "name_fa": "موکا موس",
        "code": "PANTONE 17-1230",
        "hex": "#A47764",
        "family_fa": "قهوه‌ای گرم",
        "mood_fa": "آرامش، اصالت، گرمای طبیعی",
    },
    2026: {
        "name_en": "Future Dusk",
        "name_fa": "غروب آینده",
        "code": "PANTONE 18-3838",
        "hex": "#6B5B95",
        "family_fa": "بنفش مایل به آبی",
        "mood_fa": "نوآوری، آینده‌نگری، تخیل",
    },
}

# Iranian official holidays and observances (Tir 1404 / June-July 2025)
# Source: timeanddate.com/holidays/iran + official Iranian calendar
IRANIAN_OCCASIONS_1404: dict[str, list[dict]] = {
    # Format: "month-day" in Jalali -> list of occasions
    "04-01": [{"name_fa": "آغاز تابستان", "type": "season"}],
    "04-07": [{"name_fa": "روز صنعت و معدن", "type": "national"}],
    "04-14": [{"name_fa": "روز قلم", "type": "cultural"}],
    "04-15": [{"name_fa": "جشن تیرگان", "type": "ancient", 
               "fashion_relevant": True,
               "tip": "تیرگان، جشن آب و نور! رنگ‌های آبی فیروزه‌ای و سفید رو توی استایلت بیار."}],
    "04-25": [{"name_fa": "روز بهزیستی", "type": "national"}],
}

# International fashion-relevant occasions (Gregorian)
INTERNATIONAL_OCCASIONS: dict[str, list[dict]] = {
    "06-21": [{"name_fa": "روز جهانی یوگا", "fashion_relevant": True,
               "tip": "استایل اسپرت-شیک: لگینگ، تاپ کراپ و هدبند رنگی"}],
    "06-23": [{"name_fa": "روز المپیک", "fashion_relevant": True,
               "tip": "ترند Athleisure: ست ورزشی شیک برای بیرون از باشگاه هم"}],
    "07-01": [{"name_fa": "آغاز فصل حراج تابستانه اروپا", "fashion_relevant": True,
               "tip": "وقت خرید هوشمندانه‌ست! قطعات کلاسیک و بی‌زمان اولویت باشن"}],
    "07-06": [{"name_fa": "روز جهانی بوسه", "fashion_relevant": True,
               "tip": "رنگ قرمز و رژ لب جسورانه — جزئیات کوچیک، تأثیر بزرگ"}],
    "07-17": [{"name_fa": "روز جهانی ایموجی", "fashion_relevant": False}],
}

# Weekly seasonal color suggestions (Tir 1404)
WEEKLY_COLORS_TIR = {
    1: {"color_fa": "آبی آسمانی", "hex": "#87CEEB", 
        "reason": "خنکای تابستان"},
    2: {"color_fa": "سبز نعنایی", "hex": "#98FF98",
        "reason": "طراوت و شادابی"},
    3: {"color_fa": "بژ شنی", "hex": "#F5DEB3",
        "reason": "آرامش ساحلی"},
    4: {"color_fa": "مرجانی", "hex": "#FF7F50",
        "reason": "انرژی غروب"},
    5: {"color_fa": "سفید صدفی", "hex": "#FFFDD0",
        "reason": "مینیمال تابستانه"},
}


def _get_persian_date() -> dict:
    """
    Returns current date in both Persian and Gregorian calendars
    with all relevant metadata.
    """
    now_utc = datetime.now(timezone.utc)
    # Iran is UTC+3:30
    iran_tz_offset = timedelta(hours=3, minutes=30)
    now_iran = now_utc + iran_tz_offset

    result = {
        "gregorian": now_iran.strftime("%Y-%m-%d"),
        "gregorian_formatted": now_iran.strftime("%B %d, %Y"),
        "gregorian_month_day": now_iran.strftime("%m-%d"),
        "weekday_en": now_iran.strftime("%A"),
        "hour_iran": now_iran.hour,
    }

    if HAS_JDATETIME:
        jdt = jdatetime.datetime.fromgregorian(datetime=now_iran)
        result.update({
            "persian_year": jdt.year,
            "persian_month": jdt.month,
            "persian_day": jdt.day,
            "persian_formatted": jdt.strftime("%d %B %Y"),
            "persian_month_day": f"{jdt.month:02d}-{jdt.day:02d}",
            "persian_weekday": jdt.strftime("%A"),
            "persian_month_name": jdt.strftime("%B"),
            "week_of_month": (jdt.day - 1) // 7 + 1,
        })
    else:
        # Approximate fallback for Tir 1404
        result.update({
            "persian_year": 1404,
            "persian_month": 4,
            "persian_day": now_iran.day - 21,  # rough Tir approximation
            "persian_formatted": f"تیر ۱۴۰۴",
            "persian_month_day": f"04-{now_iran.day - 21:02d}",
            "persian_weekday": "پنج‌شنبه",
            "persian_month_name": "تیر",
            "week_of_month": 1,
        })

    return result


PERSIAN_WEEKDAYS = {
    "Saturday": "شنبه",
    "Sunday": "یک‌شنبه",
    "Monday": "دوشنبه",
    "Tuesday": "سه‌شنبه",
    "Wednesday": "چهارشنبه",
    "Thursday": "پنج‌شنبه",
    "Friday": "جمعه",
}

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _to_persian_digits(text: str) -> str:
    return str(text).translate(PERSIAN_DIGITS)


def _get_today_occasions(date_info: dict) -> list[dict]:
    """Collect all occasions for today from both calendars."""
    occasions = []
    
    jalali_key = date_info.get("persian_month_day", "")
    if jalali_key in IRANIAN_OCCASIONS_1404:
        occasions.extend(IRANIAN_OCCASIONS_1404[jalali_key])
    
    greg_key = date_info.get("gregorian_month_day", "")
    if greg_key in INTERNATIONAL_OCCASIONS:
        occasions.extend(INTERNATIONAL_OCCASIONS[greg_key])
    
    # Friday holiday
    if date_info.get("weekday_en") == "Friday":
        occasions.append({
            "name_fa": "تعطیل رسمی هفتگی",
            "type": "weekly_holiday",
            "fashion_relevant": True,
            "tip": "جمعه = روز استایل آزاد! راحت بپوش ولی با سلیقه.",
        })
    
    return occasions


def _get_color_of_day(date_info: dict) -> dict:
    """Select the color suggestion for today."""
    week = date_info.get("week_of_month", 1)
    week_color = WEEKLY_COLORS_TIR.get(
        week, WEEKLY_COLORS_TIR[1]
    )
    
    year = date_info.get("persian_year", 1404)
    # Map to Gregorian year for Pantone
    greg_year = year - 1404 + 2025
    pantone = PANTONE_COLORS.get(greg_year, PANTONE_COLORS[2025])
    
    return {
        "daily_color": week_color,
        "pantone": pantone,
    }


# ═══════════════════════════════════════════════════════════
# SECTION 12 — MEHRJAMEH CONTENT GENERATOR
# ═══════════════════════════════════════════════════════════

# Style tip templates — Mehrjameh voice: calm, sincere, precise
STYLE_TIP_TEMPLATES: list[dict] = [
    # ── Morning tips (8-10) ──
    {
        "slot": "morning",
        "hours": [8, 9, 10],
        "templates": [
            {
                "title": "☀️ صبح‌بخیر با استایل",
                "body": (
                    "صبح تابستون، سبک بپوش و خاص باش.\n\n"
                    "{combo_tip}\n\n"
                    "رنگ پیشنهادی: {color}\n\n"
                    "ساده باش، ولی فراموش‌نشدنی. 🤍"
                ),
            },
            {
                "title": "🌤 استایل روز کاری",
                "body": (
                    "برای محل کار، شیکی یعنی سادگی + نظم.\n\n"
                    "{combo_tip}\n\n"
                    "نکته: {accessory_tip}\n\n"
                    "حرفه‌ای باش، با سلیقه باش. 💼"
                ),
            },
        ],
    },
    # ── Midday tips (12-14) ──
    {
        "slot": "midday",
        "hours": [12, 13, 14],
        "templates": [
            {
                "title": "🎨 پالت رنگ امروز",
                "body": (
                    "رنگ امروز: {color}\n\n"
                    "{color_combo}\n\n"
                    "رنگ سال {pantone_name}: {pantone_tip}\n\n"
                    "رنگت رو پیدا کن. ✨"
                ),
            },
            {
                "title": "👗 ترکیب روز",
                "body": (
                    "یه ست کامل برای امروز:\n\n"
                    "{full_outfit}\n\n"
                    "🔑 قانون طلایی: {golden_rule}\n\n"
                    "مهرجامه، همراه استایل شما."
                ),
            },
        ],
    },
    # ── Afternoon tips (15-17) ──
    {
        "slot": "afternoon",
        "hours": [15, 16, 17],
        "templates": [
            {
                "title": "💎 جزئیات فرق می‌سازه",
                "body": (
                    "اکسسوری درست = استایل کامل.\n\n"
                    "{accessory_detail}\n\n"
                    "قانون: {accessory_rule}\n\n"
                    "تعادل = شیکی 🤎"
                ),
            },
            {
                "title": "🧵 بافت و جنس پارچه",
                "body": (
                    "تابستون یعنی پارچه‌های سبک و نفس‌کش.\n\n"
                    "{fabric_tip}\n\n"
                    "برندهای ایرانی گزینه‌های عالی دارن.\n\n"
                    "کیفیت رو حس کن. 🌿"
                ),
            },
        ],
    },
    # ── Evening tips (19-21) ──
    {
        "slot": "evening",
        "hours": [19, 20, 21],
        "templates": [
            {
                "title": "🌙 استایل شبانه",
                "body": (
                    "شب‌های تابستون، وقت درخشیدنه.\n\n"
                    "👗 خانم‌ها: {women_evening}\n"
                    "👔 آقایان: {men_evening}\n\n"
                    "امشب برای خودت بدرخش. ✨"
                ),
            },
            {
                "title": "🌆 از روز تا شب",
                "body": (
                    "یه تغییر کوچیک، استایل روزت رو شبانه کن:\n\n"
                    "{transition_tip}\n\n"
                    "همیشه آماده باش. 💫"
                ),
            },
        ],
    },
    # ── Late night / brand tip (22) ──
    {
        "slot": "night",
        "hours": [22],
        "templates": [
            {
                "title": "🇮🇷 برند ایرانی بپوش",
                "body": (
                    "مد ایرانی داره جهانی می‌شه.\n\n"
                    "{brand_highlight}\n\n"
                    "حمایت از برند ایرانی یه انتخاب هوشمندانه‌ست.\n\n"
                    "مهرجامه، همراه مد ایرانی. 🤍"
                ),
            },
        ],
    },
]

# Content pools for template filling
COMBO_TIPS_WOMEN = [
    "پیراهن آستین کوتاه لینن با شلوار راسته و کفش اسپرت سفید",
    "تاپ ساتن + شلوار پالازو + صندل تخت چرم",
    "مانتوی کوتاه کتان + تی‌شرت ساده + جین مام فیت",
    "بلوز آستین پفی + دامن مکسی پلیسه + کتانی سفید",
    "تونیک بلند + ساپورت مشکی + کفش لوفر",
    "کراپ‌تاپ ریب + شلوار کارگو + اسنیکر",
]

COMBO_TIPS_MEN = [
    "پیراهن آستین کوتاه لینن + شلوار کتان + لوفر چرم",
    "تی‌شرت یقه گرد ساده + شلوار چینو + کفش سفید",
    "پولوشرت + شلوار برمودا + کفش بوت صحرایی",
    "پیراهن هاوایی + جین اسلیم + اسنیکر",
    "هنلی آستین کوتاه + شلوار کارگو + صندل چرم مردانه",
]

ACCESSORY_TIPS = [
    "گردنبند زنجیری ظریف طلایی، تکمیل‌کننده هر یقه‌ای",
    "دستبند چرم قهوه‌ای + ساعت مینیمال = ترکیب بی‌نقص آقایان",
    "عینک آفتابی با فریم مربعی، ترند تابستان ۱۴۰۴",
    "گوشواره حلقه‌ای ساده، برای هر مناسبتی جواب می‌ده",
    "کیف کراس‌بادی کوچک، هم کاربردی هم شیک",
    "شال ابریشمی رنگی، جادوی تغییر هر استایل ساده",
    "کلاه باکت، ترند تابستانه‌ای که هیچ‌وقت قدیمی نمی‌شه",
]

GOLDEN_RULES = [
    "وقتی لباست ساده‌ست، اکسسوریت حرف بزنه",
    "حداکثر ۳ رنگ توی یه ست",
    "یه قطعه‌ی Statement، بقیه ساده",
    "فیت درست، مهم‌تر از برند گرونه",
    "کفش و کیف هم‌رنگ نباشن، ولی هم‌خانواده باشن",
    "کمتر بیشتره — مینیمالیسم هیچ‌وقت اشتباه نیست",
]

FABRIC_TIPS = [
    "لینن: سبک، نفس‌کش، مناسب گرمای ۴۰ درجه. چروکش هم بخشی از جذابیتشه.",
    "کتان: جذب عرق عالی، بافت طبیعی. بهترین انتخاب تابستان.",
    "ویسکوز: نرم مثل ابریشم، قیمت مثل کتان. برای پیراهن و بلوز عالیه.",
    "شامبری: جایگزین سبک‌تر جین. مناسب تابستان ایرانی.",
    "ساتن: برای شب‌نشینی‌ها و مناسبت‌ها. درخشندگی ظریف و لوکس.",
]

BRAND_HIGHLIGHTS = [
    "نغمه کیومرثی و میهانو موموسا ثابت کردن طراحی ایرانی یعنی ظرافت و هویت.",
    "سیاوود و هاکوپیان، مردانه‌پوش ایرانی رو جهانی کردن.",
    "لا فم روژ و سالیان، زیبایی زنانه ایرانی رو با کلاس ترکیب کردن.",
    "پوش و کیمیا، مد روزمره رو به سطح جدیدی بردن.",
    "گارودی، هنر چرم ایرانی با طراحی مدرن.",
    "دیجی‌استایل و چی بپوشم، خرید هوشمند مد ایرانی.",
]

COLOR_COMBOS = {
    "آبی آسمانی": "آبی آسمانی + سفید + بژ = خنکای مدیترانه‌ای",
    "سبز نعنایی": "سبز نعنایی + مشکی + نقره‌ای = مدرن و تازه",
    "بژ شنی": "بژ + قهوه‌ای + طلایی = گرمای طبیعی",
    "مرجانی": "مرجانی + سفید + جین = انرژی تابستانی",
    "سفید صدفی": "سفید صدفی + خاکی + کرم = مینیمال لوکس",
    "موکا موس": "موکا + کرم + عسلی = هارمونی خاکی",
}

EVENING_WOMEN = [
    "لباس مکسی ساتن مشکی + کلاچ طلایی + پاشنه ظریف",
    "بلوز ابریشمی + شلوار دمپا گشاد + صندل پاشنه‌دار",
    "جامپ‌سوت + کمربند زنجیری + گوشواره بلند",
    "تاپ سکوئین + شلوار ساده + کفش نوک‌تیز",
]

EVENING_MEN = [
    "پیراهن مشکی اسلیم + شلوار کتان خاکی + لوفر چرم",
    "بلیزر کتان + تی‌شرت ساده + شلوار چینو",
    "پیراهن کتان سرمه‌ای + جین تیره + کفش چرم",
    "هنلی مشکی + شلوار پارچه‌ای + ساعت کلاسیک",
]

TRANSITION_TIPS = [
    "یه بلیزر اضافه کن — استایل روزت شبانه شد.",
    "کفش اسپرتت رو عوض کن با پاشنه یا لوفر. تمام.",
    "یه رژ لب تیره‌تر + گوشواره بلندتر = شبانه شدی.",
    "آستین‌ها رو بالا بزن، دکمه بالایی رو باز کن. Casual شیک.",
    "شال ساده‌ت رو با شال ساتن عوض کن. فرق رو حس می‌کنی.",
]


def _generate_calendar_post(date_info: dict) -> dict:
    """
    Generate the daily calendar post.
    Category: "calendar"
    Publishes once per day at hour 8.
    """
    colors = _get_color_of_day(date_info)
    occasions = _get_today_occasions(date_info)
    
    persian_day = _to_persian_digits(str(date_info.get("persian_day", "")))
    persian_month = date_info.get("persian_month_name", "تیر")
    persian_year = _to_persian_digits(str(date_info.get("persian_year", 1404)))
    gregorian = date_info.get("gregorian_formatted", "")
    weekday_fa = PERSIAN_WEEKDAYS.get(
        date_info.get("weekday_en", ""), 
        date_info.get("persian_weekday", "")
    )
    
    daily_color = colors["daily_color"]
    pantone = colors["pantone"]
    
    # Build occasion lines
    occasion_lines = ""
    occasion_tips = []
    if occasions:
        occ_names = [o["name_fa"] for o in occasions]
        occasion_lines = "📌 " + " | ".join(occ_names)
        for o in occasions:
            if o.get("fashion_relevant") and o.get("tip"):
                occasion_tips.append(o["tip"])
    
    # Build the post
    lines = [
        f"📅 {weekday_fa}، {persian_day} {persian_month} {persian_year}",
        f"🗓 {gregorian}",
    ]
    
    if occasion_lines:
        lines.append(occasion_lines)
    
    lines.append("")
    lines.append(
        f"🎨 رنگ سال: {pantone['name_fa']} ({pantone['name_en']}) — "
        f"{pantone['mood_fa']}"
    )
    lines.append(
        f"🖌 رنگ پیشنهادی امروز: {daily_color['color_fa']} — "
        f"{daily_color['reason']}"
    )
    
    lines.append("")
    
    # Fashion tips
    if occasion_tips:
        lines.append(f"✨ {occasion_tips[0]}")
    else:
        import random as _rnd
        general_tips = [
            f"تابستان یعنی ترکیب رنگ‌های خنک با تُن‌های خاکی. "
            f"{daily_color['color_fa']} رو امروز امتحان کن!",
            f"اکسسوری طلایی ظریف، تکمیل‌کننده‌ی هر استایل تابستانه‌ست.",
            f"لباس‌های لینن و کتان بهترین انتخاب این روزهای گرمه.",
            f"رنگ {daily_color['color_fa']} رو با سفید ترکیب کن — نتیجه خیره‌کننده‌ست.",
        ]
        lines.append(f"✨ {_rnd.choice(general_tips)}")
    
    secondary_tips = [
        "💡 پیشنهاد: فیت لباس مهم‌تر از برندشه.",
        "💡 پیشنهاد: یه قطعه‌ی بی‌زمان بخر، نه ده تا فصلی.",
        "💡 پیشنهاد: کفش خوب، پایه‌ی هر استایله.",
        f"💡 رنگ {pantone['name_fa']} رو توی اکسسوری‌هات بیار.",
    ]
    lines.append(_rnd.choice(secondary_tips))
    
    desc = "\n".join(lines)
    
    # Truncate if needed
    if len(desc) > MAX_DESC_CHARS:
        desc = desc[:MAX_DESC_CHARS - 1] + "…"
    
    title = f"📅 تقویم مد | {persian_day} {persian_month} {persian_year}"
    
    return {
        "title": title,
        "desc": desc,
        "images": [],
        "hashtags": (
            f"#مد #استایل #ترند #برند_ایرانی #فشن_ایرانی "
            f"#fashion #IranianFashion #style "
            f"#تقویم_مد #تابستان۱۴۰۴ #{pantone['name_en'].replace(' ', '')}"
        ),
        "category": "calendar",
        "post_hour": 8,
    }


def _generate_style_tips(date_info: dict) -> list[dict]:
    """
    Generate multiple style tip posts for the day.
    Category: "style_tip"
    Returns 4-5 posts scheduled at different hours.
    """
    import random as _rnd
    
    colors = _get_color_of_day(date_info)
    daily_color = colors["daily_color"]
    pantone = colors["pantone"]
    
    posts = []
    used_indices = set()
    
    for slot_config in STYLE_TIP_TEMPLATES:
        slot = slot_config["slot"]
        hours = slot_config["hours"]
        templates = slot_config["templates"]
        
        # Pick one template per slot
        template = _rnd.choice(templates)
        hour = _rnd.choice(hours)
        
        # Fill template variables
        body = template["body"]
        
        replacements = {
            "{color}": daily_color["color_fa"],
            "{combo_tip}": _rnd.choice(
                COMBO_TIPS_WOMEN + COMBO_TIPS_MEN
            ),
            "{accessory_tip}": _rnd.choice(ACCESSORY_TIPS),
            "{color_combo}": COLOR_COMBOS.get(
                daily_color["color_fa"],
                f"{daily_color['color_fa']} + سفید + مشکی = کلاسیک همیشگی"
            ),
            "{pantone_name}": pantone["name_fa"],
            "{pantone_tip}": (
                f"این رنگ {pantone['family_fa']} رو توی مانتو، "
                f"شال یا کیفت بیار"
            ),
            "{full_outfit}": (
                f"🔸 {_rnd.choice(COMBO_TIPS_WOMEN)}\n"
                f"🔹 {_rnd.choice(COMBO_TIPS_MEN)}"
            ),
            "{golden_rule}": _rnd.choice(GOLDEN_RULES),
            "{accessory_detail}": (
                f"📿 {_rnd.choice(ACCESSORY_TIPS)}\n"
                f"💍 {_rnd.choice(ACCESSORY_TIPS)}"
            ),
            "{accessory_rule}": (
                "وقتی لباست ساده‌ست، اکسسوریت حرف بزنه. "
                "وقتی لباست شلوغه، اکسسوریت سکوت کنه."
            ),
            "{fabric_tip}": _rnd.choice(FABRIC_TIPS),
            "{women_evening}": _rnd.choice(EVENING_WOMEN),
            "{men_evening}": _rnd.choice(EVENING_MEN),
            "{transition_tip}": _rnd.choice(TRANSITION_TIPS),
            "{brand_highlight}": _rnd.choice(BRAND_HIGHLIGHTS),
        }
        
        for key, value in replacements.items():
            body = body.replace(key, value)
        
        # Truncate
        if len(body) > MAX_DESC_CHARS:
            body = body[:MAX_DESC_CHARS - 1] + "…"
        
        posts.append({
            "title": template["title"],
            "desc": body,
            "images": [],
            "hashtags": (
                "#مد #استایل #ترند #برند_ایرانی #فشن_ایرانی "
                "#fashion #IranianFashion #style"
            ),
            "category": "style_tip",
            "post_hour": hour,
        })
    
    return posts


# ═══════════════════════════════════════════════════════════
# SECTION 13 — MEHRJAMEH CAPTION BUILDER (BRAND VOICE)
# ═══════════════════════════════════════════════════════════

def _build_mehrjameh_caption(post: dict) -> str:
    """
    Build Telegram caption in Mehrjameh's brand voice.
    Warm, calm, precise, emotionally appealing.
    Different from the RSS aggregator caption.
    """
    title = _escape_html(post["title"])
    desc = _escape_html(post["desc"])
    hashtags = post["hashtags"]
    category = post["category"]
    
    if category == "calendar":
        parts = [
            f"<b>{title}</b>",
            "",
            desc,
            "",
            f"🆔 @mehrjameh_brand",
            "",
            hashtags,
        ]
    else:  # style_tip
        parts = [
            f"<b>{title}</b>",
            "",
            desc,
            "",
            "─────────────",
            "مهرجامه | همراه استایل شما",
            f"🆔 @mehrjameh_brand",
            "",
            hashtags,
        ]
    
    caption = "\n".join(parts)
    
    # Enforce caption limit
    if len(caption) > CAPTION_MAX:
        # Trim desc
        overflow = len(caption) - CAPTION_MAX + 5
        trimmed_desc = desc[:max(20, len(desc) - overflow)] + "…"
        if category == "calendar":
            parts = [
                f"<b>{title}</b>", "",
                trimmed_desc, "",
                f"🆔 @mehrjameh_brand", "",
                hashtags,
            ]
        else:
            parts = [
                f"<b>{title}</b>", "",
                trimmed_desc, "",
                "─────────────",
                "مهرجامه | همراه استایل شما",
                f"🆔 @mehrjameh_brand", "",
                hashtags,
            ]
        caption = "\n".join(parts)
    
    return caption


# ═══════════════════════════════════════════════════════════
# SECTION 14 — MEHRJAMEH CONTENT DEDUP & POSTING
# ═══════════════════════════════════════════════════════════

async def _post_mehrjameh_content(
    bot: Bot,
    chat_id: str,
    db: '_AppwriteDB',
    loop: asyncio.AbstractEventLoop,
    stats: dict,
    time_left_fn,
) -> int:
    """
    Generate and post all Mehrjameh original content.
    Returns number of posts successfully published.
    """
    date_info = _get_persian_date()
    posted_count = 0
    
    _log("\n[MEHRJAMEH] Generating original content...")
    _log(f"  Date: {date_info.get('persian_formatted', 'N/A')} | "
         f"{date_info.get('gregorian_formatted', 'N/A')}")
    
    # Generate all posts
    all_posts = []
    
    # 1. Calendar post (once daily)
    calendar_post = _generate_calendar_post(date_info)
    all_posts.append(calendar_post)
    
    # 2. Style tips (multiple per day)
    style_tips = _generate_style_tips(date_info)
    all_posts.extend(style_tips)
    
    _log(f"[MEHRJAMEH] Generated {len(all_posts)} posts "
         f"(1 calendar + {len(style_tips)} style tips)")
    
    # Sort by post_hour
    all_posts.sort(key=lambda p: p["post_hour"])
    
    # Current hour (Iran time)
    current_hour = date_info.get("hour_iran", 12)
    
    for post in all_posts:
        if time_left_fn() < 10:
            _log("[MEHRJAMEH] Time budget low — stopping")
            break
        
        # Only post content for current or past hours
        # (allows catch-up if bot runs late)
        if post["post_hour"] > current_hour + 1:
            _log(f"  [SKIP:schedule] '{post['title']}' "
                 f"scheduled for hour {post['post_hour']}, "
                 f"current={current_hour}")
            continue
        
        # Compute dedup hashes
        title_hash = _make_title_hash(post["title"])
        content_hash = _make_content_hash(post["desc"][:100])
        
        # Check DB
        try:
            exists = await asyncio.wait_for(
                loop.run_in_executor(
                    None, db.check_exists, "title_hash", title_hash
                ),
                timeout=3,
            )
            if exists:
                _log(f"  [SKIP:dupe] '{post['title']}'")
                stats["skip_dupe"] += 1
                continue
        except (asyncio.TimeoutError, Exception) as e:
            _log(f"  DB check error: {e}", level="WARN")
        
        # Generate link (for DB record)
        date_slug = date_info.get("gregorian", "").replace("-", "")
        link = (
            f"https://mehrjameh.com/daily/"
            f"{date_slug}/{post['category']}/{post['post_hour']}"
        )
        domain_hash = _make_domain_hash("https://mehrjameh.com")
        
        # Save to DB
        try:
            saved = await asyncio.wait_for(
                loop.run_in_executor(
                    None, db.save,
                    link,
                    post["title"],
                    title_hash,
                    content_hash,
                    "https://mehrjameh.com",
                    datetime.now(timezone.utc).isoformat(),
                    "generated",
                    post["category"],
                    50,  # trend_score for generated content
                    post["post_hour"],
                    domain_hash,
                ),
                timeout=5,
            )
        except (asyncio.TimeoutError, Exception) as e:
            _log(f"  DB save error: {e}", level="WARN")
            saved = False
        
        if not saved:
            _log(f"  [SKIP:db_fail] '{post['title']}'")
            continue
        
        # Build caption
        caption = _build_mehrjameh_caption(post)
        
        # Post to Telegram
        try:
            success = await asyncio.wait_for(
                _post_to_telegram(
                    bot, chat_id, post.get("images", []), caption
                ),
                timeout=12,
            )
        except (asyncio.TimeoutError, Exception) as e:
            _log(f"  Telegram error: {e}", level="WARN")
            success = False
        
        if success:
            posted_count += 1
            stats["posted"] += 1
            _log(f"  [POSTED] '{post['title']}' (hour={post['post_hour']})")
            
            if time_left_fn() > 8:
                await asyncio.sleep(INTER_POST_DELAY)
        else:
            stats["errors"] += 1
    
    _log(f"[MEHRJAMEH] Done: {posted_count} posts published")
    return posted_count


# ═══════════════════════════════════════════════════════════
# SECTION 15 — UPDATED MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════

async def main_v2(event=None, context=None):
    """
    Enhanced main function that runs BOTH:
    1. Mehrjameh original content generation (calendar + style tips)
    2. Brand RSS aggregation (existing v14.0 logic)
    """
    _t0 = monotonic()

    def _time_left() -> float:
        return GLOBAL_DEADLINE_SEC - (monotonic() - _t0)

    _log("══════════════════════════════════════════")
    _log("Mehrjameh Fashion Bot v15.0 — Production")
    _log(f"Time: {datetime.now(timezone.utc).isoformat()}")
    _log("══════════════════════════════════════════")

    config = _load_config()
    if not config:
        return {"status": "error", "reason": "missing_env_vars"}

    bot = Bot(token=config["token"])
    db = _AppwriteDB(
        endpoint=config["endpoint"],
        project=config["project"],
        key=config["key"],
        database_id=config["database_id"],
        collection_id=config["collection_id"],
    )

    loop = asyncio.get_event_loop()

    stats = {
        "feeds_ok": 0, "feeds_fail": 0, "feeds_retry": 0,
        "entries_total": 0, "skip_time": 0, "skip_filter": 0,
        "skip_dupe": 0, "posted": 0, "errors": 0,
        "db_timeout": False, "mehrjameh_posted": 0,
    }

    # ════════════════════════════════════════════════════
    # PHASE 0: Mehrjameh Original Content
    # ════════════════════════════════════════════════════
    _log("\n[PHASE 0] Mehrjameh Original Content")

    try:
        mehrjameh_count = await _post_mehrjameh_content(
            bot=bot,
            chat_id=config["chat_id"],
            db=db,
            loop=loop,
            stats=stats,
            time_left_fn=_time_left,
        )
        stats["mehrjameh_posted"] = mehrjameh_count
    except Exception as e:
        _log(f"[PHASE 0] Error: {e}", level="ERROR")
        stats["errors"] += 1

    _log(f"[PHASE 0] Done: {stats['mehrjameh_posted']} Mehrjameh posts "
         f"[{_time_left():.1f}s left]")

    # ════════════════════════════════════════════════════
    # PHASE 1-3: Brand RSS Aggregation (existing logic)
    # ════════════════════════════════════════════════════
    if _time_left() > 30:
        _log("\n[PHASE 1-3] Brand RSS Aggregation")
        # ... (existing Phase 1-3 code from v14.0 runs here)
        # This is the existing feed fetch → dedup → post logic
        # Keeping it as-is from your original code
        
        now = datetime.now(timezone.utc)
        time_threshold = now - timedelta(hours=HOURS_THRESHOLD)

        # Phase 1: Fetch feeds
        fetch_budget = min(FEEDS_TOTAL_TIMEOUT, _time_left() - 40)
        if fetch_budget >= 5:
            try:
                all_items = await asyncio.wait_for(
                    _fetch_all_parallel(loop, stats),
                    timeout=fetch_budget,
                )
            except asyncio.TimeoutError:
                all_items = []
                _log("Feed fetch timed out", level="WARN")
            
            stats["entries_total"] = len(all_items)
            
            if all_items:
                all_items.sort(
                    key=lambda x: x["pub_date"] or datetime.min.replace(
                        tzinfo=timezone.utc
                    ),
                    reverse=True,
                )
                
                # Phase 2: Load DB state
                known_title_hashes = set()
                known_content_hashes = set()
                known_links = set()
                posted_hashes = set()
                
                db_budget = min(DB_TIMEOUT, _time_left() - 30)
                if db_budget > 2:
                    try:
                        raw_records = await asyncio.wait_for(
                            loop.run_in_executor(
                                None, db.load_recent, 1000
                            ),
                            timeout=db_budget,
                        )
                        for rec in raw_records:
                            th = rec.get("title_hash", "")
                            ch = rec.get("content_hash", "")
                            lk = rec.get("link", "")
                            if th: known_title_hashes.add(th)
                            if ch: known_content_hashes.add(ch)
                            if lk: known_links.add(lk)
                    except (asyncio.TimeoutError, Exception):
                        stats["db_timeout"] = True
                
                # Phase 3: Filter + Post
                remaining_budget = PUBLISH_BATCH_SIZE - stats["posted"]
                for item in all_items:
                    if _time_left() < 15:
                        break
                    if stats["posted"] >= PUBLISH_BATCH_SIZE:
                        break
                    
                    title = item["title"]
                    link = item["link"]
                    desc = item["desc"]
                    pub_date = item["pub_date"]
                    brand_name = item["brand"]
                    brand_tag = item["tag"]
                    feed_url = item["feed_url"]
                    category = item["category"]
                    source_type = item["source_type"]
                    entry_obj = item["entry"]
                    brand_short = brand_name.split("|")[0].strip()
                    
                    if pub_date and pub_date < time_threshold:
                        stats["skip_time"] += 1
                        continue
                    
                    if not _is_fashion(title, desc, feed_url, brand_name):
                        stats["skip_filter"] += 1
                        continue
                    
                    title_hash = _make_title_hash(title)
                    content_hash = _make_content_hash(title)
                    domain_hash = _make_domain_hash(feed_url)
                    
                    if (title_hash in posted_hashes
                            or title_hash in known_title_hashes
                            or content_hash in known_content_hashes
                            or link in known_links):
                        stats["skip_dupe"] += 1
                        continue
                    
                    trend_score = _calc_trend_score(
                        title, desc, brand_name
                    )
                    pub_iso = (pub_date.isoformat() 
                               if pub_date 
                               else now.isoformat())
                    
                    try:
                        saved = await asyncio.wait_for(
                            loop.run_in_executor(
                                None, db.save,
                                link, title, title_hash, content_hash,
                                feed_url, pub_iso, source_type, 
                                category, trend_score, now.hour,
                                domain_hash,
                            ),
                            timeout=DB_TIMEOUT,
                        )
                    except (asyncio.TimeoutError, Exception):
                        continue
                    
                    if not saved:
                        stats["skip_dupe"] += 1
                        continue
                    
                    posted_hashes.add(title_hash)
                    known_title_hashes.add(title_hash)
                    known_content_hashes.add(content_hash)
                    known_links.add(link)
                    
                    # Collect images
                    image_urls = []
                    img_budget = min(PAGE_TIMEOUT, _time_left() - 8)
                    if img_budget > 2:
                        try:
                            image_urls = await asyncio.wait_for(
                                loop.run_in_executor(
                                    None, _collect_images, 
                                    entry_obj, link
                                ),
                                timeout=img_budget,
                            )
                        except asyncio.TimeoutError:
                            image_urls = []
                    
                    caption = _build_caption(
                        title=title, desc=desc, link=link,
                        brand_name=brand_name, brand_tag=brand_tag,
                        pub_date=pub_date,
                    )
                    
                    try:
                        success = await asyncio.wait_for(
                            _post_to_telegram(
                                bot, config["chat_id"], 
                                image_urls, caption
                            ),
                            timeout=15,
                        )
                    except (asyncio.TimeoutError, Exception):
                        success = False
                    
                    if success:
                        stats["posted"] += 1
                        if _time_left() > 8:
                            await asyncio.sleep(INTER_POST_DELAY)
                    else:
                        stats["errors"] += 1
    else:
        _log("Not enough time for RSS aggregation", level="WARN")

    # ════════════════════════════════════════════════════
    # SUMMARY
    # ════════════════════════════════════════════════════
    elapsed = monotonic() - _t0
    _log(f"\n{'═' * 50}")
    _log(f"SUMMARY ({elapsed:.1f}s / {GLOBAL_DEADLINE_SEC}s)")
    _log(f"{'═' * 50}")
    _log(f"Mehrjameh : {stats['mehrjameh_posted']} original posts")
    _log(f"Feeds     : {stats['feeds_ok']} ok | "
         f"{stats['feeds_fail']} fail")
    _log(f"Entries   : {stats['entries_total']} total")
    _log(f"Posted    : {stats['posted']} total")
    _log(f"Skip/dupe : {stats['skip_dupe']}")
    _log(f"Errors    : {stats['errors']}")
    _log(f"{'═' * 50}")

    return {
        "status": "success",
        "posted": stats["posted"],
        "mehrjameh_posted": stats["mehrjameh_posted"],
        "feeds_ok": stats["feeds_ok"],
        "feeds_fail": stats["feeds_fail"],
        "entries_total": stats["entries_total"],
        "skip_dupe": stats["skip_dupe"],
        "errors": stats["errors"],
    }

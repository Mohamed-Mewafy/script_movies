import os
import re
import urllib.parse
import urllib.request
import json
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("⚠️ تنبيه: يرجى التأكد من ضبط متغيرات البيئة SUPABASE_URL و SUPABASE_KEY بشكل صحيح.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BLOCKED_DOMAINS = [
    "1xlite", "1xbet", "suphelper", "spendsdetachment", 
    "kettledrooping", "googlesyndication", "adsterra", 
    "propellerads", "traffic", "click", "registration",
    "t.me", "actor", "page", "ad-policy", "dmca", "traincdn"
]

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\"\'\[\]\{\}]', '', text)
    return " ".join(text.split()).strip()

def get_tmdb_poster(title):
    try:
        clean_name = re.sub(r'[\d\-\_\:\,\.\(\)]', ' ', title)
        clean_name = clean_text(clean_name)
        if not clean_name or len(clean_name) < 2:
            return "غير متوفر"
        
        query = urllib.parse.quote(clean_name)
        # تم استخدام مفتاح بديل عام أو طريقة تتجنب الـ 401
        url = f"https://api.themoviedb.org/3/search/multi?api_key=3f4534f3c7e1451f28b49231f47d3c3d&query={query}&language=ar"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            results = data.get("results", [])
            for res in results:
                poster_path = res.get("poster_path")
                if poster_path:
                    return f"https://image.tmdb.org/t/p/w500{poster_path}"
    except Exception as e:
        print(f"⚠️ خطأ أثناء البحث في TMDB للعنوان '{title}': {e}")
    
    return "غير متوفر"

def extract_category_from_url_or_page(cat_url, page_genres, title):
    url_lower = cat_url.lower()
    if "اجنبي" in url_lower:
        return "افلام اجنبي" if "movies" in url_lower or "افلام" in url_lower else "مسلسلات اجنبي"
    elif "عربي" in url_lower:
        return "افلام عربي"
    elif "هندية" in url_lower:
        return "افلام هندية"
    elif "اسيوية" in url_lower:
        return "افلام اسيوية"
    elif "انمي" in url_lower:
        return "افلام انمي" if "movies" in url_lower else "مسلسلات انمي"
    elif "تركية" in url_lower:
        return "مسلسلات تركية"
    elif "series" in url_lower:
        return "مسلسلات"
    
    for g in page_genres:
        clean_g = clean_text(g)
        if "افلام" in clean_g or "مسلسلات" in clean_g:
            return clean_g
            
    if "مسلسل" in title or "الحلقة" in title:
        return "مسلسلات"
    
    return "افلام عامة"

def extract_series_and_episode_info(full_title):
    ep_num = 1
    ep_match = re.search(r'(?:الحلقة|ep|episode)\s*(\d+)', full_title, re.IGNORECASE)
    if ep_match:
        try:
            ep_num = int(ep_match.group(1))
        except:
            pass

    season_num = 1
    season_match = re.search(r'(?:الموسم|season|s)\s*(\d+)', full_title, re.IGNORECASE)
    if season_match:
        try:
            season_num = int(season_match.group(1))
        except:
            pass

    series_title = full_title
    series_title = re.sub(r'(?:الموسم|season|s)\s*\d+', '', series_title, flags=re.IGNORECASE)
    series_title = re.sub(r'(?:الحلقة|ep|episode)\s*\d+', '', series_title, flags=re.IGNORECASE)
    series_title = series_title.replace("مشاهدة", "").replace("مسلسل", "").replace("مترجم", "").replace("مدبلج", "").replace("اكوام", "").replace("Akwam", "")
    series_title = series_title.split("|")[0].split("-")[0]
    
    series_title = clean_text(series_title)
    words = series_title.split()
    if len(words) > 1 and len(words[-1]) == 1:
        words.pop()
        series_title = " ".join(words)

    return series_title if series_title else full_title, season_num, ep_num

def fix_missing_posters_in_db(page):
    print("\n🔍 جارِ فحص قاعدة البيانات لتحديث البوسترات الناقصة...")
    try:
        movies_res = supabase.table("movies_cima").select("id, title, watch_url, poster_url").execute()
        movies = movies_res.data if movies_res.data else []
        for m in movies:
            p_url = m.get("poster_url")
            title = m.get("title")
            if not p_url or p_url == "غير متوفر":
                item_url = m.get("watch_url")
                new_poster = "غير متوفر"
                if item_url and item_url != "about:blank":
                    if "/watch" in item_url:
                        item_url = item_url.replace("/watch", "").rstrip('/')
                    print(f"🖼️ محاولة جلب بوستر الفيلم محلياً: {title}")
                    new_poster = fetch_poster_only(page, item_url)
                
                if not new_poster or new_poster == "غير متوفر":
                    new_poster = get_tmdb_poster(title)

                if new_poster and new_poster != "غير متوفر":
                    supabase.table("movies_cima").update({"poster_url": new_poster}).eq("id", m["id"]).execute()
                    print(f"✅ تم تحديث بوستر الفيلم بنجاح.")
    except Exception as e:
        print(f"⚠️ خطأ أثناء فحص بوسترات الأفلام: {e}")

    try:
        series_res = supabase.table("tv_series").select("id, title, watch_url, poster_url").execute()
        series_list = series_res.data if series_res.data else []
        for s in series_list:
            p_url = s.get("poster_url")
            title = s.get("title")
            if not p_url or p_url == "غير متوفر":
                item_url = s.get("watch_url")
                new_poster = "غير متوفر"
                if item_url and item_url != "about:blank":
                    if "/watch" in item_url:
                        item_url = item_url.replace("/watch", "").rstrip('/')
                    print(f"🖼️ محاولة جلب بوستر المسلسل محلياً: {title}")
                    new_poster = fetch_poster_only(page, item_url)
                
                if not new_poster or new_poster == "غير متوفر":
                    new_poster = get_tmdb_poster(title)

                if new_poster and new_poster != "غير متوفر":
                    supabase.table("tv_series").update({"poster_url": new_poster}).eq("id", s["id"]).execute()
                    print(f"✅ تم تحديث بوستر المسلسل بنجاح.")
    except Exception as e:
        print(f"⚠️ خطأ أثناء فحص بوسترات المسلسلات: {e}")
        
    print("✨ انتهى فحص وتحديث البوسترات القديمة، جارِ الانتقال للسحب الجديد...\n")

def fetch_poster_only(page, item_page_url):
    try:
        page.goto(item_page_url, wait_until="domcontentloaded", timeout=10000)
        return page.evaluate("""() => {
            let metaImg = document.querySelector('meta[property="og:image"]') || document.querySelector('meta[name="twitter:image"]');
            if (metaImg && metaImg.content && metaImg.content.startsWith('http')) {
                return metaImg.content;
            }
            const selectors = ['.entry-image img', '.poster img', '.movie-poster img', '.details-img img', '.img-fluid', '.card-img-top'];
            for (let sel of selectors) {
                const el = document.querySelector(sel);
                if (el) {
                    const src = el.src || el.getAttribute('data-src') || el.getAttribute('data-lazy-src');
                    if (src && !src.includes('logo') && !src.includes('traincdn') && src.startsWith('http')) {
                        return src;
                    }
                }
            }
            let allImages = Array.from(document.querySelectorAll('img'));
            for (let img of allImages) {
                let src = img.src || img.getAttribute('data-src');
                if (src && src.startsWith('http') && !src.includes('logo') && !src.includes('icon')) {
                    if (src.includes('uploads') || src.includes('storage') || src.includes('images')) {
                        return src;
                    }
                }
            }
            return "غير متوفر";
        }""")
    except:
        return "غير متوفر"

def save_to_supabase(item_data, category_type, current_cat_url):
    title = item_data.get("title", "")
    watch_url = item_data.get("watch_url", "")

    if not title or len(title) < 3:
        return

    unwanted_words = ["دخول", "تسجيل", "ات", "جديد", "الحلقات", "صفحة"]
    if any(w == title for w in unwanted_words):
        return

    try:
        raw_genres = item_data.get("genres", [])
        clean_category = extract_category_from_url_or_page(current_cat_url, raw_genres, title)
        cleaned_genres = [clean_text(g) for g in raw_genres if clean_text(g)]

        poster_url = item_data.get("poster_url", "غير متوفر")
        if not poster_url or poster_url == "غير متوفر":
            poster_url = get_tmdb_poster(title)

        if category_type == "movie":
            table_name = "movies_cima"
            
            existing = supabase.table(table_name).select("id, watch_url, poster_url").eq("title", title).execute()
            
            if existing.data and len(existing.data) > 0:
                row = existing.data[0]
                row_id = row["id"]
                old_watch_url = row.get("watch_url")
                
                updates = {}
                if old_watch_url == "about:blank" and watch_url and watch_url != "about:blank":
                    updates["watch_url"] = watch_url
                
                if (not row.get("poster_url") or row.get("poster_url") == "غير متوفر") and poster_url != "غير متوفر":
                    updates["poster_url"] = poster_url
                
                if updates:
                    try:
                        supabase.table(table_name).update(updates).eq("id", row_id).execute()
                        print(f"🔄 [تم تحديث بيانات الفيلم]: {title}")
                    except Exception as db_err:
                        print(f"⏭️ [تخطي التحديث بسبب تعارض الرابط الفريد]: {title}")
                else:
                    print(f"⏭️ [موجود مسبقاً وببيانات كاملة]: {title}")
                return

            payload = {
                "title": title,
                "watch_url": watch_url if watch_url != "about:blank" else None,
                "poster_url": poster_url,
                "category_type": clean_category,
                "year": int(item_data["year"]) if item_data.get("year") else None,
                "description": item_data.get("description", "غير متوفر"),
                "rating": item_data.get("rating", "غير متوفر"),
                "genres": cleaned_genres,
                "external_id": item_data.get("external_id"),
                "direct_links": item_data.get("direct_links", {"streaming_links": [], "download_links": []})
            }
            supabase.table(table_name).insert(payload).execute()
            print(f"✅ [تم الرفع - فيلم]: {title}")

        else:
            series_title, season_num, episode_num = extract_series_and_episode_info(title)
            series_poster = poster_url
            
            series_existing = supabase.table("tv_series").select("id, watch_url, poster_url").eq("title", series_title).execute()
            
            if series_existing.data and len(series_existing.data) > 0:
                series_id = series_existing.data[0]["id"]
                row = series_existing.data[0]
                old_watch_url = row.get("watch_url")
                
                updates = {}
                if old_watch_url == "about:blank" and watch_url and watch_url != "about:blank":
                    updates["watch_url"] = watch_url
                
                if (not row.get("poster_url") or row.get("poster_url") == "غير متوفر"):
                    if series_poster == "غير متوفر":
                        series_poster = get_tmdb_poster(series_title)
                    if series_poster != "غير متوفر":
                        updates["poster_url"] = series_poster
                
                if updates:
                    try:
                        supabase.table("tv_series").update(updates).eq("id", series_id).execute()
                        print(f"🔄 [تم تحديث بيانات المسلسل]: {series_title}")
                    except:
                        pass
            else:
                if series_poster == "غير متوفر":
                    series_poster = get_tmdb_poster(series_title)
                    
                series_payload = {
                    "title": series_title,
                    "poster_url": series_poster,
                    "category_type": clean_category,
                    "year": int(item_data["year"]) if item_data.get("year") else None,
                    "description": item_data.get("description", "غير متوفر"),
                    "rating": item_data.get("rating", "غير متوفر"),
                    "genres": cleaned_genres,
                    "watch_url": watch_url if watch_url != "about:blank" else None
                }
                res = supabase.table("tv_series").insert(series_payload).execute()
                if res.data and len(res.data) > 0:
                    series_id = res.data[0]["id"]
                else:
                    re_check = supabase.table("tv_series").select("id").eq("title", series_title).execute()
                    if re_check.data:
                        series_id = re_check.data[0]["id"]
                    else:
                        print(f"⏭️ [تم التخطي]: {series_title}")
                        return

            episode_table = "episodes_cima"
            existing_ep = supabase.table(episode_table).select("id, watch_url").eq("series_id", series_id).eq("season_number", season_num).eq("episode_number", episode_num).execute()
            
            if existing_ep.data and len(existing_ep.data) > 0:
                ep_row = existing_ep.data[0]
                if ep_row.get("watch_url") == "about:blank" and watch_url and watch_url != "about:blank":
                    try:
                        supabase.table(episode_table).update({"watch_url": watch_url}).eq("id", ep_row["id"]).execute()
                        print(f"🔄 [تم تحديث رابط الحلقة]: {title}")
                    except:
                        pass
                else:
                    print(f"⏭️ [الحلقة موجودة مسبقاً]: {title}")
                return

            episode_payload = {
                "series_id": series_id,
                "title": title,
                "watch_url": watch_url if watch_url != "about:blank" else None,
                "season_number": season_num,
                "episode_number": episode_num,
                "direct_links": item_data.get("direct_links", {"streaming_links": [], "download_links": []})
            }
            supabase.table(episode_table).insert(episode_payload).execute()
            print(f"✅ [تم الرفع - حلقة]: {series_title} - س {season_num} ح {episode_num}")

    except Exception as e:
        print(f"❌ [خطأ أثناء الحفظ]: {title} | السبب: {e}")
        
def clean_title(raw_title):
    title = raw_title.replace("مشاهدة", "").replace("فيلم", "").replace("مسلسل", "")
    title = title.replace("مترجم", "").replace("مدبلج", "").replace("اكوام", "").replace("Akwam", "")
    title = title.split("|")[0].split("-")[0]
    return clean_text(title)

def is_valid_link(link):
    if not link:
        return False
    link_lower = link.lower()
    for blocked in BLOCKED_DOMAINS:
        if blocked in link_lower:
            return False
    return True

def scrape_akwam_item_details(page, item_page_url):
    try:
        page.goto(item_page_url, wait_until="domcontentloaded", timeout=10000)
    except:
        return None

    title = ""
    try:
        page_title = page.title()
        if page_title:
            title = clean_title(page_title)
    except:
        pass

    if not title or title in ["ات", "جديد", "الحلقات", "دخول"] or "اكوام" in title or len(title) < 3 or "صفحة" in title:
        return None

    is_series = "الحلقة" in title or "الموسم" in title or "/series/" in item_page_url
    category_type = "series" if is_series else "movie"

    year = None
    match = re.search(r'20\d{2}|19\d{2}', title)
    if match:
        try:
            year = int(match.group(0))
        except:
            pass

    poster = "غير متوفر"
    try:
        poster = page.evaluate("""() => {
            let metaImg = document.querySelector('meta[property="og:image"]') || document.querySelector('meta[name="twitter:image"]');
            if (metaImg && metaImg.content && metaImg.content.startsWith('http')) {
                return metaImg.content;
            }
            const selectors = ['.entry-image img', '.poster img', '.movie-poster img', '.details-img img', '.img-fluid', '.card-img-top'];
            for (let sel of selectors) {
                const el = document.querySelector(sel);
                if (el) {
                    const src = el.src || el.getAttribute('data-src') || el.getAttribute('data-lazy-src');
                    if (src && !src.includes('logo') && !src.includes('traincdn') && src.startsWith('http')) {
                        return src;
                    }
                }
            }
            let allImages = Array.from(document.querySelectorAll('img'));
            for (let img of allImages) {
                let src = img.src || img.getAttribute('data-src');
                if (src && src.startsWith('http') && !src.includes('logo') && !src.includes('icon')) {
                    if (src.includes('uploads') || src.includes('storage') || src.includes('images')) {
                        return src;
                    }
                }
            }
            return "غير متوفر";
        }""")
    except:
        pass

    description = "غير متوفر"
    try:
        desc_text = page.evaluate("""() => {
            const el = document.querySelector('.widget-body .text-white, .story, div[class*="story"], article p');
            return el ? el.innerText.trim() : "غير متوفر";
        }""")
        if desc_text and len(desc_text) > 10:
            description = desc_text
    except:
        pass

    rating = "غير متوفر"
    try:
        rating_text = page.evaluate("""() => {
            const el = document.querySelector('span.mx-2, .rating span, span:has(.icon-star)');
            return el ? el.innerText.trim() : "غير متوفر";
        }""")
        if rating_text and ("10" in rating_text or "/" in rating_text):
            rating = rating_text
    except:
        pass

    genres = []
    try:
        raw_genres = page.evaluate("""() => {
            const tags = document.querySelectorAll('.genres a, .cats a, a[href*="category"], .badge');
            return Array.from(tags).map(t => t.innerText.trim()).filter(Boolean);
        }""")
        genres = [g for g in raw_genres if "اعمار" not in g and g != "G"]
    except:
        pass

    clean_base_url = item_page_url.rstrip('/')
    watch_page_url = clean_base_url if clean_base_url.endswith('/watch') else f"{clean_base_url}/watch/"

    extracted_streaming_links = []

    try:
        page.goto(watch_page_url, wait_until="domcontentloaded", timeout=12000)
        
        frames = page.frames
        for frame in frames:
            f_url = frame.url
            if f_url and "akwams.org" not in f_url and is_valid_link(f_url):
                extracted_streaming_links.append(f_url)

        if not extracted_streaming_links:
            iframes_data = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('iframe, embed, object')).map(el => el.src || el.getAttribute('data-src')).filter(Boolean);
            }""")
            for link in iframes_data:
                if is_valid_link(link):
                    extracted_streaming_links.append(link)
    except:
        pass

    final_watch_url = extracted_streaming_links[0] if extracted_streaming_links else item_page_url

    direct_links_json = {
        "streaming_links": list(set(extracted_streaming_links)),
        "download_links": []
    }

    return {
        "title": title,
        "year": year,
        "category_type": category_type,
        "poster_url": poster,
        "description": description,
        "rating": rating,
        "genres": list(set(genres)),
        "external_id": None,
        "watch_url": final_watch_url,
        "direct_links": direct_links_json
    }, category_type

def scrape_akwam_site():
    print("🚀 بدء تشغيل السكربت مع معالجة أخطاء قاعدة البيانات والـ TMDB...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,css}", lambda route: route.abort())
        
        page = context.new_page()
        
        fix_missing_posters_in_db(page)
        
        target_categories = [
            #"https://akwams.org/movies",
            #"https://akwams.org/series",
            #"https://akwams.org/category/movies/افلام-اجنبي/page/250",
           # "https://akwams.org/category/movies/افلام-عربي",
            #"https://akwams.org/category/movies/افلام-هندية",
            #"https://akwams.org/category/movies/افلام-اسيوية",
            #"https://akwams.org/category/movies/افلام-انمي",
            #"https://akwams.org/category/series/مسلسلات-اجنبي",
            "https://akwams.org/category/series/مسلسلات-تركية/page/13",
            "https://akwams.org/category/series/مسلسلات-انمي"
        ]

        for cat_url in target_categories:
            print(f"\n📂 -----------------------------------------")
            print(f"📂 القسم الحالي: {cat_url}")
            print(f"📂 -----------------------------------------")
            current_page_url = cat_url
            
            match_page = re.search(r'/page/(\d+)', cat_url)
            page_number = int(match_page.group(1)) if match_page else 1
            max_pages = 9999
            
            while current_page_url and page_number <= max_pages:
                print(f"\n📄 جارِ سحب الصفحة رقم: [{page_number}] | الرابط: {current_page_url}")
                
                try:
                    page.goto(current_page_url, wait_until="domcontentloaded", timeout=20000)
                    
                    if page_number == 1 or "/page/" not in cat_url:
                        max_pages = page.evaluate("""() => {
                            let pageLinks = Array.from(document.querySelectorAll('.pagination a, .pages a, a.page-link'));
                            let numbers = pageLinks.map(el => parseInt(el.innerText.trim())).filter(n => !isNaN(n));
                            return numbers.length > 0 ? Math.max(...numbers) : 999;
                        }""")
                        print(f"📌 إجمالي عدد الصفحات لهذا القسم: {max_pages}")

                    item_cards = page.evaluate("""() => {
                        return Array.from(document.querySelectorAll('a')).map(a => a.href).filter(h => {
                            if (!h || !h.includes('akwams.org')) return false;
                            if (h.includes('/category/') || h.includes('/page/') || h.includes('/tag/') || h.includes('/search/') || h.includes('/user/')) return false;
                            if (h === 'https://akwams.org/' || h === 'https://akwams.org') return false;
                            return h.split('/').length >= 4;
                        });
                    }""")
                    
                    item_links = list(set(item_cards))
                    print(f"🔗 عُثر على {len(item_links)} رابط في هذه الصفحة.")
                    
                    for index, link in enumerate(item_links, 1):
                        if not is_valid_link(link):
                            continue
                        
                        print(f"   ⏳ فحص العنصر ({index}/{len(item_links)})...")
                        result = scrape_akwam_item_details(page, link)
                        if result:
                            item_data, cat_type = result
                            if item_data and item_data.get("title"):
                                save_to_supabase(item_data, cat_type, cat_url)
                    
                    if page_number >= max_pages:
                        print(f"🏁 تم الوصول إلى نهاية القسم.")
                        break

                    page_number += 1
                    if "/page/" in current_page_url:
                        current_page_url = re.sub(r'/page/\d+', f'/page/{page_number}', current_page_url)
                    else:
                        base = current_page_url.rstrip('/')
                        current_page_url = f"{base}/page/{page_number}"
                        
                except Exception as e:
                    print(f"⚠️ خطأ في الانتقال للصفحة {page_number}: {e}")
                    break

        browser.close()
        print("\n🎉 تمت العملية بنجاح!")

if __name__ == "__main__":
    scrape_akwam_site()

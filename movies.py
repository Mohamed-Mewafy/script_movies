import os
import re
import time
import urllib.parse
import urllib.request
import json
import requests
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SHRINKME_API_TOKEN = os.environ.get("SHRINKME_API_TOKEN")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("تنبيه: يرجى التأكد من ضبط متغيرات البيئة SUPABASE_URL و SUPABASE_KEY بشكل صحيح.")

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

def shorten_link_via_shrinkme(original_url):
    if not original_url or not is_valid_link(original_url):
        return original_url

    if "shrinkme.io" in original_url or "shrinkme.click" in original_url:
        return original_url

    try:
        encoded_url = urllib.parse.quote(original_url)
        api_url = f"https://shrinkme.io/api?api={SHRINKME_API_TOKEN}&url={encoded_url}"
        
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success" and data.get("shortenedUrl"):
                return data.get("shortenedUrl")
    except Exception:
        pass
    
    return original_url

def get_tmdb_poster(title):
    try:
        clean_name = re.sub(r'[\d\-\_\:\,\.\(\)]', ' ', title)
        clean_name = clean_text(clean_name)
        if not clean_name or len(clean_name) < 2:
            return "غير متوفر"
        
        query = urllib.parse.quote(clean_name)
        url = f"https://api.themoviedb.org/3/search/multi?api_key=3f4534f3c7e1451f28b49231f47d3c3d&query={query}&language=ar"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            results = data.get("results", [])
            for res in results:
                poster_path = res.get("poster_path")
                if poster_path:
                    return f"https://image.tmdb.org/t/p/w500{poster_path}"
    except Exception:
        pass
    
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
        except Exception:
            pass

    season_num = 1
    season_match = re.search(r'(?:الموسم|season|s)\s*(\d+)', full_title, re.IGNORECASE)
    if season_match:
        try:
            season_num = int(season_match.group(1))
        except Exception:
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

def fetch_download_links_only(page, item_page_url, max_retries=2):
    raw_download_links = []
    clean_base_url = item_page_url.rstrip('/')
    
    if clean_base_url.endswith('/watch'):
        download_page_url = clean_base_url.replace('/watch', '/download')
    elif clean_base_url.endswith('/download'):
        download_page_url = clean_base_url
    else:
        download_page_url = f"{clean_base_url}/download"

    for attempt in range(max_retries):
        try:
            page.goto(download_page_url, wait_until="domcontentloaded", timeout=20000)
            try:
                page.wait_for_selector('a[href*="download"], a[href*="/link/"], .btn-download, a.download-link', timeout=5000)
            except Exception:
                pass

            links = page.evaluate("""() => {
                const downloadElements = Array.from(document.querySelectorAll(`
                    a[href*="download"], 
                    a[href*="/link/"], 
                    a[href*="niramirus"], 
                    a[href*="file"], 
                    a.link-download, 
                    a.btn-download, 
                    a.download-link, 
                    .download-link a, 
                    .buttons-list a,
                    a.btn,
                    a[class*="download"]
                `));
                return downloadElements.map(el => el.href).filter(Boolean);
            }""")

            for link in links:
                if is_valid_link(link) and link != download_page_url and link not in raw_download_links:
                    raw_download_links.append(link)

            for frame in page.frames:
                f_url = frame.url
                if f_url and "akwams.org" not in f_url and is_valid_link(f_url):
                    if f_url not in raw_download_links:
                        raw_download_links.append(f_url)

            if raw_download_links:
                break
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"تعذر زيارة صفحة التحميل ({download_page_url}): {e}")
            time.sleep(1)

    shortened_download_links = []
    for raw_link in raw_download_links:
        short_link = shorten_link_via_shrinkme(raw_link)
        shortened_download_links.append(short_link)

    return shortened_download_links

def scrape_akwam_item_details(page, item_page_url):
    try:
        page.goto(item_page_url, wait_until="domcontentloaded", timeout=15000)
    except Exception:
        return None

    title = ""
    try:
        page_title = page.title()
        if page_title:
            title = clean_title(page_title)
    except Exception:
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
        except Exception:
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
            return "غير متوفر";
        }""")
    except Exception:
        pass

    description = "غير متوفر"
    try:
        desc_text = page.evaluate("""() => {
            const el = document.querySelector('.widget-body .text-white, .story, div[class*="story"], article p');
            return el ? el.innerText.trim() : "غير متوفر";
        }""")
        if desc_text and len(desc_text) > 10:
            description = desc_text
    except Exception:
        pass

    rating = "غير متوفر"
    try:
        rating_text = page.evaluate("""() => {
            const el = document.querySelector('span.mx-2, .rating span, span:has(.icon-star)');
            return el ? el.innerText.trim() : "غير متوفر";
        }""")
        if rating_text and ("10" in rating_text or "/" in rating_text):
            rating = rating_text
    except Exception:
        pass

    genres = []
    try:
        raw_genres = page.evaluate("""() => {
            const tags = document.querySelectorAll('.genres a, .cats a, a[href*="category"], .badge');
            return Array.from(tags).map(t => t.innerText.trim()).filter(Boolean);
        }""")
        genres = [g for g in raw_genres if "اعمار" not in g and g != "G"]
    except Exception:
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
    except Exception:
        pass

    final_watch_url = extracted_streaming_links[0] if extracted_streaming_links else item_page_url
    extracted_download_links = fetch_download_links_only(page, item_page_url)

    direct_links_json = {
        "streaming_links": list(set(extracted_streaming_links)),
        "download_links": list(set(extracted_download_links))
    }

    return {
        "title": title,
        "year": year,
        "category_type": category_type,
        "poster_url": poster,
        "description": description,
        "rating": rating,
        "genres": list(set(genres)),
        "watch_url": final_watch_url,
        "direct_links": direct_links_json
    }, category_type

def save_or_update_download_links(page, item_data, category_type, current_cat_url, item_page_url):
    title = item_data.get("title", "")
    if not title or len(title) < 3:
        return

    unwanted_words = ["دخول", "تسجيل", "ات", "جديد", "الحلقات", "صفحة"]
    if any(w == title for w in unwanted_words):
        return

    if category_type == "movie":
        existing_movie = supabase.table("movies_cima").select("id, direct_links").eq("title", title).execute()
        if existing_movie.data:
            row = existing_movie.data[0]
            movie_id = row.get("id")
            direct_links = row.get("direct_links") or {}
            if isinstance(direct_links, dict):
                download_links = direct_links.get("download_links", [])
                if not download_links:
                    new_download_links = fetch_download_links_only(page, item_page_url)
                    if new_download_links:
                        direct_links["download_links"] = list(set(new_download_links))
                        supabase.table("movies_cima").update({"direct_links": direct_links}).eq("id", movie_id).execute()
                        print(f"🔄 تم تحديث روابط الفيلم: {title}")
            return

        raw_genres = item_data.get("genres", [])
        clean_category = extract_category_from_url_or_page(current_cat_url, raw_genres, title)
        cleaned_genres = [clean_text(g) for g in raw_genres if clean_text(g)]
        poster_url = item_data.get("poster_url", "غير متوفر")
        if not poster_url or poster_url == "غير متوفر":
            poster_url = get_tmdb_poster(title)

        formatted_movie = {
            "title": title,
            "category_type": clean_category,
            "year": int(item_data["year"]) if item_data.get("year") else None,
            "poster_url": poster_url,
            "description": item_data.get("description", "غير متوفر"),
            "rating": item_data.get("rating", "غير متوفر"),
            "genres": cleaned_genres,
            "watch_url": item_data.get("watch_url"),
            "direct_links": item_data.get("direct_links", {"streaming_links": [], "download_links": []})
        }
        supabase.table("movies_cima").upsert(formatted_movie, on_conflict="title").execute()
        print(f"📥 تم حفظ فيلم جديد: {title}")
    else:
        series_title, season_num, episode_num = extract_series_and_episode_info(title)
        raw_genres = item_data.get("genres", [])
        clean_category = extract_category_from_url_or_page(current_cat_url, raw_genres, title)
        cleaned_genres = [clean_text(g) for g in raw_genres if clean_text(g)]

        existing_series = supabase.table("tv_series").select("id").eq("title", series_title).execute()
        if existing_series.data:
            series_id = existing_series.data[0]["id"]
        else:
            poster_url = item_data.get("poster_url", "غير متوفر")
            if poster_url == "غير متوفر":
                poster_url = get_tmdb_poster(series_title)

            series_data = {
                "title": series_title,
                "category_type": clean_category,
                "year": int(item_data["year"]) if item_data.get("year") else None,
                "poster_url": poster_url,
                "description": item_data.get("description", "غير متوفر"),
                "rating": item_data.get("rating", "غير متوفر"),
                "genres": cleaned_genres
            }
            res = supabase.table("tv_series").upsert(series_data, on_conflict="title").execute()
            series_id = res.data[0]["id"]
            print(f"📥 تم حفظ مسلسل جديد: {series_title}")

        existing_episode = supabase.table("episodes_cima").select("id, direct_links").eq("series_id", series_id).eq("season_number", season_num).eq("episode_number", episode_num).execute()

        if existing_episode.data:
            row = existing_episode.data[0]
            ep_id = row.get("id")
            direct_links = row.get("direct_links") or {}
            if isinstance(direct_links, dict):
                download_links = direct_links.get("download_links", [])
                if not download_links:
                    new_download_links = fetch_download_links_only(page, item_page_url)
                    if new_download_links:
                        direct_links["download_links"] = list(set(new_download_links))
                        supabase.table("episodes_cima").update({"direct_links": direct_links}).eq("id", ep_id).execute()
                        print(f"🔄 تم تحديث روابط الحلقة: {title}")
            return

        formatted_episode = {
            "series_id": series_id,
            "title": title,
            "season_number": season_num,
            "episode_number": ep_num,
            "watch_url": item_data.get("watch_url"),
            "direct_links": item_data.get("direct_links", {"streaming_links": [], "download_links": []})
        }
        supabase.table("episodes_cima").insert(formatted_episode).execute()
        print(f"📥 تم حفظ حلقة جديدة: {title}")

def scrape_akwam_site():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,css}", lambda route: route.abort())
        page = context.new_page()
        
        target_categories = [
            "https://akwams.org/movies",
            "https://akwams.org/series",
            "https://akwams.org/category/movies/افلام-اجنبي/page/250",
            "https://akwams.org/category/movies/افلام-عربي",
            "https://akwams.org/category/movies/افلام-هندية",
            "https://akwams.org/category/movies/افلام-اسيوية",
            "https://akwams.org/category/movies/افلام-انمي",
            "https://akwams.org/category/series/مسلسلات-اجنبي",
            "https://akwams.org/category/series/مسلسلات-تركية/page/13",
            "https://akwams.org/category/series/مسلسلات-انمي"
        ]

        for cat_url in target_categories:
            current_page_url = cat_url
            match_page = re.search(r'/page/(\d+)', cat_url)
            page_number = int(match_page.group(1)) if match_page else 1
            max_pages = 9999
            
            print(f"\n🌐 جاري البدء في القسم: {cat_url}")
            
            while current_page_url and page_number <= max_pages:
                try:
                    print(f"📄 تصفح الصفحة رقم {page_number}: {current_page_url}")
                    page.goto(current_page_url, wait_until="domcontentloaded", timeout=20000)
                    if page_number == 1 or "/page/" not in cat_url:
                        max_pages = page.evaluate("""() => {
                            let pageLinks = Array.from(document.querySelectorAll('.pagination a, .pages a, a.page-link'));
                            let numbers = pageLinks.map(el => parseInt(el.innerText.trim())).filter(n => !isNaN(n));
                            return numbers.length > 0 ? Math.max(...numbers) : 999;
                        }""")

                    item_cards = page.evaluate("""() => {
                        return Array.from(document.querySelectorAll('a')).map(a => a.href).filter(h => {
                            if (!h || !h.includes('akwams.org')) return false;
                            if (h.includes('/category/') || h.includes('/page/') || h.includes('/tag/') || h.includes('/search/') || h.includes('/user/')) return false;
                            if (h === 'https://akwams.org/' || h === 'https://akwams.org') return false;
                            return h.split('/').length >= 4;
                        });
                    }""")
                    
                    item_links = list(set(item_cards))
                    print(f"🔍 تم العثور على {len(item_links)} عنصر في هذه الصفحة.")
                    
                    for index, link in enumerate(item_links, 1):
                        if not is_valid_link(link):
                            continue
                        
                        print(f"⏳ معالجة العنصر ({index}/{len(item_links)}): {link}")
                        result = scrape_akwam_item_details(page, link)
                        if result:
                            item_data, cat_type = result
                            if item_data and item_data.get("title"):
                                save_or_update_download_links(page, item_data, cat_type, cat_url, link)
                    
                    if page_number >= max_pages:
                        break

                    page_number += 1
                    if "/page/" in current_page_url:
                        current_page_url = re.sub(r'/page/\d+', f'/page/{page_number}', current_page_url)
                    else:
                        base = current_page_url.rstrip('/')
                        current_page_url = f"{base}/page/{page_number}"
                except Exception as e:
                    print(f"⚠️ خطأ أثناء تصفح الصفحة: {e}")
                    break

        browser.close()
        print("✅ تم الانتهاء من السحب بنجاح!")

if __name__ == "__main__":
    scrape_akwam_site()

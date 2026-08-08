import os
import re
import time
import urllib.parse
import urllib.request
import json
import requests
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

# ==========================================
# الإعدادات ومفاتيح البيئة
# ==========================================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SHRINKME_API_TOKEN = os.environ.get("SHRINKME_API_TOKEN")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "3f4534f3c7e1451f28b49231f47d3c3d")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("⚠️ يرجى التأكد من ضبط متغيرات البيئة SUPABASE_URL و SUPABASE_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================
# الدوال المساعدة
# ==========================================
def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\"\'\[\]\{\}]', '', text)
    return " ".join(text.split()).strip()

def normalize_movie_title(raw_title):
    name = re.sub(r'^(مشاهدة|تحميل|فيلم)?\s*', '', raw_title).strip()
    clean_name = re.sub(r'\s*(-|\||مترجم|مدبلج|اكوام|Akwam|اونلاين|بجودة|HD|4K|1080p|720p).*', '', name, flags=re.IGNORECASE).strip()
    clean_name = clean_text(clean_name)
    
    invalid_names = ["جديد", "حصريا", "فيلم"]
    if not clean_name or clean_name in invalid_names or len(clean_name) < 2:
        return None
    return clean_name

def shorten_link_via_shrinkme(original_url):
    if not original_url or not SHRINKME_API_TOKEN:
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
    except Exception as e:
        print(f"    ⚠️ خطأ في اختصار الرابط: {e}")
    return original_url

def get_tmdb_poster(title):
    try:
        clean_name = re.sub(r'[\d\-\_\:\,\.\(\)]', ' ', title)
        clean_name = clean_text(clean_name)
        if not clean_name or len(clean_name) < 2:
            return "غير متوفر"
        query = urllib.parse.quote(clean_name)
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}&language=ar"
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

def extract_media_links(page):
    download_links = []
    streaming_links = []
    
    # 1. استخراج روابط التحميل
    try:
        raw_links = page.evaluate("""() => {
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            return anchors.map(a => a.href).filter(h => {
                if (!h) return false;
                return h.includes('download') || h.includes('link') || h.includes('file') || h.includes('niramirus') || h.includes('direct');
            });
        }""")
        for link in raw_links:
            if link and link not in download_links and not link.startswith("chrome-error://"):
                download_links.append(link)
    except Exception as e:
        print(f"    ⚠️ خطأ أثناء قراءة روابط التحميل: {e}")

    # 2. استخراج سيرفرات المشاهدة
    try:
        server_buttons = page.locator('button:has-text("سيرفر"), a:has-text("سيرفر"), .servers-list button, div[class*="server"] button').all()
        for btn in server_buttons[:5]:
            try:
                if btn.is_visible():
                    btn.click(timeout=2000)
                    time.sleep(1)
                    frame_url = page.evaluate("() => document.querySelector('iframe')?.src")
                    if frame_url and frame_url not in streaming_links and "akwams" not in frame_url and "about:blank" not in frame_url:
                        streaming_links.append(frame_url)
            except Exception:
                pass
    except Exception as e:
        print(f"    ⚠️ خطأ أثناء فحص سيرفرات المشاهدة: {e}")

    shortened_downloads = [shorten_link_via_shrinkme(l) for l in download_links if l]
    return list(set(streaming_links)), shortened_downloads

# ==========================================
# معالجة صفحة الفيلم
# ==========================================
def process_movie(page, movie_page_url, cat_type):
    try:
        res = page.goto(movie_page_url, wait_until="domcontentloaded", timeout=20000)
        if res and res.status == 404:
            return
    except Exception as e:
        print(f"⚠️ تعذر فتح الرابط {movie_page_url}: {e}")
        return

    title = ""
    try:
        page_title = page.title()
        if page_title:
            title = clean_text(page_title)
    except Exception:
        pass

    invalid_keywords = ["page not found", "404", "تصنيف", "الصفحة الرئيسية", "تسجيل الدخول"]
    if not title or any(kw in title.lower() for kw in invalid_keywords):
        return

    movie_title = normalize_movie_title(title)
    if not movie_title:
        return

    print(f"\n🎬 جاري معالجة فيلم: {movie_title}")

    # 1. البوستر
    poster = "غير متوفر"
    try:
        poster = page.evaluate("""() => {
            let metaImg = document.querySelector('meta[property="og:image"]');
            if (metaImg && metaImg.content) return metaImg.content;
            const el = document.querySelector('.entry-image img, .poster img, img');
            return el ? (el.src || el.getAttribute('data-src')) : "غير متوفر";
        }""")
    except Exception:
        pass

    if poster == "غير متوفر" or not str(poster).startswith("http"):
        poster = get_tmdb_poster(movie_title)

    # 2. الوصف
    description = "غير متوفر"
    try:
        desc_text = page.evaluate("() => document.querySelector('.story, .text-white, article p')?.innerText.trim()")
        if desc_text and len(desc_text) > 5:
            description = desc_text
    except Exception:
        pass

    # 3. التقييم
    rating = "غير متوفر"
    try:
        rating_text = page.evaluate("() => document.querySelector('span.mx-2, .rating span')?.innerText.trim()")
        if rating_text:
            rating = rating_text
    except Exception:
        pass

    # 4. التصنيفات (Genres)
    genres = []
    try:
        genres = page.evaluate("() => Array.from(document.querySelectorAll('.genres a, .cats a, a[href*=\"category\"]')).map(t => t.innerText.trim()).filter(Boolean)")
    except Exception:
        pass

    # 5. جلب روابط المشاهدة والتحميل
    extracted_streaming, extracted_download = extract_media_links(page)

    movie_data = {
        "title": movie_title,
        "category_type": cat_type,
        "poster_url": poster,
        "description": description,
        "rating": rating,
        "genres": [clean_text(g) for g in genres if clean_text(g)],
        "watch_url": extracted_streaming[0] if extracted_streaming else None,
        "direct_links": {
            "streaming_links": extracted_streaming,
            "download_links": extracted_download
        }
    }

    try:
        supabase.table("movies_cima").upsert(movie_data, on_conflict="title").execute()
        print(f"  ✅ تم حفظ الفيلم بنجاح في Supabase!")
    except Exception as e:
        print(f"  ❌ خطأ في حفظ الفيلم: {e}")

# ==========================================
# السكربت الرئيسي
# ==========================================
def scrape_movies():
    movie_categories = [
        ("https://akwams.org/category/افلام-اجنبي", "افلام اجنبي"),
        ("https://akwams.org/category/افلام-عربي", "افلام عربي"),
        ("https://akwams.org/category/افلام-هندي", "افلام هندي"),
        ("https://akwams.org/category/افلام-انمي", "افلام انمي")
    ]

    print("🚀 بدء تشغيل سكربت سحب الأفلام فقط...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        # حظر الصور والملفات الثقيلة للسرعة
        context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2}", lambda route: route.abort())
        page = context.new_page()

        for base_url, cat_type in movie_categories:
            print(f"\n==========================================")
            print(f"📂 بدء سحب قسم: {cat_type}")
            print(f"==========================================")
            
            page_number = 1
            while True:
                url = f"{base_url}/page/{page_number}/" if page_number > 1 else f"{base_url}/"
                print(f"\n📄 جاري فحص الصفحة [{page_number}]...")
                
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    if response and response.status == 404:
                        print(f"🏁 وصلت لنهاية قسم {cat_type}.")
                        break

                    time.sleep(2)
                    movie_links = page.evaluate("""() => {
                        return [...new Set(Array.from(document.querySelectorAll('a')).map(a => a.href).filter(h => {
                            if (!h || !h.includes('akwams.org') || h.includes('/category/') || h.includes('/page/') || h.includes('/tag/')) return false;
                            const parts = h.split('/').filter(Boolean);
                            return parts.length >= 3 && parts[parts.length - 1].length > 5;
                        }))];
                    }""")
                    
                    if not movie_links:
                        print("⚠️ لم يتم العثور على روابط أفلام في هذه الصفحة.")
                        break
                    
                    for link in movie_links:
                        process_movie(page, link, cat_type)
                    
                    page_number += 1
                except Exception as e:
                    print(f"⚠️ خطأ أثناء قراءة الصفحة {page_number}: {e}")
                    page_number += 1
                    continue

        browser.close()

if __name__ == "__main__":
    scrape_movies()

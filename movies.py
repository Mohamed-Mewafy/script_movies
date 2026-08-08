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
    raise ValueError("⚠️ تنبيه: يرجى التأكد من ضبط متغيرات البيئة SUPABASE_URL و SUPABASE_KEY بشكل صحيح.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\"\'\[\]\{\}]', '', text)
    return " ".join(text.split()).strip()

def normalize_movie_title(raw_title):
    name = re.sub(r'^(مشاهدة|تحميل|فيلم)?\s*', '', raw_title).strip()
    clean_name = re.sub(r'\s*(-|\||مترجم|مدبلج|اكوام|Akwam|اونلاين|بجودة).*', '', name, flags=re.IGNORECASE).strip()
    clean_name = clean_text(clean_name)
    
    invalid_names = ["جديد", "حصريا", "فيلم"]
    if not clean_name or clean_name in invalid_names or len(clean_name) < 2:
        return None
    return clean_name

def shorten_link_via_shrinkme(original_url):
    if not original_url:
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

def extract_poster_url(page):
    try:
        poster = page.evaluate("""() => {
            let metaImg = document.querySelector('meta[property="og:image"]');
            if (metaImg && metaImg.content) return metaImg.content;
            
            const el = document.querySelector('.entry-image img, .poster img, .movie-poster img, img[class*="poster"]');
            return el ? (el.src || el.getAttribute('data-src')) : "غير متوفر";
        }""")
        return poster if poster else "غير متوفر"
    except Exception:
        return "غير متوفر"

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

def fetch_download_links_only(page, item_page_url):
    raw_download_links = []
    clean_base_url = item_page_url.rstrip('/')
    download_page_url = f"{clean_base_url}/download"

    try:
        page.goto(download_page_url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(2)
        
        links = page.evaluate("""() => {
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            return anchors.map(a => a.href).filter(h => {
                if (!h) return false;
                if (h === window.location.href || h.endsWith('/download') || h.endsWith('/download/')) return false;
                return h.includes('download') || h.includes('link') || h.includes('file') || h.includes('niramirus') || h.includes('server') || h.includes('direct') || h.includes('get') || !h.includes('akwams.org');
            });
        }""")
        
        for link in links:
            if link and link not in raw_download_links and not link.startswith("chrome-error://"):
                raw_download_links.append(link)
    except Exception:
        pass

    return [shorten_link_via_shrinkme(l) for l in raw_download_links if l]

def fetch_streaming_links_with_clicking(page, item_page_url):
    watch_page_url = f"{item_page_url.rstrip('/')}/watch/"
    extracted_streaming_links = []
    
    try:
        page.goto(watch_page_url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(3)
        
        server_buttons = page.locator('button:has-text("سيرفر"), a:has-text("سيرفر"), .servers-list button, div[class*="server"] button').all()
        if not server_buttons:
            server_buttons = page.locator('button').all()

        for btn in server_buttons:
            try:
                if btn.is_visible():
                    btn.click(timeout=2000)
                    time.sleep(1.5)
                    frame_url = page.evaluate("() => document.querySelector('iframe')?.src")
                    if frame_url and frame_url not in extracted_streaming_links and "akwams" not in frame_url and "about:blank" not in frame_url:
                        extracted_streaming_links.append(frame_url)
            except Exception:
                pass
    except Exception:
        pass
        
    return list(set(extracted_streaming_links))

def process_movie_item(page, item_page_url, cat_type):
    try:
        page.goto(item_page_url, wait_until="domcontentloaded", timeout=15000)
    except Exception:
        return

    title = ""
    try:
        page_title = page.title()
        if page_title:
            title = clean_text(page_title)
    except Exception:
        pass

    invalid_keywords = ["page not found", "404", "رمضان", "تصنيف", "الصفحة الرئيسية", "تسجيل الدخول"]
    if not title or any(kw in title.lower() for kw in invalid_keywords):
        return

    movie_title = normalize_movie_title(title)
    if not movie_title:
        return

    # 1. التحقق مسبقاً من قاعدة البيانات هل الفيلم موجود وله روابط؟
    try:
        existing_movie = supabase.table("movies_cima").select("watch_url, direct_links").eq("title", movie_title).execute()
        if existing_movie.data:
            row = existing_movie.data[0]
            has_watch = bool(row.get("watch_url"))
            direct = row.get("direct_links") or {}
            has_download = bool(direct.get("download_links"))
            
            # لو الفيلم موجود وله روابط مشاهدة وتحميل، نتخطاه فوراً
            if has_watch and has_download:
                print(ف"    ⏭️ الفيلم موجود مسبقاً وله روابط كاملة، تم التخطي: {movie_title}")
                return
    except Exception:
        pass
        
    print(f"    🎬 معالجة فيلم جديد أو تنشيط روابطه: {movie_title}")

    # استخراج البوستر من الصفحة مباشرة، وإذا لم يوجد يتم الاعتماد على TMDB
    poster = extract_poster_url(page)
    if poster == "غير متوفر" or not poster.startswith("http"):
        poster = get_tmdb_poster(movie_title)

    description = "غير متوفر"
    try:
        desc_text = page.evaluate("() => document.querySelector('.story, .text-white, article p')?.innerText.trim()")
        if desc_text and len(desc_text) > 5:
            description = desc_text
    except Exception:
        pass

    rating = "غير متوفر"
    try:
        rating_text = page.evaluate("() => document.querySelector('span.mx-2, .rating span')?.innerText.trim()")
        if rating_text:
            rating = rating_text
    except Exception:
        pass

    genres = []
    try:
        genres = page.evaluate("() => Array.from(document.querySelectorAll('.genres a, .cats a, a[href*=\"category\"]')).map(t => t.innerText.trim()).filter(Boolean)")
    except Exception:
        pass

    extracted_streaming_links = fetch_streaming_links_with_clicking(page, item_page_url)
    extracted_download_links = fetch_download_links_only(page, item_page_url)

    movie_data = {
        "title": movie_title,
        "category_type": cat_type,
        "poster_url": poster,
        "description": description,
        "rating": rating,
        "genres": [clean_text(g) for g in genres if clean_text(g)],
        "watch_url": extracted_streaming_links[0] if extracted_streaming_links else None,
        "direct_links": {
            "streaming_links": extracted_streaming_links,
            "download_links": extracted_download_links
        }
    }
    
    try:
        supabase.table("movies_cima").upsert(movie_data, on_conflict="title").execute()
        print(f"    ✅ تم حفظ وتحديث بيانات الفيلم وروابطه بنجاح.")
    except Exception as e:
        print(f"    ❌ خطأ في حفظ الفيلم: {e}")

def scrape_akwam_movies():
    categories = [
        ("https://akwams.org/category/افلام-اجنبي", "افلام اجنبي"),
        ("https://akwams.org/category/افلام-عربي", "افلام عربي")
    ]

    print("🚀 بدء سكريبت الأفلام...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36")
        context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,css}", lambda route: route.abort())
        page = context.new_page()

        for base_url, cat_type in categories:
            print(f"\n📂 بدء سحب قسم: {cat_type}")
            page_number = 1
            while True:
                url = f"{base_url}/page/{page_number}/" if page_number > 1 else f"{base_url}/"
                print(f"  📄 صفحة [{page_number}]")
                
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    if response and response.status == 404:
                        break

                    time.sleep(2)
                    item_links = page.evaluate("""() => {
                        return [...new Set(Array.from(document.querySelectorAll('a')).map(a => a.href).filter(h => {
                            if (!h || !h.includes('akwams.org') || h.includes('/category/') || h.includes('/page/') || h.includes('/tag/')) return false;
                            const parts = h.split('/').filter(Boolean);
                            return parts.length >= 3 && parts[parts.length - 1].length > 5;
                        }))];
                    }""")
                    
                    if not item_links:
                        break
                    
                    for link in item_links:
                        process_movie_item(page, link, cat_type)
                    page_number += 1
                except Exception:
                    break

        browser.close()

if __name__ == "__main__":
    scrape_akwam_movies()

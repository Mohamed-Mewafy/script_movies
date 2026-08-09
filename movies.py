import os
import re
import time
import urllib.parse
import urllib.request
import json
import requests
from playwright.sync_api import sync_playwright
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SHRINKME_API_TOKEN = os.environ.get("SHRINKME_API_TOKEN")

# إعدادات Cloudinary
cloudinary.config(
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME",),
    api_key = os.environ.get("CLOUDINARY_API_KEY"),
    api_secret = os.environ.get("CLOUDINARY_API_SECRET")
)

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("⚠️ تنبيه: يرجى التأكد من ضبط متغيرات البيئة SUPABASE_URL و SUPABASE_KEY بشكل صحيح.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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

def get_optimized_image_url(original_url):
    if not original_url or original_url == "غير متوفر":
        return original_url
    if "cloudinary.com" in original_url:
        return original_url
    try:
        upload_result = cloudinary.uploader.upload(
            original_url,
            folder="cimaspace_posters",
            fetch_format="auto",
            quality="auto"
        )
        return upload_result.get('secure_url', original_url)
    except Exception as e:
        print(f"    ⚠️ خطأ أثناء رفع وتحويل الصورة إلى Cloudinary: {e}")
        return original_url

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
                return h.includes('download') || 
                       h.includes('link') || 
                       h.includes('file') || 
                       h.includes('niramirus') || 
                       h.includes('server') ||
                       h.includes('direct') ||
                       h.includes('get') ||
                       !h.includes('akwams.org');
            });
        }""")
        
        for link in links:
            if link and link not in raw_download_links and not link.startswith("chrome-error://"):
                raw_download_links.append(link)
                
    except Exception as e:
        print(f"    ⚠️ خطأ أثناء سحب روابط التحميل: {e}")

    shortened_download_links = []
    for raw_link in raw_download_links:
        short_link = shorten_link_via_shrinkme(raw_link)
        if short_link:
            shortened_download_links.append(short_link)
            
    return list(set(shortened_download_links))

def fetch_streaming_links_with_clicking(page, item_page_url):
    watch_page_url = f"{item_page_url.rstrip('/')}/watch/"
    extracted_streaming_links = []
    
    try:
        page.goto(watch_page_url, wait_until="domcontentloaded", timeout=15000)
        time.sleep(3)
        
        server_buttons = page.locator('button:has-text("سيرفر"), a:has-text("سيرفر"), .servers-list button, .servers-list li, div[class*="server"] button').all()
        
        if not server_buttons:
            server_buttons = page.locator('button').all()

        for btn in server_buttons:
            try:
                if btn.is_visible():
                    btn.click(timeout=2000)
                    time.sleep(1.5)
                    
                    frame_url = page.evaluate("""() => {
                        const iframe = document.querySelector('iframe');
                        return iframe ? iframe.src : null;
                    }""")
                    
                    if (frame_url and 
                        frame_url not in extracted_streaming_links and 
                        "akwams" not in frame_url and 
                        "about:blank" not in frame_url and
                        not frame_url.startswith("chrome-error://")):
                        extracted_streaming_links.append(frame_url)
            except Exception:
                pass
            
            for frame in page.frames:
                f_url = frame.url
                if (f_url and 
                    "akwams.org" not in f_url and 
                    "about:blank" not in f_url and 
                    not f_url.startswith("chrome-error://")):
                    if f_url not in extracted_streaming_links:
                        extracted_streaming_links.append(f_url)
                        
    except Exception as e:
        print(f"    ⚠️ خطأ أثناء سحب روابط المشاهدة: {e}")
        
    return list(set(extracted_streaming_links))

def process_movie_item(page, item_page_url):
    try:
        page.goto(item_page_url, wait_until="domcontentloaded", timeout=15000)
    except Exception as e:
        print(f"    ❌ فشل فتح صفحة الفيلم: {e}")
        return

    title = ""
    try:
        page_title = page.title()
        if page_title:
            title = clean_title(page_title)
    except Exception:
        pass

    if not title or len(title) < 2 or "الصفحة الرئيسية" in title or "تسجيل الدخول" in title:
        return

    print(f"    🎬 فيلم: {title}")

    # 1. الاستعلام عن الفيلم للتأكد من وجوده مسبقاً
    existing = supabase.table("movies_cima").select("id, watch_url, direct_links").eq("title", title).execute()

    if existing.data:
        movie_record = existing.data[0]
        watch_url = movie_record.get("watch_url")
        direct_links = movie_record.get("direct_links") or {}
        
        streaming_links = direct_links.get("streaming_links", [])
        download_links = direct_links.get("download_links", [])

        has_watch = bool(watch_url) or bool(streaming_links)
        has_download = bool(download_links)

        if has_watch and has_download:
            print(f"    ⏭️ الفيلم وروابطه موجودة مسبقاً. تم التخطّي.")
            return

    # 2. سحب الروابط فقط للفيلم
    extracted_streaming_links = fetch_streaming_links_with_clicking(page, item_page_url)
    final_watch_url = extracted_streaming_links[0] if extracted_streaming_links else None
    extracted_download_links = fetch_download_links_only(page, item_page_url)

    direct_links_json = {
        "streaming_links": extracted_streaming_links,
        "download_links": extracted_download_links
    }

    # 3. إذا كان الفيلم موجوداً والروابط ناقصة -> تحديث الروابط فقط بدون تعديل البوستر
    if existing.data:
        movie_id = existing.data[0]["id"]
        update_data = {
            "watch_url": final_watch_url or existing.data[0].get("watch_url"),
            "direct_links": direct_links_json
        }
        try:
            supabase.table("movies_cima").update(update_data).eq("id", movie_id).execute()
            print(f"    ✅ [تم تحديث روابط الفيلم فقط بنجاح]")
        except Exception as e:
            print(f"    ❌ خطأ أثناء تحديث روابط الفيلم: {e}")
        return

    # 4. الفيلم جديد تماماً -> سحب البوستر، رفعه وتحويله لـ Cloudinary، ثم إضافة الفيلم لأول مرة
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
            let metaImg = document.querySelector('meta[property="og:image"]');
            if (metaImg && metaImg.content && metaImg.content.trim() !== "") {
                return new URL(metaImg.content, window.location.href).href;
            }
            const el = document.querySelector('.picture img, .poster img, .entry-image img, .box-poster img, main img');
            if (el) {
                let src = el.getAttribute('data-src') || el.getAttribute('src') || el.src;
                if (src && !src.includes('data:image') && !src.includes('blank.gif')) {
                    return new URL(src, window.location.href).href;
                }
            }
            return "غير متوفر";
        }""")
    except Exception:
        pass

    if poster == "غير متوفر" or not poster.startswith("http"):
        poster = get_tmdb_poster(title)

    # تحسين ورفع البوستر مباشرة إلى Cloudinary قبل الحفظ في سوبابيز
    optimized_poster_url = get_optimized_image_url(poster)

    formatted_movie = {
        "title": title,
        "category_type": "افلام اجنبي",
        "year": year,
        "poster_url": optimized_poster_url,
        "watch_url": final_watch_url,
        "direct_links": direct_links_json
    }

    try:
        supabase.table("movies_cima").insert(formatted_movie).execute()
        print(f"    ✅ [تم حفظ الفيلم الجديد مع البوستر المحسن على Cloudinary بنجاح]")
    except Exception as e:
        print(f"    ❌ خطأ أثناء حفظ الفيلم: {e}")

def scrape_section(page, base_category_url):
    print(f"\n🚀 بدء سحب قسم الأفلام بلا حدود: {base_category_url}")
    page_number = 1
    global_processed_links = set()
    
    while True:
        current_page_url = f"{base_category_url}/" if page_number == 1 else f"{base_category_url}/page/{page_number}/"
        print(f"\n📂 فحص وتثبيت روابط الصفحة [{page_number}] | الرابط: {current_page_url}")
        
        try:
            response = page.goto(current_page_url, wait_until="domcontentloaded", timeout=30000)
            if response and response.status == 404:
                print(f"🏁 وصلنا لنهاية القسم تماماً (خطأ 404).")
                break

            time.sleep(2)
            
            page_links = page.evaluate("""() => {
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                return anchors.map(a => a.href).filter(h => {
                    if (!h || !h.includes('akwams.org')) return false;
                    if (h.includes('/category/') || h.includes('/page/') || h.includes('/tag/') || h.includes('/search/') || h.includes('/login') || h.includes('/recent')) return false;
                    if (h === 'https://akwams.org/' || h === 'https://akwams.org') return false;
                    const parts = h.split('/').filter(Boolean);
                    return parts.length >= 3;
                });
            }""")
            
            current_page_items = []
            for link in page_links:
                if link and link not in global_processed_links:
                    global_processed_links.add(link)
                    current_page_items.append(link)
            
            if not current_page_items:
                print(f"⚠️ لا توجد روابط جديدة في الصفحة [{page_number}]. الانتقال للصفحة التالية...")
                page_number += 1
                continue
            
            print(f"🔗 تم تثبيت {len(current_page_items)} عنصر. جاري المعالجة...")
            
            for index, link in enumerate(current_page_items, 1):
                print(f"\n  -- عنصر ({index}/{len(current_page_items)})")
                process_movie_item(page, link)
            
            page_number += 1
            
        except Exception as e:
            print(f"⚠️ حدث خطأ في الصفحة [{page_number}]: {e}")
            page_number += 1
            continue

def scrape_akwam_site():
    print("🚀 بدء تشغيل السكربت لسحب الأفلام...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,css}", lambda route: route.abort())
        page = context.new_page()
        
        # سحب قسم الأفلام فقط
        scrape_section(page, "https://akwams.org/category/movies")

        browser.close()
        print("\n🎉 تم الانتهاء من سحب كافة الأفلام بنجاح!")

if __name__ == "__main__":
    scrape_akwam_site()

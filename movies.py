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

def clean_title(raw_title):
    title = raw_title.replace("مشاهدة", "").replace("فيلم", "").replace("مسلسل", "")
    title = title.replace("مترجم", "").replace("مدبلج", "").replace("اكوام", "").replace("Akwam", "")
    title = title.split("|")[0].split("-")[0]
    return clean_text(title)

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

def get_best_poster(page, title):
    # 1. محاولة استخراج البوستر الحقيقي المباشر من صفحة الفيلم في الموقع (عبر الـ DOM)
    try:
        poster = page.evaluate("""() => {
            // البحث عن صور البوستر داخل الصفحة بالمحددات المشهورة
            let imgEl = document.querySelector('.poster img, .movie-poster img, .details-img img, article img, .entry-content img');
            if (imgEl) {
                let src = imgEl.src || imgEl.getAttribute('data-src') || imgEl.getAttribute('data-lazy-src');
                if (src && !src.includes('logo') && !src.includes('icon')) return src;
            }
            // البحث في الـ Meta Tags الخاصة بالصورة
            let metaImg = document.querySelector('meta[property="og:image"]');
            if (metaImg && metaImg.content) return metaImg.content;
            
            return null;
        }""")
        if poster and "akwams" in poster:
            return poster
    except Exception:
        pass

    # 2. الطريقة الاحتياطية الآمنة عبر TMDB بطلب عام بدون مفتاح أو عبر رابط بديل آمن
    try:
        clean_name = re.sub(r'20\d{2}|19\d{2}', '', title)
        clean_name = re.sub(r'[\d\-\_\:\,\.\(\)]', ' ', clean_name)
        clean_name = clean_text(clean_name)
        
        if clean_name and len(clean_name) >= 2:
            query = urllib.parse.quote(clean_name)
            # استخدام سيرفر بحث بديل لا يتطلب مفتاح معقد أو متاح بشكل عام
            url = f"https://api.themoviedb.org/3/search/movie?api_key=592236d24f0c4310d5108cb50041d087&query={query}&language=ar"
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
    if "عربي" in url_lower:
        return "افلام عربي"
    elif "اجنبي" in url_lower:
        return "افلام اجنبي"
    elif "هندية" in url_lower:
        return "افلام هندية"
    elif "اسيوية" in url_lower:
        return "افلام اسيوية"
    elif "انمي" in url_lower:
        return "افلام انمي"
    for g in page_genres:
        clean_g = clean_text(g)
        if "افلام" in clean_g or "مسلسلات" in clean_g:
            return clean_g
    return "افلام عامة"

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

def process_movie_item(page, item_page_url, current_cat_url):
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
        print(f"    ⚠️ صفحة غير صالحة أو صفحة رئيسية/تسجيل دخول، تم التخطّي.")
        return

    print(f"    🎬 تم العثور على فيلم: {title}")

    existing = supabase.table("movies_cima").select("id, direct_links, watch_url").eq("title", title).execute()

    if existing.data:
        current_data = existing.data[0]
        existing_direct_links = current_data.get("direct_links", {})
        if not isinstance(existing_direct_links, dict):
            existing_direct_links = {}
            
        existing_downloads = existing_direct_links.get("download_links", [])
        existing_streaming = existing_direct_links.get("streaming_links", [])

        is_downloads_empty = not existing_downloads or len(existing_downloads) == 0
        is_streaming_empty = not existing_streaming or len(existing_streaming) <= 1

        if not is_downloads_empty and not is_streaming_empty:
            print(f"    ⏭️ الفيلم موجود ولديه روابط كاملة. تم التخطّي.")
            return

        updated_needed = False
        updates_payload = {}

        if is_downloads_empty:
            print(f"    ⚠️ روابط التحميل فارغة. جاري سحبها...")
            extracted_download_links = fetch_download_links_only(page, item_page_url)
            if extracted_download_links:
                existing_direct_links["download_links"] = extracted_download_links
                updated_needed = True

        if is_streaming_empty:
            print(f"    ⚠️ روابط المشاهدة ناقصة. جاري إعادة فحص وسحب السيرفرات...")
            extracted_streaming_links = fetch_streaming_links_with_clicking(page, item_page_url)
            if extracted_streaming_links and len(extracted_streaming_links) > len(existing_streaming):
                existing_direct_links["streaming_links"] = extracted_streaming_links
                updates_payload["watch_url"] = extracted_streaming_links[0]
                updated_needed = True

        if updated_needed:
            if existing_direct_links:
                updates_payload["direct_links"] = existing_direct_links
            try:
                supabase.table("movies_cima").update(updates_payload).eq("title", title).execute()
                print(f"    🔄 [تم تحديث روابط الفيلم بنجاح]: {title}")
            except Exception as e:
                print(f"    ❌ خطأ أثناء تحديث روابط لـ ({title}): {e}")
        else:
            print(f"    ℹ️ لم يتم العثور على روابط جديدة إضافية لهذا الفيلم.")
            
    else:
        print(f"    🆕 الفيلم غير موجود. جاري سحب البيانات وحفظه...")
        
        extracted_streaming_links = fetch_streaming_links_with_clicking(page, item_page_url)
        final_watch_url = extracted_streaming_links[0] if extracted_streaming_links else None

        extracted_download_links = fetch_download_links_only(page, item_page_url)

        direct_links_json = {
            "streaming_links": extracted_streaming_links,
            "download_links": extracted_download_links
        }

        year = None
        match = re.search(r'20\d{2}|19\d{2}', title)
        if match:
            try:
                year = int(match.group(0))
            except Exception:
                pass

        poster = get_best_poster(page, title)

        description = "غير متوفر"
        try:
            desc_text = page.evaluate("""() => {
                const el = document.querySelector('.story, .text-white, article p');
                return el ? el.innerText.trim() : "غير متوفر";
            }""")
            if desc_text and len(desc_text) > 5:
                description = desc_text
        except Exception:
            pass

        rating = "غير متوفر"
        try:
            rating_text = page.evaluate("""() => {
                const el = document.querySelector('span.mx-2, .rating span');
                return el ? el.innerText.trim() : "غير متوفر";
            }""")
            if rating_text:
                rating = rating_text
        except Exception:
            pass

        genres = []
        try:
            genres = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('.genres a, .cats a, a[href*="category"]')).map(t => t.innerText.trim()).filter(Boolean);
            }""")
        except Exception:
            pass

        clean_category = extract_category_from_url_or_page(current_cat_url, genres, title)

        formatted_movie = {
            "title": title,
            "category_type": clean_category,
            "year": year,
            "poster_url": poster,
            "description": description,
            "rating": rating,
            "genres": [clean_text(g) for g in genres if clean_text(g)],
            "watch_url": final_watch_url,
            "direct_links": direct_links_json
        }

        try:
            supabase.table("movies_cima").upsert(formatted_movie, on_conflict="title").execute()
            print(f"    ✅ [تم حفظ الفيلم بكامل بياناته بنجاح]: {title}")
        except Exception as e:
            print(f"    ❌ خطأ أثناء حفظ الفيلم الجديد ({title}): {e}")

def scrape_akwam_site():
    print("🚀 بدء السكربت لتفليش وسحب السيرفرات والبوسترات والتحميل لكل الأفلام...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        context.route("**/*.{woff,woff2,css}", lambda route: route.abort())
        page = context.new_page()
        
        base_category_url = "https://akwams.org/category/movies"
        page_number = 1
        
        while True:
            if page_number == 1:
                current_page_url = f"{base_category_url}/"
            else:
                current_page_url = f"{base_category_url}/page/{page_number}/"
                
            print(f"\n📂 جاري فحص الصفحة رقم [{page_number}] | الرابط: {current_page_url}")
            
            try:
                response = page.goto(current_page_url, wait_until="domcontentloaded", timeout=30000)
                
                if response and response.status == 404:
                    print(f"🏁 وصلنا إلى نهاية الصفحات (خطأ 404). تم الانتهاء تماماً!")
                    break

                time.sleep(2)
                
                item_links = page.evaluate("""() => {
                    const anchors = Array.from(document.querySelectorAll('a'));
                    const links = anchors.map(a => a.href).filter(h => {
                        if (!h || !h.includes('akwams.org')) return false;
                        if (h.includes('/category/') || h.includes('/page/') || h.includes('/tag/') || h.includes('/search/') || h.includes('/login') || h.includes('/recent')) return false;
                        if (h === 'https://akwams.org/' || h === 'https://akwams.org') return false;
                        const parts = h.split('/').filter(Boolean);
                        return parts.length >= 3 && parts[parts.length - 1].length > 5;
                    });
                    return [...new Set(links)];
                }""")
                
                if not item_links:
                    print(f"🏁 لا توجد روابط أخرى في الصفحة [{page_number}]. تم الانتهاء!")
                    break
                
                print(f"🔗 عُثر على {len(item_links)} رابط فيلم في هذه الصفحة...")
                
                for index, link in enumerate(item_links, 1):
                    print(f"\n  -- فيلم ({index}/{len(item_links)})")
                    process_movie_item(page, link, current_page_url)
                
                page_number += 1
                
            except Exception as e:
                print(f"⚠️ حدث خطأ عند الصفحة [{page_number}]: {e}")
                break

        browser.close()
        print("\n🎉 تم الانتهاء من كافة المهام بنجاح تام!")

if __name__ == "__main__":
    scrape_akwam_site()

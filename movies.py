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

def extract_season_and_episode(text):
    season_num = 1
    episode_num = 1
    
    season_match = re.search(r'(?:الموسم|Season)\s*(\d+)', text, re.IGNORECASE)
    if season_match:
        try:
            season_num = int(season_match.group(1))
        except Exception:
            pass
            
    episode_match = re.search(r'(?:الحلقة|Episode)\s*(\d+)', text, re.IGNORECASE)
    if episode_match:
        try:
            episode_num = int(episode_match.group(1))
        except Exception:
            pass
            
    return season_num, episode_num

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

    existing = supabase.table("movies_cima").select("id").eq("title", title).execute()
    if existing.data:
        print(f"    ⏭️ الفيلم موجود مسبقاً. تم التخطّي.")
        return

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

    if poster == "غير متوفر" or not poster.startswith("http"):
        poster = get_tmdb_poster(title)

    formatted_movie = {
        "title": title,
        "category_type": "افلام اجنبي",
        "year": year,
        "poster_url": poster,
        "watch_url": final_watch_url,
        "direct_links": direct_links_json
    }

    try:
        supabase.table("movies_cima").insert(formatted_movie).execute()
        print(f"    ✅ [تم حفظ الفيلم بنجاح]")
    except Exception as e:
        print(f"    ❌ خطأ أثناء حفظ الفيلم: {e}")

def process_series_item(page, item_page_url, episode_index=1):
    try:
        page.goto(item_page_url, wait_until="domcontentloaded", timeout=15000)
    except Exception as e:
        print(f"    ❌ فشل فتح صفحة الحلقة: {e}")
        return

    raw_page_title = ""
    try:
        raw_page_title = page.title()
    except Exception:
        pass

    if not raw_page_title or "الصفحة الرئيسية" in raw_page_title or "تسجيل الدخول" in raw_page_title:
        return

    series_name = ""
    try:
        series_name = page.evaluate("""() => {
            const breadcrumb = document.querySelector('ul.breadcrumb, .series-title, h1 a, .entry-title a');
            if (breadcrumb) return breadcrumb.innerText.trim();
            const headerEl = document.querySelector('h1, h2');
            return headerEl ? headerEl.innerText.trim() : "";
        }""")
    except Exception:
        pass

    if not series_name or len(series_name) < 2:
        temp_name = raw_page_title
        for keyword in ["الموسم", "الحلقة", "مترجم", "مدبلج", "مشاهدة", "مسلسل", "اكوام", "Akwam", "|", "-"]:
            if keyword in temp_name:
                temp_name = temp_name.split(keyword)[0]
        series_name = clean_text(temp_name)

    if not series_name or len(series_name) < 2:
        series_name = "Fightland"

    season_number, episode_number = extract_season_and_episode(raw_page_title)
    if episode_number == 1 and episode_index > 1:
        episode_number = episode_index

    episode_title = f"الحلقة {episode_number}"
    print(f"    📺 مسلسل: {series_name} | موسم {season_number} - حلقة {episode_number}")

    series_id = None
    try:
        existing_series = supabase.table("tv_series").select("id, title").ilike("title", f"%{series_name}%").execute()
        if existing_series.data:
            series_id = existing_series.data[0]["id"]
            series_name = existing_series.data[0]["title"]
        else:
            poster = get_tmdb_poster(series_name)
            new_series_data = {
                "title": series_name,
                "poster_url": poster,
                "category_type": "مسلسلات اجنبي"
            }
            res = supabase.table("tv_series").insert(new_series_data).execute()
            if res.data:
                series_id = res.data[0]["id"]
    except Exception as e:
        print(f"    ⚠️ خطأ في جدول tv_series: {e}")
        return

    if not series_id:
        return

    try:
        existing_ep = supabase.table("episodes_cima").select("id").eq("series_id", series_id).eq("season_number", season_number).eq("episode_number", episode_number).execute()
        if existing_ep.data:
            print(f"    ⏭️ الحلقة موجودة مسبقاً. تم التخطّي.")
            return
    except Exception:
        pass

    extracted_streaming_links = fetch_streaming_links_with_clicking(page, item_page_url)
    final_watch_url = extracted_streaming_links[0] if extracted_streaming_links else None
    extracted_download_links = fetch_download_links_only(page, item_page_url)

    direct_links_json = {
        "streaming_links": extracted_streaming_links,
        "download_links": extracted_download_links
    }

    episode_data = {
        "series_id": series_id,
        "title": episode_title,
        "season_number": season_number,
        "episode_number": episode_number,
        "watch_url": final_watch_url,
        "direct_links": direct_links_json
    }

    try:
        supabase.table("episodes_cima").insert(episode_data).execute()
        print(f"    ✅ [تم حفظ الحلقة بنجاح]")
    except Exception as e:
        print(f"    ❌ خطأ أثناء حفظ الحلقة: {e}")

def scrape_section(page, base_category_url, section_type):
    print(f"\n🚀 بدء سحب القسم: {base_category_url}")
    page_number = 1
    global_processed_links = set() # ذاكرة مؤقتة لمنع تكرار الروابط نهائياً في الجلسة
    
    while page_number <= 30: # تحديد الحد الأقصى للصفحات لمنع الدوران اللانهائي
        current_page_url = f"{base_category_url}/" if page_number == 1 else f"{base_category_url}/page/{page_number}/"
        print(f"\n📂 فحص الصفحة [{page_number}] | الرابط: {current_page_url}")
        
        try:
            response = page.goto(current_page_url, wait_until="domcontentloaded", timeout=30000)
            if response and response.status == 404:
                print(f"🏁 نهاية القسم (خطأ 404).")
                break

            time.sleep(2)
            
            # استهداف الروابط الخاصة بالبوسترات/العناصر في الشبكة لتفادي الروابط العشوائية
            item_links = page.evaluate("""() => {
                const anchors = Array.from(document.querySelectorAll('.entry-box a, .media-box a, .item a, div.card a, a.box'));
                if (anchors.length === 0) {
                    // طريقة بديلة لو لم يتم العثور على الكلاسات المعتادة
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => h && h.includes('akwams.org') && !h.includes('/category/') && !h.includes('/page/'));
                }
                return anchors.map(a => a.href);
            }""")
            
            # تنقية الروابط الفريدة
            valid_links = []
            for link in item_links:
                if link and link not in global_processed_links:
                    if "akwams.org" in link and not any(x in link for x in ['/category/', '/page/', '/tag/', '/search/', '/login']):
                        valid_links.append(link)
                        global_processed_links.add(link)
            
            if not valid_links:
                print(f"⚠️ لا توجد روابط جديدة في الصفحة [{page_number}]. الانتقال للالتالي...")
                page_number += 1
                continue
            
            print(f"🔗 عُثر على {len(valid_links)} عنصر جديد في هذه الصفحة.")
            
            for index, link in enumerate(valid_links, 1):
                print(f"\n  -- عنصر ({index}/{len(valid_links)})")
                if section_type == "series":
                    process_series_item(page, link, episode_index=index)
                else:
                    process_movie_item(page, link)
            
            page_number += 1
            
        except Exception as e:
            print(f"⚠️ خطأ في الصفحة [{page_number}]: {e}")
            page_number += 1
            continue

def scrape_akwam_site():
    print("🚀 بدء السكربت المحدث...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,css}", lambda route: route.abort())
        page = context.new_page()
        
        scrape_section(page, "https://akwams.org/category/مسلسلات-اجنبي", "series")
        scrape_section(page, "https://akwams.org/category/movies", "movies")

        browser.close()
        print("\n🎉 تم الانتهاء بنجاح!")

if __name__ == "__main__":
    scrape_akwam_site()

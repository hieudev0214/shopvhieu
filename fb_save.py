"""
Tool lưu toàn bộ ảnh của bài viết Facebook vào folder đặt tên theo MÃ SỐ + GIÁ.

Cách dùng:
    python fb_save.py <link1> [link2 ...]
    python fb_save.py              (đọc các link trong file links.txt, mỗi dòng 1 link)

Tuỳ chọn:
    --show     hiện cửa sổ trình duyệt (mặc định chạy ẩn)
    --login    mở trình duyệt để đăng nhập Facebook 1 lần (dùng cho bài viết không công khai)

Kết quả: anh_da_luu/Ms <mã> - <giá>/01.jpg, 02.jpg, ... + noi_dung.txt
"""
import re
import sys
import time
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "anh_da_luu"
PROFILE_DIR = BASE / ".fb_profile"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# ---------------------------------------------------------------- phân tích mã + giá
CODE_RE = re.compile(r"\b(?:ms|mã\s*số|mã|ma\s*so|ma|code|sp)\s*[:.\-#]?\s*([A-Za-z]{0,3}\d+[A-Za-z0-9]*)", re.I)
UNIT = r"(?:k|m|tr|triệu|củ|cu|đ|vnđ|vnd)"
# giá có ghi chữ "Giá": "Giá : 3999k", "giá 2tr5"
PRICE_LABEL_RE = re.compile(r"(?:giá|gia|price)\s*[:\-=]?\s*(\d[\d.,]*\s*" + UNIT + r"?\d*x*)", re.I)
# giá không ghi chữ "Giá", nằm ngay sau mã số: "Ms 125. 4mx."
PRICE_BARE_RE = re.compile(r"^[\s.,:\-|]*(\d[\d.,]*\s*" + UNIT + r"\d*x*)(?=[\s.,|)]|$)", re.I)
CONTACT_RE = re.compile(r"https?://|zalo|\bbox\b|\bib\b|inbox|liên hệ|lh\s*:|sđt|[𝟎-𝟗\d]{3}[.\s]?[𝟎-𝟗\d]{3}[.\s]?[𝟎-𝟗\d]{3,4}", re.I)


def parse_code_price(text: str):
    code = price = None
    m = CODE_RE.search(text)
    if m:
        code = m.group(1)
    pm = PRICE_LABEL_RE.search(text)
    if pm:
        price = pm.group(1).strip()
    elif m:
        pm = PRICE_BARE_RE.search(text[m.end():])
        if pm:
            price = pm.group(1).strip()
    return code, price


def extract_description(text: str) -> str:
    """Lấy phần mô tả acc: bỏ dòng mã số/giá/liên hệ/link nhóm."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if CODE_RE.match(s) or CONTACT_RE.search(s):
            # dòng mã số hoặc liên hệ: chỉ giữ nếu còn nội dung khác sau khi bỏ phần đó
            s = CODE_RE.sub("", s)
            s = re.sub(r"\([^)]*\)", "", s)          # (múc acc ib zalo ...)
            s = re.split(r"\|", s)[0]                # | húp acc ib zalo ...
            s = PRICE_BARE_RE.sub("", s)
            if CONTACT_RE.search(s):
                continue
        s = PRICE_LABEL_RE.sub("", s)
        s = re.sub(r"^(?:giá|gia)\s*[:\-=]?\s*$", "", s, flags=re.I)
        s = s.strip(" .,:;-|")
        if len(re.sub(r"[\W\d_]", "", s)) >= 2:
            out.append(s)
    return "\n".join(out)


def safe_name(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s)
    return re.sub(r"\s+", " ", s).strip(" .")[:80] or "khong_ro"


# ---------------------------------------------------------------- trình duyệt
def get_post_text(page) -> str:
    # bấm "Xem thêm" để mở hết nội dung bài nếu bị rút gọn
    try:
        page.evaluate("""() => {
            for (const sel of ['div[data-ad-preview="message"]', 'div[data-ad-comet-preview="message"]'])
                for (const box of document.querySelectorAll(sel))
                    for (const b of box.querySelectorAll('div[role="button"]'))
                        if (/^(Xem thêm|See more)$/i.test(b.innerText.trim())) b.click();
        }""")
        page.wait_for_timeout(800)
    except Exception:
        pass
    # tiêu đề trang có dạng "Tên - <nội dung bài> | Facebook"
    for sel in ['div[data-ad-preview="message"]', 'div[data-ad-comet-preview="message"]']:
        el = page.query_selector(sel)
        if el:
            t = el.inner_text().strip()
            if t:
                return t
    try:
        meta = page.get_attribute('meta[property="og:description"]', "content", timeout=2000)
        if meta:
            return meta
    except Exception:
        pass
    # khi chưa đăng nhập: nội dung nằm giữa dòng "·" và dòng "+23"/"Tất cả cảm xúc"
    try:
        lines = page.inner_text("body").splitlines()
        if "·" in [l.strip() for l in lines]:
            start = [l.strip() for l in lines].index("·") + 1
            body = []
            for l in lines[start:]:
                if re.match(r"^\s*(\+\d+|Tất cả cảm xúc:?|All reactions:?|Thích|Like)\s*$", l):
                    break
                body.append(l)
            t = "\n".join(body).strip()
            if t:
                return t
    except Exception:
        pass
    title = page.title()
    title = re.sub(r"\s*\|\s*Facebook\s*$", "", title)
    return title.split(" - ", 1)[-1]


def fbid_of(url: str):
    q = parse_qs(urlparse(url).query)
    if "fbid" in q:
        return q["fbid"][0]
    m = re.search(r"/photos/[^/]+/(\d+)", url)
    return m.group(1) if m else url


def close_login_popup(page):
    """Đóng popup 'Xem thêm trên Facebook' (bắt đăng nhập) nếu có."""
    try:
        page.evaluate("""() => {
            for (const d of document.querySelectorAll('div[role="dialog"]')) {
                // chỉ đóng popup đăng nhập (có ô mật khẩu), KHÔNG đóng hộp thoại chứa bài viết
                if (!d.querySelector('input[type="password"]')) continue;
                const b = d.querySelector('[aria-label="Đóng"], [aria-label="Close"]');
                if (b) b.click();
            }
        }""")
    except Exception:
        pass


def big_image_src(page, prev_src=None, timeout=8.0):
    """Lấy src ảnh chính trong trình xem ảnh."""
    end = time.time() + timeout
    while time.time() < end:
        src = page.evaluate("""() => {
            const m = document.querySelector('img[data-visualcompletion="media-vscroll"]');
            if (m && m.src.includes('fbcdn')) return m.src;
            let best = null, area = 0;
            for (const im of document.querySelectorAll('img')) {
                if (!im.src.includes('fbcdn')) continue;
                const r = im.getBoundingClientRect();
                const a = r.width * r.height;
                if (r.width > 200 && a > area) { area = a; best = im.src; }
            }
            return best;
        }""")
        if src and src != prev_src:
            return src
        page.wait_for_timeout(100)
    return None


def collect_photos(page, on_photo):
    """Mở ảnh đầu tiên rồi bấm 'Ảnh tiếp theo' cho đến khi quay lại ảnh đầu.
    Mỗi ảnh tìm được sẽ gọi on_photo(stt, src) để tải ngay (song song)."""
    links = page.eval_on_selector_all(
        "a[href*='/photo/?fbid='], a[href*='/photos/']", "els => els.map(e => e.href)")
    links = [l for l in links if "fbid=" in l or "/photos/" in l]
    if not links:
        return 0
    first = links[0]
    page.goto(first, wait_until="domcontentloaded", timeout=60000)

    count, seen = 0, set()
    src = big_image_src(page, timeout=15)
    for _ in range(500):
        fid = fbid_of(page.url)
        if fid in seen:
            break
        seen.add(fid)
        if src:
            count += 1
            on_photo(count, src)
        # sang ảnh tiếp theo
        old_url = page.url
        close_login_popup(page)
        # bấm bằng JS để không bị popup che
        clicked = page.evaluate("""() => {
            const b = document.querySelector('[aria-label="Ảnh tiếp theo"], [aria-label="Next photo"]');
            if (b) { b.click(); return true; } return false;
        }""")
        if not clicked:
            page.keyboard.press("ArrowRight")
        # chờ URL đổi
        for _ in range(100):
            if page.url != old_url:
                break
            page.wait_for_timeout(100)
        if page.url == old_url:
            break
        src = big_image_src(page, prev_src=src)
    return count


def download(url, path: Path):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.facebook.com/"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                path.write_bytes(r.read())
            return True
        except Exception as e:
            err = e
            time.sleep(1.5)
    print(f"   ! lỗi tải {path.name}: {err}")
    return False


def open_context(p, show=False):
    """Mở trình duyệt (giữ đăng nhập trong thư mục .fb_profile)."""
    ctx = p.chromium.launch_persistent_context(
        str(PROFILE_DIR), headless=not show, locale="vi-VN", user_agent=UA,
        viewport={"width": 1366, "height": 900})
    # không cho trình duyệt tải video/font (không cần) -> nhanh hơn
    ctx.route("**/*", lambda r: r.abort()
              if r.request.resource_type in ("media", "font") else r.continue_())
    return ctx


def process(ctx, link, log=print, on_progress=None):
    """Lưu 1 bài viết. Trả về dict thông tin, hoặc None nếu không có ảnh."""
    log(f"\n==> {link}")
    page = ctx.new_page()
    page.goto(link, wait_until="domcontentloaded", timeout=60000)
    # link share sẽ chuyển hướng sang link bài viết thật, chờ cho xong
    try:
        page.wait_for_url(lambda u: "/share/" not in u, timeout=20000)
    except Exception:
        pass
    # chờ tới khi có link ảnh trong bài (thay vì chờ cố định)
    def ready():
        return page.title().strip() not in ("", "Facebook") and page.query_selector(
            "a[href*='/photo/?fbid='], a[href*='/photos/']") is not None
    for attempt in range(3):
        end = time.time() + 15
        while time.time() < end and not ready():
            page.wait_for_timeout(200)
        if ready():
            break
        # đôi khi Facebook trả về trang trống -> tải lại
        page.reload(wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(500)
    text = get_post_text(page)
    code, price = parse_code_price(text)
    desc = extract_description(text)
    log(f"   Mã số: {code}   Giá: {price}")
    log(f"   Mô tả: {desc.replace(chr(10), ' / ') or '(không có)'}")

    name = safe_name(f"Ms {code or 'khong_ro'} - {price or 'khong_ro_gia'}")
    folder = OUT_DIR / name
    if folder.exists() and any(folder.iterdir()):
        n = 2
        while (OUT_DIR / f"{name} ({n})").exists():
            n += 1
        folder = OUT_DIR / f"{name} ({n})"
    folder.mkdir(parents=True, exist_ok=True)

    # tải ảnh song song ngay khi tìm thấy, trong lúc trình duyệt duyệt tiếp ảnh sau
    pool = ThreadPoolExecutor(max_workers=8)
    jobs = []

    def on_photo(i, src):
        jobs.append(pool.submit(download, src, folder / f"{i:02d}.jpg"))
        if on_progress:
            on_progress(i)
    total = collect_photos(page, on_photo)
    page.close()
    ok = sum(1 for j in jobs if j.result())
    pool.shutdown()
    if not total:
        folder.rmdir()
        log("   ! Không tìm thấy ảnh (bài riêng tư? cần đăng nhập Facebook)")
        return None
    (folder / "noi_dung.txt").write_text(
        f"Mã số: {code or ''}\nGiá: {price or ''}\nMô tả: {desc}\n",
        encoding="utf-8")
    append_csv(code, price, desc)
    log(f"\n   ✔ Đã lưu {ok}/{total} ảnh vào: {folder}")
    return {"folder": folder.name, "code": code, "price": price, "desc": desc,
            "ok": ok, "total": total}


def append_csv(code, price, desc):
    """Ghi thêm 1 dòng vào anh_da_luu/danh_sach.csv (mở được bằng Excel)."""
    import csv
    f = OUT_DIR / "danh_sach.csv"
    new = not f.exists()
    with open(f, "a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["Mã số", "Giá", "Mô tả"])
        w.writerow([code or "", price or "", desc.replace("\n", " / ")])


def main():
    args = sys.argv[1:]
    show = "--show" in args or "--login" in args
    login = "--login" in args
    links = [a for a in args if a.startswith("http")]
    if not links and not login:
        f = BASE / "links.txt"
        if f.exists():
            links = [l.strip() for l in f.read_text(encoding="utf-8").splitlines()
                     if l.strip().startswith("http")]
    if not links and not login:
        print(__doc__)
        return

    with sync_playwright() as p:
        ctx = open_context(p, show)
        if login:
            pg = ctx.new_page()
            pg.goto("https://www.facebook.com/login")
            input("Đăng nhập Facebook trong cửa sổ vừa mở, xong nhấn Enter tại đây...")
            pg.close()
        for link in links:
            for attempt in (1, 2):
                try:
                    process(ctx, link, on_progress=lambda i: print(
                        f"   - ảnh {i}", end="\r", flush=True))
                    break
                except Exception as e:
                    print(f"   ! Lỗi: {str(e).splitlines()[0]}")
                    if attempt == 1:
                        print("   ... thử lại")
                    for pg in ctx.pages[1:] if login else ctx.pages:
                        try:
                            pg.close()
                        except Exception:
                            pass
        ctx.close()
    print(f"\nXong. Ảnh nằm trong: {OUT_DIR}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()

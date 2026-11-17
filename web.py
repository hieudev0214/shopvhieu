"""
Trang web lưu ảnh acc từ Facebook — chạy trên máy, mở ở http://127.0.0.1:8000
Chạy:  python web.py   (hoặc nhấp đúp chay_web.bat)
"""
import json
import os
import queue
import re
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import fb_save

PORT = 8000
OUT_DIR = fb_save.OUT_DIR
HTML_FILE = Path(__file__).resolve().parent / "web.html"

jobs = []                 # danh sách việc, mới nhất ở cuối
jobs_lock = threading.Lock()
job_queue = queue.Queue()


# ------------------------------------------------------------------ luồng chạy trình duyệt
def worker():
    """Một luồng duy nhất giữ trình duyệt và xử lý lần lượt từng link."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = None
        while True:
            job = job_queue.get()
            job["status"] = "running"
            job["started"] = time.time()
            for attempt in (1, 2):
                try:
                    if ctx is None:
                        ctx = fb_save.open_context(p)
                    res = fb_save.process(
                        ctx, job["link"], log=lambda m: None,
                        on_progress=lambda i: job.__setitem__("progress", i))
                    if res:
                        job.update(status="done", result=res)
                    else:
                        job.update(status="error",
                                   error="Không tìm thấy ảnh (bài riêng tư hoặc link sai)")
                    break
                except Exception as e:
                    job["error"] = str(e).splitlines()[0][:200]
                    job["status"] = "error" if attempt == 2 else "running"
                    try:
                        for pg in ctx.pages:
                            pg.close()
                    except Exception:
                        try:
                            ctx.close()
                        except Exception:
                            pass
                        ctx = None
            job["finished"] = time.time()


# ------------------------------------------------------------------ dữ liệu đã lưu
def read_info(folder: Path):
    info = {"code": "", "price": "", "desc": ""}
    f = folder / "noi_dung.txt"
    if f.exists():
        txt = f.read_text(encoding="utf-8")
        m = re.search(r"^Mã số:[ \t]*(.*)$", txt, re.M)
        info["code"] = m.group(1).strip() if m else ""
        m = re.search(r"^Giá:[ \t]*(.*)$", txt, re.M)
        info["price"] = m.group(1).strip() if m else ""
        m = re.search(r"^Mô tả:[ \t]*(.*)", txt, re.M | re.S)
        info["desc"] = m.group(1).strip() if m else ""
    return info


def list_items():
    items = []
    if OUT_DIR.exists():
        for d in OUT_DIR.iterdir():
            if not d.is_dir():
                continue
            imgs = sorted(p.name for p in d.glob("*.jpg"))
            info = read_info(d)
            info.update(folder=d.name, images=imgs, mtime=d.stat().st_mtime)
            items.append(info)
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def safe_folder(name: str):
    """Chỉ cho phép thư mục nằm ngay trong anh_da_luu."""
    p = (OUT_DIR / name).resolve()
    if p.parent != OUT_DIR.resolve() or not p.is_dir():
        return None
    return p


# ------------------------------------------------------------------ web server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/":
            return self.send(200, HTML_FILE.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if path == "/api/jobs":
            with jobs_lock:
                return self.send(200, jobs[-30:][::-1])
        if path == "/api/items":
            return self.send(200, list_items())
        if path.startswith("/img/"):
            parts = path[5:].split("/")
            if len(parts) == 2:
                folder = safe_folder(parts[0])
                if folder and re.fullmatch(r"[\w\-. ]+\.jpg", parts[1]):
                    f = folder / parts[1]
                    if f.is_file():
                        self.send_response(200)
                        self.send_header("Content-Type", "image/jpeg")
                        self.send_header("Content-Length", str(f.stat().st_size))
                        self.send_header("Cache-Control", "max-age=3600")
                        self.end_headers()
                        self.wfile.write(f.read_bytes())
                        return
        self.send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        data = self.read_json()
        if path == "/api/save":
            links = re.findall(r"https?://[^\s\"'<>]*facebook\.com/[^\s\"'<>]+", data.get("text", ""))
            added = []
            with jobs_lock:
                running = {j["link"] for j in jobs if j["status"] in ("queued", "running")}
                for link in dict.fromkeys(links):
                    if link in running:
                        continue
                    job = {"id": uuid.uuid4().hex[:8], "link": link, "status": "queued",
                           "progress": 0, "result": None, "error": None, "created": time.time()}
                    jobs.append(job)
                    job_queue.put(job)
                    added.append(job["id"])
            return self.send(200, {"added": len(added), "found": len(links)})
        if path == "/api/open":
            folder = safe_folder(data.get("folder", "")) if data.get("folder") else OUT_DIR
            if folder:
                OUT_DIR.mkdir(exist_ok=True)
                os.startfile(folder)
                return self.send(200, {"ok": True})
            return self.send(404, {"error": "không có folder"})
        if path == "/api/clear":
            with jobs_lock:
                jobs[:] = [j for j in jobs if j["status"] in ("queued", "running")]
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(exist_ok=True)
    threading.Thread(target=worker, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Web đang chạy: {url}\n(Đừng tắt cửa sổ này. Nhấn Ctrl+C để dừng.)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

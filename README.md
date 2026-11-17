# Lưu ảnh acc từ Facebook

Tool lưu toàn bộ ảnh của một bài viết Facebook vào folder đặt tên theo **mã số + giá**, kèm file `noi_dung.txt` (mã số, giá, mô tả acc) và file tổng hợp `danh_sach.csv`.

## Cài đặt

```
pip install playwright
playwright install chromium
```

## Cách dùng

**Trang web (dễ nhất):** nhấp đúp `chay_web.bat` (hoặc chạy `python web.py`), trình duyệt mở `http://127.0.0.1:8000`. Dán link bài viết vào là tự lưu.

**Dòng lệnh:**

```
python fb_save.py <link1> [link2 ...]
python fb_save.py              # đọc các link trong links.txt
python fb_save.py --login      # đăng nhập Facebook 1 lần (cho bài không công khai)
```

## Kết quả

```
anh_da_luu/
├── danh_sach.csv
└── Ms 2910 - 5555k/
    ├── 01.jpg … 18.jpg
    └── noi_dung.txt
```

## Các file

| File | Chức năng |
|---|---|
| `fb_save.py` | Lõi: mở bài viết, đọc mã số/giá/mô tả, duyệt album, tải ảnh song song |
| `web.py` + `web.html` | Trang web chạy trên máy |
| `chay.bat`, `chay_web.bat` | Chạy nhanh trên Windows |

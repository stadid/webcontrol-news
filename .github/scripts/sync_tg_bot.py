import os
import json
import urllib.request
from datetime import datetime, timezone
from collections import defaultdict

TOKEN = os.environ["TG_BOT_TOKEN"]
CHANNEL_USERNAME = "webcontrol_app"
MAIN_PROJECT_URL = "https://stadid.github.io/webcontrol/"
REPO_URL = "https://github.com/stadid/webcontrol/"
API_URL = f"https://api.telegram.org/bot{TOKEN}"
FILE_URL = f"https://api.telegram.org/file/bot{TOKEN}"
IMG_DIR = "images"
FILES_DIR = "files"
DATA_FILE = "data.json"
INDEX_FILE = "index.md"
MAX_BOT_FILE_BYTES = 20 * 1024 * 1024

os.makedirs(IMG_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        posts = json.load(f)
else:
    posts = {}

media_groups = {
    p["media_group_id"]: k
    for k, p in posts.items()
    if p.get("media_group_id")
}

offset = max([int(p.get("update_id", 0)) for p in posts.values()], default=0) + 1

req = urllib.request.urlopen(
    f'{API_URL}/getUpdates?offset={offset}&allowed_updates=["channel_post","edited_channel_post"]'
)
updates = json.loads(req.read().decode("utf-8")).get("result", [])

for upd in updates:
    post = upd.get("channel_post") or upd.get("edited_channel_post")
    if not post:
        continue

    chat = post.get("chat", {})
    if chat.get("username", "").lower() != CHANNEL_USERNAME.lower():
        continue

    msg_id = str(post["message_id"])
    group_id = str(post["media_group_id"]) if post.get("media_group_id") else None
    text = (post.get("text") or post.get("caption") or "").strip()
    date_ts = int(post.get("date", 0))
    date_str = datetime.fromtimestamp(date_ts, tz=timezone.utc).strftime("%Y-%m-%d")

    target_id = media_groups[group_id] if (group_id and group_id in media_groups) else msg_id
    if group_id and group_id not in media_groups:
        media_groups[group_id] = target_id

    existing = posts.get(target_id, {})
    images = existing.get("images", [])
    files = existing.get("files", [])

    if "photo" in post:
        best_photo = post["photo"][-1]
        file_id = best_photo["file_id"]
        file_info = json.loads(
            urllib.request.urlopen(f"{API_URL}/getFile?file_id={file_id}").read().decode("utf-8")
        )
        remote_path = file_info["result"]["file_path"]
        ext = os.path.splitext(remote_path)[1] or ".jpg"
        local_filename = f"{msg_id}_{best_photo['file_unique_id']}{ext}"
        local_path = f"{IMG_DIR}/{local_filename}"

        if not os.path.exists(local_path):
            urllib.request.urlretrieve(f"{FILE_URL}/{remote_path}", local_path)
        if local_path not in images:
            images.append(local_path)

    if "document" in post:
        doc = post["document"]
        if doc.get("file_size", 0) <= MAX_BOT_FILE_BYTES:
            file_id = doc["file_id"]
            orig_name = doc.get("file_name") or f"document_{msg_id}"
            file_info = json.loads(
                urllib.request.urlopen(f"{API_URL}/getFile?file_id={file_id}").read().decode("utf-8")
            )
            remote_path = file_info["result"]["file_path"]
            local_filename = f"{msg_id}_{orig_name}"
            local_path = f"{FILES_DIR}/{local_filename}"

            if not os.path.exists(local_path):
                urllib.request.urlretrieve(f"{FILE_URL}/{remote_path}", local_path)
            if not any(f["path"] == local_path for f in files):
                files.append({"name": orig_name, "path": local_path})

    if group_id:
        captions = existing.get("captions", {})
        if not captions and existing.get("text"):
            captions[target_id] = existing["text"]
        if text:
            captions[msg_id] = text
        elif msg_id in captions:
            del captions[msg_id]
        ordered_texts = [
            captions[k] for k in sorted(captions.keys(), key=int) if captions[k]
        ]
        final_text = "\n\n".join(dict.fromkeys(ordered_texts))
    else:
        captions = {}
        final_text = text

    posts[target_id] = {
        "update_id": upd["update_id"],
        "message_id": int(target_id),
        "media_group_id": group_id,
        "date": existing.get("date", date_str),
        "timestamp": existing.get("timestamp", date_ts),
        "text": final_text,
        "captions": captions,
        "images": images,
        "files": files
    }

with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(posts, f, ensure_ascii=False, indent=2)

# Сортируем в хронологическом порядке для склейки альбомов без media_group_id
chronological_posts = [
    p for p in sorted(posts.values(), key=lambda x: x["message_id"])
    if p.get("text") or p.get("images") or p.get("files")
]

merged_posts = []
for p in chronological_posts:
    can_merge = False
    if merged_posts and not p.get("text") and not p.get("files") and p.get("images"):
        prev = merged_posts[-1]
        ts_curr = int(p.get("timestamp", 0))
        ts_prev = int(prev.get("last_timestamp", prev.get("timestamp", 0)))
        
        if ts_curr > 0 and ts_prev > 0:
            # Точная проверка: склеиваем только если фото отправлены в пределах 2 минут (120 сек)
            can_merge = abs(ts_curr - ts_prev) <= 120
        else:
            # Запасной вариант для записей без timestamp: одна дата и подряд идущие ID
            can_merge = (
                prev["date"] == p["date"]
                and (p["message_id"] - prev.get("last_msg_id", prev["message_id"])) <= 5
            )

    if can_merge:
        for img in p["images"]:
            if img not in merged_posts[-1]["images"]:
                merged_posts[-1]["images"].append(img)
        merged_posts[-1]["last_msg_id"] = p["message_id"]
        if p.get("timestamp"):
            merged_posts[-1]["last_timestamp"] = p["timestamp"]
    else:
        item = dict(p)
        item["images"] = list(p.get("images", []))
        item["files"] = list(p.get("files", []))
        item["last_msg_id"] = p["message_id"]
        item["last_timestamp"] = p.get("timestamp", 0)
        merged_posts.append(item)

sorted_posts = list(reversed(merged_posts))

by_year = defaultdict(list)
for p in sorted_posts:
    year_key = p["date"][:4]
    by_year[year_key].append(p)

# HTML/CSS/JS для всплывающего окна (лайтбокса)
LIGHTBOX_SNIPPET = """
<div id="tg-lightbox" onclick="closeTgLightbox()" style="display:none; position:fixed; z-index:9999; left:0; top:0; width:100%; height:100%; background:rgba(0,0,0,0.85); align-items:center; justify-content:center; cursor:zoom-out; padding:20px; box-sizing:border-box;">
  <span style="position:fixed; top:16px; right:24px; color:#fff; font-size:32px; font-weight:bold; cursor:pointer; user-select:none;">&times;</span>
  <img id="tg-lightbox-img" src="" alt="Полный размер" style="max-width:95vw; max-height:92vh; border-radius:6px; box-shadow:0 4px 24px rgba(0,0,0,0.6); cursor:default;" onclick="event.stopPropagation()">
</div>
<script>
function openTgLightbox(src) {
  var lb = document.getElementById('tg-lightbox');
  document.getElementById('tg-lightbox-img').src = src;
  lb.style.display = 'flex';
}
function closeTgLightbox() {
  document.getElementById('tg-lightbox').style.display = 'none';
}
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeTgLightbox();
});
</script>
"""

def render_post(p):
    lines = [f"### {p['date']}", ""]
    if p["text"]:
        lines.extend([p["text"], ""])
    if p.get("images"):
        thumbs = []
        for img in p["images"]:
            thumbs.append(
                f'<img src="./{img}" alt="Изображение к посту" onclick="openTgLightbox(this.src)" title="Нажмите для увеличения" '
                f'style="max-height: 220px; max-width: 100%; width: auto; height: auto; border-radius: 6px; margin: 0 8px 8px 0; border: 1px solid #d0d7de; cursor: zoom-in;">'
            )
        lines.extend(["".join(thumbs), ""])
    for doc in p.get("files", []):
        lines.extend([
            f'📎 **Вложение:** [{doc["name"]}](./{doc["path"]})',
            ""
        ])
    lines.extend([
        f"[Открыть в Telegram](https://t.me/{CHANNEL_USERNAME}/{p['message_id']})",
        "",
        "---",
        ""
    ])
    return lines

sorted_years = sorted(by_year.keys(), reverse=True)

def build_archive_nav(current_year=None):
    if not sorted_years:
        return ""
    links = []
    for y in sorted_years:
        count = len(by_year[y])
        if y == current_year:
            links.append(f"**{y} ({count})**")
        else:
            links.append(f"[{y}](./{y}.html) ({count})")
    return "**Архив по годам:** " + " • ".join(links)

for year in sorted_years:
    year_lines = [
        f"## Новости Webcontrol — {year} год",
        "",
        f"[← Свежие новости](./) | [Главная страница Webcontrol]({MAIN_PROJECT_URL}) | [Репозиторий GitHub]({REPO_URL})",
        "",
        "---",
        ""
    ]
    for p in by_year[year]:
        year_lines.extend(render_post(p))
    
    # Добавляем навигацию по годам в конец архивного файла (текущий год — жирным, остальные — ссылками)
    year_lines.extend([build_archive_nav(current_year=year), ""])
    year_lines.append(LIGHTBOX_SNIPPET)
    
    with open(f"{year}.md", "w", encoding="utf-8") as f:
        f.write("\n".join(year_lines))

archive_nav = build_archive_nav()
main_lines = [
    f"[Главная страница Webcontrol]({MAIN_PROJECT_URL}) | [Репозиторий GitHub]({REPO_URL}) | [Канал в Telegram](https://t.me/{CHANNEL_USERNAME})",
    "",
    archive_nav,
    "",
    "---",
    ""
]

for p in sorted_posts[:15]:
    main_lines.extend(render_post(p))

if len(sorted_posts) > 15:
    main_lines.extend([archive_nav, ""])

main_lines.append(LIGHTBOX_SNIPPET)

with open(INDEX_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(main_lines))

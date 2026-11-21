import os
import json
import urllib.request
from datetime import datetime, timezone
from collections import defaultdict

TOKEN = os.environ["TG_BOT_TOKEN"]
CHANNEL_USERNAME = "webcontrol_app"
MAIN_PROJECT_URL = "https://stadid.github.io/webcontrol/"
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
    date_ts = post.get("date", 0)
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
        "text": final_text,
        "captions": captions,
        "images": images,
        "files": files
    }

with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(posts, f, ensure_ascii=False, indent=2)

sorted_posts = [
    p for p in sorted(posts.values(), key=lambda x: x["message_id"], reverse=True)
    if p.get("text") or p.get("images") or p.get("files")
]

by_year = defaultdict(list)
for p in sorted_posts:
    year_key = p["date"][:4]
    by_year[year_key].append(p)

def render_post(p):
    lines = [f"### {p['date']}", ""]
    if p["text"]:
        lines.extend([p["text"], ""])
    for img in p.get("images", []):
        lines.extend([
            f'<img src="./{img}" alt="Изображение к посту" style="max-width: 550px; width: 100%; height: auto; border-radius: 6px;">',
            ""
        ])
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

archive_links = []
for year in sorted(by_year.keys(), reverse=True):
    archive_links.append(f"[{year}](./{year}.html) ({len(by_year[year])})")
    year_lines = [
        f"# Новости Webcontrol — {year} год",
        "",
        f"[← Свежие новости](./) | [Главная страница Webcontrol]({MAIN_PROJECT_URL}) | [Репозиторий GitHub](https://github.com/stadid/webcontrol)",
        "",
        "---",
        ""
    ]
    for p in by_year[year]:
        year_lines.extend(render_post(p))
    with open(f"{year}.md", "w", encoding="utf-8") as f:
        f.write("\n".join(year_lines))

archive_nav = "**Архив по годам:** " + " • ".join(archive_links) if archive_links else ""
main_lines = [
    "",
    f"[Главная страница Webcontrol]({MAIN_PROJECT_URL}) | [Репозиторий GitHub](https://github.com/stadid/webcontrol) | [Канал в Telegram](https://t.me/{CHANNEL_USERNAME})",
    "",
    archive_nav,
    "",
    "---",
    ""
]

for p in sorted_posts[:15]:
    main_lines.extend(render_post(p))

if len(sorted_posts) > 15:
    main_lines.extend(["### Полный архив публикаций", "", archive_nav, ""])

with open(INDEX_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(main_lines))

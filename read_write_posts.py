# read_write_posts.py

import requests
import time
import os
import json
import re
import sys
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Constants ---
CACHE_DIR = "cache"


def show_progress(current, total, bar_length=30):
    """在控制台显示一个进度条。"""
    if total == 0:
        percent = 1.0
    else:
        percent = current / total
    filled_len = int(round(bar_length * percent))
    bar = "■" * filled_len + "□" * (bar_length - filled_len)
    percent_display = int(percent * 100)
    sys.stdout.write(f"\r下载进度: {bar} ({current}/{total}, {percent_display}%) ")
    sys.stdout.flush()


def clean_post_data(base_url, post):
    """清理单个帖子字典。"""
    raw_content = post.get("cooked", "")
    cleaned_content = re.sub(r"<blockquote.*?/blockquote>|<[^>]+>", "", raw_content, flags=re.DOTALL).strip()
    return {
        "post_number": post.get("post_number"),
        "user_id": post.get("user_id"),
        "username": post.get("username"),
        "created_at": post.get("created_at"),
        "reply_to_post_number": post.get("reply_to_post_number"),
        "reply_content": cleaned_content,
        "original_post_url": f'{base_url}/t/topic/{post.get("topic_id")}/{post.get("post_number")}'
    }


def get_main_post(all_posts):
    """查找主贴。"""
    for post in all_posts:
        if post.get("post_number") == 1:
            return post
    return None


def group_and_sort_replies_by_user(base_url, all_posts):
    """按用户分组和排序回复。"""
    replies_only = [p for p in all_posts if p.get("post_number", 0) > 1]
    users = {}
    for post in replies_only:
        user_id = post.get("user_id")
        if user_id not in users:
            users[user_id] = {
                "username": post.get("username"),
                "user_id": user_id,
                "replies": [],
                "first_post_num": float("inf"),
            }
        cleaned_reply = clean_post_data(base_url, post)
        users[user_id]["replies"].append(cleaned_reply)
        if cleaned_reply["post_number"] < users[user_id]["first_post_num"]:
            users[user_id]["first_post_num"] = cleaned_reply["post_number"]
    for user_id in users:
        users[user_id]["replies"].sort(key=lambda r: r["post_number"])
    sorted_users_list = sorted(users.values(), key=lambda u: u["first_post_num"])
    for user_data in sorted_users_list:
        del user_data["first_post_num"]
    return sorted_users_list


def _write_derived_files(topic_id,base_url, all_posts_raw):
    """写入派生文件。"""
    try:
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)

        grouped_data = group_and_sort_replies_by_user(base_url, all_posts_raw)
        grouped_path = os.path.join(CACHE_DIR, f"{topic_id}_ai_input_file.json")
        readable_path = os.path.join(CACHE_DIR, f"{topic_id}_readable.txt")

        with open(grouped_path, "w", encoding="utf-8") as f:
            json.dump(grouped_data, f, ensure_ascii=False, indent=4)

        with open(readable_path, "w", encoding="utf-8") as f:
            for user_data in grouped_data:
                f.write(f'"username": "{user_data.get("username", "N/A")}"\n')
                for reply in user_data.get("replies", []):
                    f.write(
                        f"{reply.get('created_at', 'N/A')}: {reply.get('reply_content', '').replace('n', ' ')}\n"
                    )
                f.write("\n")

        print(f"成功将处理后的派生文件保存到 ./{CACHE_DIR}/ 目录中。")
    except (IOError, OSError) as e:
        print(f"错误: 写入派生缓存文件失败: {e}")


def get_all_posts(base_url, topic_id, config):
    """获取所有帖子，使用正确的分页逻辑。"""
    cache_hours = config.get("CACHE_DURATION_HOURS", 24)
    max_retries = config.get("MAX_RETRIES", 5)
    backoff_factor = config.get("BACKOFF_FACTOR", 1)
    raw_cache_path = os.path.join(CACHE_DIR, "internal", f"{topic_id}_raw.json")
    all_posts_raw = None

    if os.path.exists(raw_cache_path):
        try:
            file_mod_time = os.path.getmtime(raw_cache_path)
            age_seconds = time.time() - file_mod_time
            if age_seconds < (cache_hours * 3600):
                print(f"缓存命中。正在从 '{raw_cache_path}' 加载帖子。")
                with open(raw_cache_path, "r", encoding="utf-8") as f:
                    all_posts_raw = json.load(f)
            else:
                print("原始缓存文件已过期，将从网络重新获取。")
        except (IOError, json.JSONDecodeError) as e:
            print(
                f"警告: 无法读取或解析缓存文件 '{raw_cache_path}' ({e})。将从网络获取。"
            )

    if not all_posts_raw:
        print(f"正在从网络获取 topic_id: {topic_id} 的所有帖子...")
        fetched_posts = []
        # --- 修正点 1: 分页从 1 开始 ---
        page = 1
        total_posts_count = 0

        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        session.headers.update(headers)
        retries = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[500, 502, 503, 504],
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))

        try:
            while True:
                url = f"{base_url}/t/{topic_id}.json?page={page}"
                response = session.get(url, timeout=15)
                response.raise_for_status()
                data = response.json()

                # --- 修正点 2: 检查 page 是否为 1 ---
                if page == 1:
                    total_posts_count = data.get("posts_count", 0)
                    if total_posts_count == 0:
                        print("\n错误: 未找到任何帖子，或帖子URL无效。")
                        return None

                posts = data.get("post_stream", {}).get("posts", [])
                if not posts:
                    break

                fetched_posts.extend(posts)
                show_progress(len(fetched_posts), total_posts_count)

                if len(fetched_posts) >= total_posts_count:
                    break

                page += 1
                time.sleep(0.2)

            print()

            if fetched_posts:
                all_posts_raw = fetched_posts
                if not os.path.exists(CACHE_DIR):
                    os.makedirs(CACHE_DIR)
                with open(raw_cache_path, "w", encoding="utf-8") as f:
                    json.dump(all_posts_raw, f, ensure_ascii=False, indent=4)
                print(f"成功将新的原始数据写入缓存: '{raw_cache_path}'")

        except requests.exceptions.RequestException as e:
            print()
            print(f"网络请求或解析错误: {e}")
            return None

    if all_posts_raw:
        _write_derived_files(topic_id,base_url, all_posts_raw)

    return all_posts_raw


def generate_prompt(post_id, user_credit_history):
    with open("prompt_template.md", "r", encoding="utf-8") as f:
        prompt_template = f.read()
        prompt = prompt_template.replace("{{user_credit_history}}", user_credit_history)
        with open(
            os.path.join(CACHE_DIR, f"{post_id}_prompt.md"), "w", encoding="utf-8"
        ) as f2:
            f2.write(prompt)

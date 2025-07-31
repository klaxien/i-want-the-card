# read_write_posts.py

import time
import os
import json
import re
import sys
import certifi
import cloudscraper
import requests.exceptions


def get_internal_path(relative_path):
    """
    获取打包到.exe内部的资源的路径。
    运行时会被解压到临时目录。
    """
    try:
        # PyInstaller 创建一个临时文件夹，并将路径存储在 _MEIPASS 中
        base_path = sys._MEIPASS
    except Exception:
        # 在开发环境中，_MEIPASS 不存在，使用当前文件所在目录
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_persistent_path(relative_path):
    """
    获取.exe或.app文件旁边（外部）的持久化存储路径。
    用于创建缓存等不会被删除的文件/目录。
    """
    if getattr(sys, "frozen", False):
        # 如果是打包状态 (frozen)
        if sys.platform == "darwin":
            # 对于 macOS, sys.executable 在 .app 包的内部
            # 例如: /path/to/AppName.app/Contents/MacOS/AppName
            # 我们需要回到 .app 文件所在的目录，也就是向上三级
            base_path = os.path.abspath(
                os.path.join(os.path.dirname(sys.executable), "..", "..", "..")
            )
        else:
            # 对于 Windows 或 Linux，可执行文件通常与资源文件在同一目录
            base_path = os.path.dirname(sys.executable)
    else:
        # 如果是开发环境（非打包状态）
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


# --- Constants ---
CACHE_DIR = get_persistent_path("cache")

# show_progress 函数已被移除，其功能由GUI进度条替代


def clean_post_data(base_url, post):
    """清理单个帖子字典。"""
    raw_content = post.get("cooked", "")
    cleaned_content = re.sub(
        r"<blockquote.*?/blockquote>|<[^>]+>", "", raw_content, flags=re.DOTALL
    ).strip()
    return {
        "post_number": post.get("post_number"),
        "user_id": post.get("user_id"),
        "username": post.get("username"),
        "created_at": post.get("created_at"),
        "reply_to_post_number": post.get("reply_to_post_number"),
        "reply_content": cleaned_content,
        "original_post_url": f'{base_url}/t/topic/{post.get("topic_id")}/{post.get("post_number")}',
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


def _write_derived_files(topic_id, base_url, all_posts_raw):
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


def get_all_posts(
    base_url, topic_id, config, progress_callback=None
):  # 新增 progress_callback
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
                print(
                    f"缓存命中。正在从 '{os.path.basename(raw_cache_path)}' 加载帖子。"
                )
                with open(raw_cache_path, "r", encoding="utf-8") as f:
                    all_posts_raw = json.load(f)
                # 如果从缓存加载，也更新一下进度条到100%
                if progress_callback:
                    progress_callback(1, 1)  # (current, total)
            else:
                print("缓存文件已过期，将从网络重新获取。")
        except (IOError, json.JSONDecodeError) as e:
            print(f"警告: 无法读取或解析缓存文件 ({e})。将从网络获取。")

    if not all_posts_raw:
        # 用 sys.stdout.write 以避免被重定向器添加不必要的换行符
        sys.stdout.write(f"正在从网络获取 topic_id: {topic_id} 的所有帖子...\n")
        fetched_posts = []
        page = 1
        total_posts_count = 0

        scraper = cloudscraper.create_scraper()

        if config.get("EnableCustomUserAgent") and config.get("CustomUserAgent"):
            user_agent = config["CustomUserAgent"]
            print(f"已启用自定义 User-Agent: {user_agent}")
            headers = {
                "User-Agent": user_agent
            }
            scraper.headers.update(headers)

        try:
            while True:
                url = f"{base_url}/t/{topic_id}.json?page={page}"
                response = None

                for attempt in range(max_retries):
                    try:
                        response = scraper.get(url, timeout=15, verify=certifi.where())
                        response.raise_for_status()
                        break
                    except requests.exceptions.RequestException as e:
                        is_retryable_http_error = isinstance(
                            e, requests.exceptions.HTTPError
                        ) and e.response.status_code in [500, 502, 504]
                        is_connection_error = not isinstance(
                            e, requests.exceptions.HTTPError
                        )

                        if attempt == max_retries - 1 or not (
                            is_retryable_http_error or is_connection_error
                        ):
                            raise e

                        wait_time = backoff_factor * (2**attempt)
                        # 使用 print 来输出到GUI日志
                        print(
                            f"请求失败 ({str(e)}), {wait_time:.1f}秒后重试 (第 {attempt + 1}/{max_retries} 次)..."
                        )
                        time.sleep(wait_time)

                if response is None:
                    print("\n错误：所有重试尝试均失败。")
                    return None

                data = response.json()

                if page == 1:
                    total_posts_count = data.get("posts_count", 0)
                    if total_posts_count == 0:
                        print("\n错误: 未找到任何帖子，或帖子URL无效。")
                        return None

                posts = data.get("post_stream", {}).get("posts", [])
                if not posts:
                    break

                fetched_posts.extend(posts)

                # 调用回调函数来更新GUI进度条
                if progress_callback:
                    progress_callback(len(fetched_posts), total_posts_count)

                if len(fetched_posts) >= total_posts_count:
                    break

                page += 1
                time.sleep(0.2)

            # 确保进度条在循环结束后显示为100%
            if progress_callback:
                progress_callback(total_posts_count, total_posts_count)

            if fetched_posts:
                all_posts_raw = fetched_posts
                raw_cache_directory = os.path.dirname(raw_cache_path)
                os.makedirs(raw_cache_directory, exist_ok=True)
                with open(raw_cache_path, "w", encoding="utf-8") as f:
                    json.dump(all_posts_raw, f, ensure_ascii=False, indent=4)
                print(
                    f"\n成功将新的原始数据写入缓存: '{os.path.basename(raw_cache_path)}'"
                )

        except (
            requests.exceptions.RequestException,
            cloudscraper.exceptions.CloudflareException,
        ) as e:
            print(f"\n网络请求或解析错误: {e}")
            if isinstance(e, cloudscraper.exceptions.CloudflareException):
                print("检测到Cloudflare保护。Cloudscraper未能通过质询。")
            return None

    if all_posts_raw:
        _write_derived_files(topic_id, base_url, all_posts_raw)

    return all_posts_raw


def generate_prompt(topic_id, user_credit_history):
    """根据模板和用户输入生成最终的prompt文件。"""
    template_path = get_internal_path("prompt_template.md")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
    except IOError as e:
        print(f"错误：无法读取prompt模板文件: {e}")
        return

    prompt = prompt_template.replace("{{user_credit_history}}", user_credit_history)
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

    try:
        with open(
                os.path.join(CACHE_DIR, f"{topic_id}_prompt.md"), "w", encoding="utf-8"
        ) as f2:
            f2.write(prompt)
    except IOError as e:
        print(f"错误：无法写入prompt文件: {e}")
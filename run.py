import re
import sys  # 导入 sys 模块
import yaml
from read_write_posts import (
    get_all_posts,
    get_main_post,
    generate_prompt,
    clean_post_data,
)


def load_config(path="config.yaml"):
    """加载并验证YAML配置文件。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except (IOError, yaml.YAMLError) as e:
        print(f"错误: 无法加载或解析配置文件 '{path}': {e}")
        sys.exit(1)

    # (验证逻辑保持不变)
    if "CACHE_DURATION_HOURS" not in config or not isinstance(
        config["CACHE_DURATION_HOURS"], int
    ):
        sys.exit(f"错误: 配置文件 '{path}' 中缺少或无效的 'CACHE_DURATION_HOURS'。")
    if "BASE_URL" not in config or not isinstance(config["BASE_URL"], str):
        sys.exit(f"错误: 配置文件 '{path}' 中缺少或无效的 'BASE_URL'。")
    if "MAX_RETRIES" not in config or not isinstance(config["MAX_RETRIES"], int):
        config["MAX_RETRIES"] = 5
    if "BACKOFF_FACTOR" not in config or not isinstance(
        config["BACKOFF_FACTOR"], (int, float)
    ):
        config["BACKOFF_FACTOR"] = 1
    return config


def main():
    """主执行函数。"""
    config = load_config()
    cache_hours = config.get("CACHE_DURATION_HOURS")
    base_url = config.get("BASE_URL")

    duration_str = (
        f"{cache_hours // 24}天"
        if cache_hours % 24 == 0 and cache_hours >= 24
        else f"{cache_hours}小时"
    )
    print(
        f"--- \n当前配置：【{duration_str}】内重复请求同一个帖子时，将优先使用缓存。\n---"
    )

    post_url = input(
        "请输入帖子的URL（如https://www.uscardforum.com/t/topic/406078）: "
    )
    match = re.search(r"/t/(?:topic/)?(\d+)", post_url)
    if not match:
        print(
            f"错误：无法从输入的URL中找到有效的 topic_id。\n请确保URL格式正确, 例如: {base_url}/t/topic/12345"
        )
        return

    # --- 主要修改部分 ---
    print("\n请输入你的开卡需求以及信用记录 (可直接复制粘贴多行):")
    print("粘贴完成后，请按以下组合键结束输入:")
    print("  - Windows: Ctrl+Z 然后按 Enter")
    print("  - macOS / Linux: Ctrl+D")

    # 从标准输入一次性读取所有内容，直到遇到EOF
    user_credit_history = sys.stdin.read()

    # strip() 可以去除前后可能存在的空白，包括换行符
    if not user_credit_history.strip():
        print("错误：未输入任何内容。程序终止。")
        return
    # --- 修改部分结束 ---

    topic_id = match.group(1)
    print(f"\n成功提取 topic_id: {topic_id}")

    all_posts_raw = get_all_posts(base_url, topic_id, config)
    if not all_posts_raw:
        print("未能获取任何帖子内容，程序终止。")
        return

    print(f"\n成功获取或加载 {len(all_posts_raw)} 个帖子的内容.")

    # --- 数据处理与显示 ---
    print("\n" + "=" * 25 + "\n  主贴内容预览\n" + "=" * 25)
    main_post_raw = get_main_post(all_posts_raw)
    if main_post_raw:
        main_post_cleaned = clean_post_data(main_post_raw)
        print(
            f"作者: {main_post_cleaned.get('username')} (ID: {main_post_cleaned.get('user_id')})"
        )
        print(f"发布于: {main_post_cleaned.get('created_at')}")
        print(
            f"内容预览: {main_post_cleaned.get('reply_content', '')[:200].strip()}..."
        )
    else:
        print("错误：未在本话题中找到主贴 (post_number == 1)。")

    generate_prompt(topic_id, user_credit_history)
    # --- 文件名格式已更改 ---
    print(f"\n处理后的文件已保存到 cache/ 目录中：")
    print(f"  - cache/{topic_id}_ai_input_file.json <-此文件**上传**到输入框")
    print(f"  - cache/{topic_id}_prompt.md <-此文件内容**复制粘贴**到输入框")


if __name__ == "__main__":
    main()

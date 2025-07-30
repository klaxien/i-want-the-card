# run.py

import re
import sys
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk
import yaml
import threading
import traceback
import queue

from read_write_posts import (
    get_all_posts,
    get_main_post,
    generate_prompt,
    clean_post_data,
    get_persistent_path,
)


# 用于将print输出重定向到GUI的文本框
class TextRedirector(object):
    def __init__(self, widget):
        self.widget = widget
        self.widget.configure(state="disabled")

    def write(self, s):
        self.widget.configure(state="normal")
        self.widget.insert(tk.END, s)
        self.widget.see(tk.END)  # 自动滚动到底部
        self.widget.update_idletasks()  # 实时更新UI
        self.widget.configure(state="disabled")

    def flush(self):
        # 在GUI环境中，flush通常是无操作的
        pass


class App:
    def __init__(self, window):
        self.window = window
        self.window.title("NiTanPreapproval")
        self.setup_ui()

        # 将 sys.stdout 和 sys.stderr 重定向到日志文本框
        self.log_redirector = TextRedirector(self.log_text)
        sys.stdout = self.log_redirector
        sys.stderr = self.log_redirector

        # 用于从工作线程向主线程传递消息的队列
        self.queue = queue.Queue()
        self.window.after(100, self.process_queue)

    def setup_ui(self):
        # --- 窗口居中和尺寸设置 ---
        window_width = 750
        window_height = 650
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        center_x = int(screen_width / 2 - window_width / 2)
        center_y = int(screen_height / 2 - window_height / 2)
        self.window.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}")
        self.window.minsize(600, 500)
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)

        # --- 主框架 ---
        main_frame = tk.Frame(self.window)
        main_frame.pack(padx=15, pady=15, fill="both", expand=True)
        main_frame.grid_rowconfigure(2, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        # --- 1. 输入部分 ---
        input_frame = tk.LabelFrame(main_frame, text="输入信息")
        input_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        input_frame.grid_columnconfigure(1, weight=1)

        url_label = tk.Label(input_frame, text="帖子 URL:")
        url_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.url_entry = tk.Entry(input_frame, width=70)
        self.url_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        self.url_entry.focus_set()

        history_label = tk.Label(
            input_frame,
            text="开卡需求及信用记录:\n(推荐严格按照DP贴格式)",
            justify=tk.LEFT,
        )
        history_label.grid(row=1, column=0, padx=10, pady=5, sticky="nw")
        self.history_text = scrolledtext.ScrolledText(
            input_frame, wrap=tk.WORD, height=8
        )
        self.history_text.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

        # --- 2. 控制和进度部分 ---
        control_frame = tk.Frame(main_frame)
        control_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=5)
        control_frame.grid_columnconfigure(0, weight=1)

        self.progress_bar = ttk.Progressbar(
            control_frame, orient="horizontal", length=100, mode="determinate"
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.run_button = tk.Button(
            control_frame, text="开始分析", command=self.start_analysis_thread, width=15
        )
        self.run_button.grid(row=0, column=1)

        # --- 3. 日志输出部分 ---
        log_frame = tk.LabelFrame(main_frame, text="处理日志")
        log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        log_frame.grid_rowconfigure(0, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, state="normal"
        )
        self.log_text.pack(expand=True, fill="both", padx=5, pady=5)

    def update_progress(self, current, total):
        if total > 0:
            percentage = (current / total) * 100
            self.progress_bar["value"] = percentage
            self.window.update_idletasks()

    def process_queue(self):
        """处理来自工作线程的消息队列"""
        try:
            while True:
                task = self.queue.get_nowait()
                task()
        except queue.Empty:
            pass
        finally:
            self.window.after(100, self.process_queue)

    def show_message(self, title, message, type="info"):
        """线程安全地显示消息框"""
        if type == "error":
            messagebox.showerror(title, message)
        elif type == "warning":
            messagebox.showwarning(title, message)
        else:
            messagebox.showinfo(title, message)

    def start_analysis_thread(self):
        url = self.url_entry.get().strip()
        history = self.history_text.get("1.0", tk.END).strip()

        # --- 验证输入 ---
        if not url or not history:
            messagebox.showwarning("输入错误", "URL 和信用记录均不能为空！")
            return

        match = re.search(r"/t/(?:topic/)?(\d+)", url)
        if not match:
            messagebox.showerror(
                "URL格式错误",
                f"无法从输入的URL '{url}' 中找到有效的 topic_id。\n\n"
                "请确保URL格式正确, 例如:\n"
                "https://www.uscardforum.com/t/topic/12345",
            )
            return

        topic_id = match.group(1)

        # --- 禁用输入和按钮，启动线程 ---
        self.run_button.config(state="disabled")
        self.url_entry.config(state="disabled")
        self.history_text.config(state="disabled")
        self.progress_bar["value"] = 0

        # 清空之前的日志
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

        print("--- 分析开始 ---\n")

        # 在新线程中运行耗时任务
        self.analysis_thread = threading.Thread(
            target=self.run_analysis_task, args=(url, history, topic_id)
        )
        self.analysis_thread.daemon = True
        self.analysis_thread.start()

    def run_analysis_task(self, post_url, user_credit_history, topic_id):
        try:
            config = load_config()
            cache_hours = config.get("CACHE_DURATION_HOURS")
            base_url = config.get("BASE_URL")

            duration_str = (
                f"{cache_hours // 24}天"
                if cache_hours % 24 == 0 and cache_hours >= 24
                else f"{cache_hours}小时"
            )
            print(f"配置加载成功。缓存有效期: {duration_str}")
            print(f"输入验证通过。准备处理 Topic ID: {topic_id}\n")
            print("开始获取帖子内容...")

            # 将GUI更新函数作为回调传递
            all_posts_raw = get_all_posts(
                base_url, topic_id, config, progress_callback=self.update_progress
            )

            if not all_posts_raw:
                print("\n未能获取任何帖子内容，程序终止。")
                self.queue.put(
                    lambda: self.show_message(
                        "错误", "未能获取任何帖子内容，请检查URL或网络连接。", "error"
                    )
                )
                return

            print(f"\n成功获取或加载 {len(all_posts_raw)} 个帖子的内容.")
            print("\n" + "=" * 25 + "\n  主贴内容预览\n" + "=" * 25)

            main_post_raw = get_main_post(all_posts_raw)
            if main_post_raw:
                main_post_cleaned = clean_post_data(
                    base_url=base_url, post=main_post_raw
                )
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

            print("\n\n" + "=" * 15 + " 处理完成 " + "=" * 15)
            print("文件已成功保存到 cache/ 目录中：")
            generated_json_path = f"cache/{topic_id}_ai_input_file.json"
            generated_prompt_path = f"cache/{topic_id}_prompt.json"
            print(f"  - {generated_json_path}")
            print(f"  - {generated_prompt_path}")
            print("\n您现在可以关闭此窗口。")

            self.queue.put(
                lambda: self.show_message(
                    "成功",
                    f"分析完成！\n\n相关文件已生成在 cache 目录中。\n\n{generated_json_path}\n\n{generated_prompt_path}",
                    "info",
                )
            )

        except Exception as e:
            # 打印详细错误到日志窗口
            print(f"\n发生未处理的严重错误: {e}")
            traceback.print_exc()
            self.queue.put(
                lambda: self.show_message(
                    "严重错误",
                    f"发生未处理的错误，请查看日志窗口获取详情。\n\n错误: {e}",
                    "error",
                )
            )

        finally:
            # 无论成功或失败，都重新启用按钮
            self.queue.put(lambda: self.run_button.config(state="normal"))
            self.queue.put(lambda: self.url_entry.config(state="normal"))
            self.queue.put(lambda: self.history_text.config(state="normal"))

    def on_close(self):
        """关闭窗口时的确认"""
        # 如果分析线程正在运行，给出提示
        if hasattr(self, "analysis_thread") and self.analysis_thread.is_alive():
            if messagebox.askyesno("确认退出", "分析仍在进行中，确定要退出吗？"):
                self.window.destroy()
        else:
            self.window.destroy()


def load_config(path="config.yaml"):
    """加载并验证YAML配置文件。"""
    config_path = get_persistent_path(path)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except (IOError, yaml.YAMLError) as e:
        # 抛出异常而不是打印和退出
        raise ValueError(f"无法加载或解析配置文件 '{config_path}': {e}")

    if "CACHE_DURATION_HOURS" not in config or not isinstance(
        config["CACHE_DURATION_HOURS"], int
    ):
        raise ValueError(f"配置文件 '{path}' 中缺少或无效的 'CACHE_DURATION_HOURS'。")
    if "BASE_URL" not in config or not isinstance(config["BASE_URL"], str):
        raise ValueError(f"配置文件 '{path}' 中缺少或无效的 'BASE_URL'。")
    if "MAX_RETRIES" not in config or not isinstance(config["MAX_RETRIES"], int):
        config["MAX_RETRIES"] = 5
    if "BACKOFF_FACTOR" not in config or not isinstance(
        config["BACKOFF_FACTOR"], (int, float)
    ):
        config["BACKOFF_FACTOR"] = 1
    return config


def main():
    """主执行函数，现在只负责创建和运行GUI。"""
    try:
        root = tk.Tk()
        app = App(root)
        root.mainloop()
    except Exception as e:
        # 这个捕获是为了在GUI完全无法启动时提供一个最后的反馈
        messagebox.showerror("致命错误", f"无法启动应用程序GUI: {e}")
        # 写入一个本地文件以供调试
        with open("gui_startup_error.log", "w") as f:
            f.write(traceback.format_exc())


if __name__ == "__main__":
    main()

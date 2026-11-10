# Windows 下浏览器标签页检测与控制模块
# 支持 Chrome、Edge、Brave

import win32gui
import win32con
import win32clipboard
import pywinauto
from pywinauto.keyboard import send_keys
import ctypes
import os
import time

# 浏览器窗口标题关键字与类名映射
BROWSER_PROFILES = {
    "chrome": {"title_keyword": "Google Chrome", "class_name": "Chrome_WidgetWin_1"},
    "edge":   {"title_keyword": "Microsoft Edge", "class_name": "Chrome_WidgetWin_1"},
    "brave":  {"title_keyword": "Brave",           "class_name": "Chrome_WidgetWin_1"},
}


# ---------------- 基础工具函数 ----------------

def get_browser_windows(browser_name):
    """获取指定浏览器的所有窗口包装对象。"""
    profile = BROWSER_PROFILES.get(browser_name.lower())
    if not profile:
        raise ValueError(f"不支持的浏览器: {browser_name}")
    desktop = pywinauto.Desktop(backend="uia")
    return desktop.windows(
        title_re=f".*{profile['title_keyword']}.*",
        class_name=profile["class_name"],
        control_type="Window",
    )


def get_tabs_from_window(window):
    """从一个浏览器窗口中提取所有标签页的标题。"""
    tabs = []
    try:
        for idx, tab in enumerate(window.descendants(control_type="TabItem")):
            title = tab.window_text()
            if title:
                tabs.append({"index": idx, "title": title})
    except Exception as e:
        print(f"[警告] 获取标签页失败: {e}")
    return tabs


def get_all_tabs(browser_name=None):
    """获取所有（或指定）浏览器的标签页。"""
    browsers = [browser_name.lower()] if browser_name else list(BROWSER_PROFILES.keys())
    result = {}
    for b_name in browsers:
        windows = get_browser_windows(b_name)
        all_tabs = []
        for win in windows:
            all_tabs.extend(get_tabs_from_window(win))
        if all_tabs:
            result[b_name] = all_tabs
    return result


def _bring_window_to_front(hwnd):
    """把窗口置前（含最小化恢复、绕过前台限制）。"""
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False


def _set_clipboard_text(text):
    """把文字写入剪贴板（用于可靠地粘贴中文/特殊字符/路径）。"""
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()


def _find_window_by_title(title_keyword):
    target = None
    def callback(hwnd, _):
        nonlocal target
        if not win32gui.IsWindowVisible(hwnd):
            return True
        if title_keyword in win32gui.GetWindowText(hwnd):
            target = hwnd
            return False
        return True
    win32gui.EnumWindows(callback, None)
    return target


# ---------------- 通用操作接口 ----------------

def activate_window(title_keyword):
    """将标题包含指定关键字的窗口置于前台。"""
    hwnd = _find_window_by_title(title_keyword)
    if not hwnd:
        return False
    return _bring_window_to_front(hwnd)


def switch_to_tab(tab_index, browser_name="chrome"):
    """切换到指定浏览器的指定标签页。"""
    profile = BROWSER_PROFILES.get(browser_name.lower())
    if not profile:
        raise ValueError(f"不支持的浏览器: {browser_name}")
    if not activate_window(profile["title_keyword"]):
        print(f"[错误] 无法激活 {browser_name} 窗口")
        return False
    time.sleep(0.3)
    windows = get_browser_windows(browser_name)
    if not windows:
        print(f"[错误] 未找到 {browser_name} 窗口")
        return False
    try:
        tab_items = windows[0].descendants(control_type="TabItem")
        if tab_index < 0 or tab_index >= len(tab_items):
            print(f"[错误] 标签页索引 {tab_index} 超出范围")
            return False
        tab_items[tab_index].select()
        return True
    except Exception as e:
        print(f"[错误] 切换标签页失败: {e}")
        return False


def send_shortcut(keys, title_keyword):
    """向指定窗口发送快捷键，窗口会被自动激活。"""
    if not activate_window(title_keyword):
        print(f"[错误] 无法激活窗口: {title_keyword}")
        return False
    time.sleep(0.2)
    try:
        send_keys(keys)
        return True
    except Exception as e:
        print(f"[错误] 发送快捷键失败: {e}")
        return False


def send_text(text, title_keyword):
    """向指定窗口发送文字（优先使用剪贴板粘贴，避免中文/特殊字符问题）。"""
    if not activate_window(title_keyword):
        print(f"[错误] 无法激活窗口: {title_keyword}")
        return False
    time.sleep(0.2)
    try:
        _set_clipboard_text(text)
        time.sleep(0.1)
        send_keys("^v")
        return True
    except Exception as e:
        print(f"[错误] 发送文字失败: {e}")
        return False


# ---------------- DeepSeek 专用 ----------------

def _find_deepseek_tab():
    """在三个浏览器中查找标题包含 '- DeepSeek' 的标签页。"""
    for b_name in ["chrome", "edge", "brave"]:
        try:
            windows = get_browser_windows(b_name)
        except Exception:
            continue
        for win in windows:
            try:
                tabs = win.descendants(control_type="TabItem")
            except Exception:
                continue
            for idx, tab in enumerate(tabs):
                try:
                    title = tab.window_text()
                except Exception:
                    continue
                if title and ("- DeepSeek" in title or "DeepSeek -" in title):
                    return b_name, win, idx, title
    return None


def send_to_deepseek(file_path, text, extra_wait=1.0):
    """
    向 DeepSeek 网页发送一段文字并上传一个附件。
    流程：
      1. 找到标题包含 '- DeepSeek' 的标签页；
      2. 前置该窗口并选中该标签页；
      3. Ctrl+/ 聚焦输入框；
      4. 粘贴文字；
      5. Ctrl+Alt+U 打开文件对话框；
      6. 输入文件路径并回车。

    :param file_path: 要上传的附件路径
    :param text:      要发送的文字 prompt
    :return: 成功 True，失败 False
    """
    if not os.path.isfile(file_path):
        print(f"[错误] 文件不存在: {file_path}")
        return False
    file_path = os.path.abspath(file_path)

    found = _find_deepseek_tab()
    if not found:
        print("[错误] 三个浏览器中都未找到标题包含 '- DeepSeek' 的标签页")
        return False
    b_name, win, tab_idx, tab_title = found
    print(f"[信息] 找到 DeepSeek 标签页: {b_name} 索引={tab_idx} 标题='{tab_title}'")

    # 1) 前置窗口 + 选中标签页
    hwnd = win.handle
    if not _bring_window_to_front(hwnd):
        print("[警告] 窗口前置失败，继续尝试操作")
    time.sleep(0.4)

    try:
        tabs = win.descendants(control_type="TabItem")
        tabs[tab_idx].select()
    except Exception as e:
        print(f"[警告] 选中标签页失败: {e}")
    time.sleep(0.4)

    # 2) Ctrl+/ 聚焦输入框
    try:
        send_keys("^/")
    except Exception as e:
        print(f"[错误] 发送 Ctrl+/ 失败: {e}")
        return False
    time.sleep(0.5)

    # 3) 粘贴 prompt 文字
    try:
        _set_clipboard_text(text)
        time.sleep(0.1)
        send_keys("^v")
    except Exception as e:
        print(f"[错误] 粘贴文字失败: {e}")
        return False
    time.sleep(0.8)

    # 4) Ctrl+Alt+U 打开文件选择对话框
    try:
        send_keys("^%u")
    except Exception as e:
        print(f"[错误] 发送 Ctrl+Alt+U 失败: {e}")
        return False
    time.sleep(1.5)  # 等待文件对话框出现

    # 5) 粘贴路径并回车
    try:
        _set_clipboard_text(file_path)
        time.sleep(0.2)
        send_keys("^a")       # 先清空（若有默认内容）
        time.sleep(0.1)
        send_keys("^v")
        time.sleep(0.3)
        send_keys("{ENTER}")
    except Exception as e:
        print(f"[错误] 输入文件路径失败: {e}")
        return False
    time.sleep(extra_wait)
    print("[信息] 已发送到 DeepSeek")
    return True


# ---------------- 测试入口 ----------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="浏览器标签页检测 & DeepSeek 自动化工具")
    parser.add_argument("--file", help="要发送给 DeepSeek 的附件路径（用于测试 send_to_deepseek）")
    parser.add_argument("--text", help="要发送给 DeepSeek 的文字 prompt（用于测试 send_to_deepseek）")
    args = parser.parse_args()

    if args.file and args.text:
        print("=" * 60)
        print(f"调用 send_to_deepseek(file={args.file}, text={args.text!r})")
        print("=" * 60)
        ok = send_to_deepseek(args.file, args.text)
        print(f"结果: {'成功' if ok else '失败'}")
    elif args.file or args.text:
        print("[用法] --file 和 --text 必须同时提供")
    else:
        print("=" * 60)
        print("检测所有浏览器标签页")
        print("=" * 60)
        all_tabs = get_all_tabs()
        if not all_tabs:
            print("未检测到任何浏览器标签页（请确保 Chrome / Edge / Brave 正在运行并打开了标签页）")
        else:
            for b_name, tabs in all_tabs.items():
                print(f"\n【{b_name.upper()}】共 {len(tabs)} 个标签页:")
                for t in tabs:
                    print(f"  [{t['index']}] {t['title']}")
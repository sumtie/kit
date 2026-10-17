#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import sys
import time
import requests
from datetime import datetime
from seleniumbase import SB

# ==================== 环境变量 ====================
EMAIL        = os.environ.get("BOTHOST_EMAIL") or ""
PASSWORD     = os.environ.get("BOTHOST_PASSWORD") or ""
TG_CHAT_ID   = os.environ.get("TG_CHAT_ID") or ""
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""

if not EMAIL or not PASSWORD:
    print("❌ 请配置 EMAIL 和 PASSWORD")
    sys.exit(1)

# ==================== 工具函数 ====================
def send_telegram_message(message: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠️ Telegram 未配置，跳过通知")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT_ID, "text": message}, timeout=10)
        print("✅ Telegram 通知已发送")
    except Exception as e:
        print(f"❌ Telegram 发送失败: {e}")

def format_notification(status: str, extra: str = "", error: str = "", expiry_date: str = "") -> str:
    local_time = time.gmtime(time.time() + 8 * 3600)
    now = time.strftime("%Y-%m-%d %H:%M:%S", local_time)

    if "@" in EMAIL:
        name, domain = EMAIL.split("@", 1)
        masked_email = f"{name[:2]}****{name[-2:]}@{domain}" if len(name) > 4 else f"{name}@{domain}"
    else:
        masked_email = EMAIL[:2] + "****" if EMAIL else "未配置"

    lines = [
        "🇫🇮 Bot-hosting 续期通知",
        "",
        status,
        f"👤 登录账户: {masked_email}",
        "🔐 登录方式: Email/Password",
    ]
    if expiry_date:
        lines.append(f"📅 到期时间: {expiry_date}")
    if extra:
        lines.append(extra)
    if error:
        lines.append(f"⚠️ 错误信息: {error}")
    lines.append(f"⏱️ 登录时间: {now}")
    return "\n".join(lines)

def wait_for_turnstile_pass(sb, timeout=30):
    start = time.time()
    indicators = ["verify you are human", "确认您是真人", "troubleshoot", "just a moment"]
    while time.time() - start < timeout:
        if not any(x in sb.get_page_source().lower() for x in indicators):
            print("✅ Turnstile 验证已通过")
            return True
        sb.sleep(1)
    print("❌ Turnstile 验证超时未通过")
    return False

def get_current_ip(proxy_server: str = "") -> str:
    proxies = {"http": proxy_server, "https": proxy_server} if proxy_server else None
    resp = requests.get("https://api.ip.sb/ip", proxies=proxies, timeout=15)
    resp.raise_for_status()
    return resp.text.strip()

def format_countdown(countdown_str: str) -> str:
    try:
        h, m, _ = countdown_str.split(":")
        h, m = int(h), int(m)
        return f"{h}h{m}min" if h > 0 else f"{m}min"
    except Exception:
        return countdown_str

def extract_expiry_date(page_source: str) -> str | None:
    patterns = [
        r"[Ee]xpires\s*[:\-]?\s*(\d{4}/\d{2}/\d{2})",
        r"[Ee]xpires\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})",
        r"(\d{4}/\d{2}/\d{2})\s*[\-–]\s*renew",
        r"(\d{2}/\d{2}/\d{4})\s*[\-–]\s*renew",
        r"(\d{4}/\d{2}/\d{2})\s*[\-–]\s*renew manually to extend for 4 days",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_source)
        if match:
            date_str = match.group(1)
            parts = date_str.split("/")
            if len(parts[-1]) == 4 and len(parts[0]) == 2:  # MM/DD/YYYY → YYYY/MM/DD
                return f"{parts[2]}/{parts[0]}/{parts[1]}"
            return date_str
    return None

# ==================== 邮箱密码登录 ====================
def do_email_login(sb) -> bool:
    print("🚀 使用邮箱密码登录...")
    try:
        sb.open("https://bot-hosting.net/login")
        sb.wait_for_ready_state_complete()
        sb.sleep(2)

        # 输入邮箱
        print("📧 输入邮箱...")
        sb.type("#email", EMAIL)
        sb.sleep(0.5)
        sb.click('button:contains("Continue with email")')
        sb.sleep(3)

        # 处理可能的 Turnstile
        try:
            sb.uc_gui_click_captcha()
            time.sleep(3)
        except Exception:
            pass

        # 输入密码
        print("🔑 输入密码...")
        sb.wait_for_element("#ea-password", timeout=15)
        sb.type("#ea-password", PASSWORD)
        sb.sleep(0.5)
        sb.click('button:contains("Sign in")')
        sb.sleep(4)

        # 再次处理 Turnstile
        for _ in range(3):
            try:
                sb.uc_gui_click_captcha()
                time.sleep(4)
            except Exception:
                pass
            if wait_for_turnstile_pass(sb, timeout=12):
                break

        # 验证是否登录成功
        sb.sleep(2)
        current_url = sb.get_current_url()
        print(f"📝 登录后URL: {current_url}")

        if "/login" not in current_url:
            print("✅ 邮箱密码登录成功")
            return True

        # 二次确认：直接访问账单页
        sb.open("https://bot-hosting.net/a/billings")
        sb.wait_for_ready_state_complete()
        sb.sleep(3)
        if "/a/billings" in sb.get_current_url() and "/login" not in sb.get_current_url():
            print("✅ 邮箱密码登录成功（已到达账单页）")
            return True

        print("❌ 邮箱密码登录失败")
        return False

    except Exception as e:
        print(f"❌ 登录过程出错: {e}")
        return False

# ==================== 主流程 ====================
def main():
    print("#" * 25)
    print("   Bot-hosting 自动续期")
    print("#" * 25)

    IS_PROXY     = os.environ.get("IS_PROXY", "false").lower() == "true"
    PROXY_SERVER = os.environ.get("PROXY_SERVER", "").strip() or "http://127.0.0.1:1080"
    HEADLESS     = os.environ.get("HEADLESS", "false").lower() == "true"

    sb_kwargs = {"uc": True, "headless": HEADLESS}
    if IS_PROXY:
        print(f"🔗 挂载代理: {PROXY_SERVER}")
        sb_kwargs["proxy"] = PROXY_SERVER
    else:
        print("🍭 未使用代理，直连访问")

    with SB(**sb_kwargs) as sb:
        try:
            ip = get_current_ip(PROXY_SERVER if IS_PROXY else "")
            print(f"📍 当前出口IP: {ip}")
        except Exception as e:
            print(f"⚠️ 获取出口 IP 失败: {e}")

        # 登录
        if not do_email_login(sb):
            send_telegram_message(format_notification("❌ 登录失败", error="邮箱或密码错误 / 页面异常"))
            return

        # 进入账单页
        print("🌐 访问账单页...")
        sb.open("https://bot-hosting.net/a/billings")
        sb.wait_for_ready_state_complete()
        sb.sleep(3)

        # 提取当前到期日期
        page_source = sb.get_page_source()
        current_expiry = extract_expiry_date(page_source)
        if current_expiry:
            print(f"📅 当前到期日期: {current_expiry}")
        else:
            print("⚠️ 未能提取当前到期日期")

        # 查找续期按钮
        outer_renew_selector = None
        countdown_text = None
        possible_selectors = [
            'button:contains("Renew")',
            'button:contains("Renew free plan")',
            'a:contains("Renew")',
            '[class*="renew"]',
            '[class*="Renew"]',
        ]
        for selector in possible_selectors:
            try:
                if sb.is_element_visible(selector):
                    button_text = sb.get_text(selector)
                    if "Renew in" in button_text:
                        match = re.search(r"Renew in (\d{2}:\d{2}:\d{2})", button_text)
                        if match:
                            countdown_text = match.group(1)
                        break
                    elif "Renew" in button_text and "in" not in button_text.lower():
                        outer_renew_selector = selector
                        print(f"✅ 续期按钮可用: '{button_text}'")
                        break
            except Exception:
                pass

        # 执行续期
        if outer_renew_selector:
            print("🔄 点击外部续期按钮，等待验证窗口...")
            try:
                sb.sleep(2)
                sb.click(outer_renew_selector)
                sb.sleep(15)
            except Exception as e:
                print(f"❌ 点击外部按钮失败: {e}")
                send_telegram_message(format_notification("❌ 续期失败", error="点击外部续期按钮出错"))
                return

            # 处理弹窗 Turnstile
            print("🔒 检测弹窗中的 Turnstile 验证...")
            turnstile_passed = False
            for attempt in range(1, 4):
                try:
                    sb.uc_gui_click_captcha()
                    time.sleep(12)
                except Exception as e:
                    print(f"⚠️ 点击 Turnstile 出错: {e}")
                if wait_for_turnstile_pass(sb, timeout=20):
                    turnstile_passed = True
                    break
                print(f"⏳ 第 {attempt} 次未通过，重试...")

            if not turnstile_passed:
                print("❌ Turnstile 验证最终未通过")
                send_telegram_message(format_notification("❌ 续期失败", error="Turnstile 验证未通过"))
                return

            # 点击弹窗内续期按钮
            print("⏳ 点击续期按钮...")
            time.sleep(5)
            try:
                sb.click('div[role="dialog"] button.btn-primary', timeout=8)
                print("✅ 已点击续期按钮")
            except Exception as e:
                print(f"续期按钮点击失败: {e}")

            print("⏳ 等待新的过期时间...")
            sb.sleep(6)

            new_page_text = sb.get_page_source()
            new_expiry = extract_expiry_date(new_page_text)
            new_match = re.search(r"Renewal cooldown (\d{2}:\d{2}:\d{2})", new_page_text)

            if new_match:
                new_countdown = new_match.group(1)
                print(f"✅ 续期成功！新的倒计时: {new_countdown}")
                if new_expiry:
                    print(f"📅 新的到期日期: {new_expiry}")
                send_telegram_message(
                    format_notification(
                        "✅ 续期成功",
                        extra=f"⏱️ 可续期时间: {format_countdown(new_countdown)}后",
                        expiry_date=new_expiry or "（未获取到）"
                    )
                )
            elif new_expiry and new_expiry != current_expiry:
                print(f"✅ 续期成功，到期日期已更新为: {new_expiry}")
                send_telegram_message(
                    format_notification("✅ 续期成功", extra="到期日期已更新", expiry_date=new_expiry)
                )
            else:
                print("⚠️ 续期结果未知，请手动检查")
                send_telegram_message(
                    format_notification(
                        "⚠️ 续期可能未成功",
                        extra="请登录后台检查",
                        expiry_date=current_expiry or "（未获取到）"
                    )
                )
        else:
            if countdown_text:
                friendly = format_countdown(countdown_text)
                print(f"⏳ 未到续期时间，倒计时: {countdown_text} ({friendly})")
                send_telegram_message(
                    format_notification(
                        "⏳ 未到续期时间",
                        extra=f"⏱️ 可续期时间: {friendly}后",
                        expiry_date=current_expiry or "（未获取到）"
                    )
                )
            else:
                print("ℹ️ 未找到续期按钮或倒计时，状态未知")
                send_telegram_message(
                    format_notification(
                        "ℹ️ 无需续期",
                        extra="当前状态未知，请手动检查",
                        expiry_date=current_expiry or "（未获取到）"
                    )
                )

        print("🏁 脚本执行完毕")

if __name__ == "__main__":
    main()
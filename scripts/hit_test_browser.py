#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : hit_test_browser.py

通过真实浏览器（非无头）对知识库文档页执行召回测试：
1. 打开前端登录页，用账号密码登录
2. 跳转到目标知识库文档列表页
3. 打开"召回测试"弹窗，填入 query + 检索策略
4. 点击召回测试按钮，读取召回结果并截图

用法：
    python scripts/hit_test_browser.py [--query "docker 是什么"] [--strategy semantic|full_text|hybrid] [--k 5]
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATASET_ID = "be2f9b05-805d-46d2-a01b-b2292f1b7da5"
BASE_URL = "http://localhost:5173"
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
if not EMAIL or not PASSWORD:
    raise RuntimeError("请设置 EMAIL 和 PASSWORD 环境变量")


def main() -> None:
    parser = argparse.ArgumentParser(description="浏览器召回测试")
    parser.add_argument("--query", default="docker 是什么", help="检索 query")
    parser.add_argument("--strategy", default="semantic", choices=["semantic", "full_text", "hybrid"], help="检索策略")
    parser.add_argument("--k", type=int, default=5, help="最大召回数量")
    parser.add_argument("--headless", action="store_true", help="无头模式（默认关闭，使用真实浏览器）")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless, args=["--start-maximized"])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        # 1、打开登录页
        print(">>> 打开登录页")
        page.goto(f"{BASE_URL}/auth/login", wait_until="networkidle")
        page.wait_for_timeout(1000)
        page.screenshot(path="scripts/_screenshots/01_login.png")

        # 2、尝试登录（先看页面结构，失败则注入 token）
        try:
            # 常见 Arco Design 表单结构：placeholder 或 label
            page.locator("input").first
            # 找 email 输入框
            email_locator = page.locator("input[type='text'], input[placeholder*='邮箱'], input[placeholder*='email'], input[placeholder*='账号']").first
            email_locator.fill(EMAIL)
            password_input = page.locator("input[type='password']").first
            password_input.fill(PASSWORD)
            page.wait_for_timeout(300)
            page.screenshot(path="scripts/_screenshots/02_login_filled.png")
            # 点登录按钮
            login_btn = page.locator("button:has-text('登录'), button[type='submit']").first
            login_btn.click()
            print(">>> 已提交登录表单")
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f">>> 表单登录失败（{e}），尝试注入 token")
            # 通过 API 登录拿 token 并注入 localStorage
            import urllib.request
            req = urllib.request.Request(
                "http://localhost:5000/auth/password_login",
                data=(f'{{"email":"{EMAIL}","password":"{PASSWORD}"}}').encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                login_data = eval(resp.read().decode())["data"]
            token = login_data["access_token"]
            page.goto(f"{BASE_URL}/auth/login", wait_until="domcontentloaded")
            page.evaluate(
                """(token) => localStorage.setItem('credential', JSON.stringify({access_token: token}))""",
                token,
            )
            page.goto(f"{BASE_URL}/space/datasets", wait_until="networkidle")
            page.wait_for_timeout(1500)

        page.screenshot(path="scripts/_screenshots/03_after_login.png")

        # 3、跳转到目标文档页
        print(">>> 跳转文档列表页")
        page.goto(f"{BASE_URL}/space/datasets/{DATASET_ID}/documents", wait_until="networkidle")
        page.wait_for_timeout(2000)
        page.screenshot(path="scripts/_screenshots/04_documents.png")

        # 4、打开召回测试弹窗
        print(">>> 打开召回测试弹窗")
        hit_btn = page.locator("button:has-text('召回测试')").first
        hit_btn.click()
        page.wait_for_timeout(1500)
        page.screenshot(path="scripts/_screenshots/05_hit_modal.png")

        # 5、填入 query
        print(f">>> 填入 query: {args.query}")
        query_input = page.locator(
            "textarea[placeholder*='请输入'], textarea, input[placeholder*='请输入']"
        ).first
        query_input.fill(args.query)
        page.wait_for_timeout(500)

        # 6、设置检索策略（打开检索设置弹窗）
        print(f">>> 设置检索策略: {args.strategy}, k={args.k}")
        try:
            setting_btn = page.locator("button:has-text('检索设置')").first
            setting_btn.click()
            page.wait_for_timeout(800)
            # 选择策略
            strategy_el = page.locator(f"text={args.strategy}").first
            strategy_el.click()
            page.wait_for_timeout(300)
            # 设置 k
            k_input = page.locator("input[type='number'], input").nth(0)
            k_input.fill(str(args.k))
            page.wait_for_timeout(300)
            # 保存设置
            save_btn = page.locator("button:has-text('保存')").first
            save_btn.click()
            page.wait_for_timeout(800)
        except Exception as e:
            print(f">>> 检索设置失败（继续默认设置）: {e}")

        # 7、点击召回测试
        print(">>> 点击召回测试按钮")
        submit_btn = page.locator("button:has-text('召回测试')").last
        submit_btn.click()

        # 8、等待结果并截图
        page.wait_for_timeout(5000)
        page.screenshot(path="scripts/_screenshots/06_hit_results.png", full_page=True)

        # 9、读取召回结果文本
        try:
            results_text = page.locator("text=/共召回.*条/").first.text_content(timeout=5000)
            print(f">>> 结果: {results_text}")
        except Exception:
            print(">>> 未找到'共召回 X 条'文本，尝试读取弹窗内容")
            try:
                modal_text = page.locator(".arco-modal, [class*='modal']").first.text_content(timeout=3000)
                print(">>> 弹窗内容片段:", (modal_text or "")[:800])
            except Exception as e2:
                print(f">>> 读取失败: {e2}")

        browser.close()
        print(">>> 完成，截图保存在 scripts/_screenshots/")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : cdp_hit_test.py

通过 CDP 控制真实浏览器（非无头）执行知识库召回测试：
登录 → 文档页 → 召回测试弹窗 → 填 query/策略 → 执行 → 截图 + 读取结果。

用法：
    python scripts/cdp_hit_test.py [--query "docker 是什么"] [--strategy hybrid] [--k 5]
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cdp_client import CDP, get_page_ws

DATASET_ID = "be2f9b05-805d-46d2-a01b-b2292f1b7da5"
BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:5000"
EMAIL = os.getenv("EMAIL")
PASSWORD = os.getenv("PASSWORD")
if not EMAIL or not PASSWORD:
    raise RuntimeError("请设置 EMAIL 和 PASSWORD 环境变量")
SHOT_DIR = Path(__file__).resolve().parent / "_screenshots"


def login_get_token() -> dict:
    """调用后端登录接口获取 access_token + expire_at"""
    req = urllib.request.Request(
        f"{API_URL}/auth/password_login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode())
    if body.get("code") != "success":
        raise RuntimeError(f"登录失败: {body}")
    return body["data"]


def main() -> None:
    parser = argparse.ArgumentParser(description="CDP 浏览器召回测试")
    parser.add_argument("--query", default="docker 是什么", help="检索 query")
    parser.add_argument("--strategy", default="hybrid", choices=["semantic", "full_text", "hybrid"], help="检索策略")
    parser.add_argument("--k", type=int, default=5, help="最大召回数量")
    args = parser.parse_args()

    SHOT_DIR.mkdir(parents=True, exist_ok=True)

    # 1、登录拿 token + expire_at（用于注入 localStorage）
    login_data = login_get_token()
    token = login_data["access_token"]
    expire_at = login_data["expire_at"]
    print(f">>> 登录成功, token={token[:20]}...")

    cdp = CDP(get_page_ws())
    try:
        # 2、打开登录页（先导航确保页面环境正常）
        print(">>> 打开前端页面")
        cdp.navigate(f"{BASE_URL}/auth/login")
        cdp.wait(2)
        cdp.screenshot(str(SHOT_DIR / "01_login.png"))

        # 3、注入完整 credential 到 localStorage（需含 expire_at，否则路由守卫判未登录）
        cdp.evaluate(
            f"localStorage.setItem('credential', JSON.stringify({{access_token: '{token}', expire_at: {expire_at}}})); 'ok'"
        )
        print(">>> token 已注入 localStorage")

        # 4、刷新页面让路由守卫读到登录态，再导航到目标文档页
        cdp.navigate(f"{BASE_URL}/space/datasets/{DATASET_ID}/documents")
        cdp.wait(3)
        cdp.screenshot(str(SHOT_DIR / "02_documents_page.png"))

        # 5、确认页面标题/加载状态
        title = cdp.eval_value("document.title")
        body_text = cdp.eval_value("document.body ? document.body.innerText.slice(0, 200) : ''")
        print(f">>> 页面标题: {title}")
        print(f">>> 页面文本: {body_text[:150]!r}")

        # 6、打开"召回测试"弹窗
        clicked = cdp.eval_value(
            """
            (() => {
              const btns = [...document.querySelectorAll('button')];
              const hit = btns.find(b => b.innerText.includes('召回测试'));
              if (hit) { hit.click(); return 'clicked'; }
              return 'not-found';
            })()
            """
        )
        print(f">>> 点击召回测试按钮: {clicked}")
        cdp.wait(2)
        cdp.screenshot(str(SHOT_DIR / "03_hit_modal.png"))

        # 7、在弹窗中填 query
        filled = cdp.eval_value(
            f"""
            (() => {{
              const el = document.querySelector('.arco-modal textarea') ||
                        document.querySelector('.arco-modal input[type="text"]') ||
                        document.querySelector('textarea');
              if (el) {{
                const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement ?
                    HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value').set;
                setter.call(el, {json.dumps(args.query)});
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                return 'filled: ' + el.value;
              }}
              return 'no-input';
            }})()
            """
        )
        print(f">>> 填入 query: {filled}")
        cdp.wait(1)

        # 8、设置检索策略（点击当前策略按钮打开检索设置弹窗）
        STRATEGY_LABEL = {
            "semantic": "相似性检索",
            "full_text": "全文检索",
            "hybrid": "混合策略",
        }
        if args.strategy != "semantic" or args.k != 5:
            setting_clicked = cdp.eval_value(
                """
                (() => {
                  const btns = [...document.querySelectorAll('.arco-modal button')];
                  const s = btns.find(b => b.innerText.includes('相似性检索') ||
                                            b.innerText.includes('全文检索') ||
                                            b.innerText.includes('混合策略'));
                  if (s) { s.click(); return 'clicked: ' + s.innerText; }
                  return 'not-found';
                })()
                """
            )
            print(f">>> 打开检索设置: {setting_clicked}")
            cdp.wait(1.5)
            if "clicked" in str(setting_clicked):
                # 选择策略（单选组，按中文 label 匹配）
                chosen = cdp.eval_value(
                    f"""
                    (() => {{
                      const label = {json.dumps(STRATEGY_LABEL[args.strategy])};
                      const els = [...document.querySelectorAll('.arco-modal label, .arco-modal span, .arco-modal div')];
                      const target = els.find(e => e.innerText === label && e.children.length === 0);
                      if (target) {{ target.click(); return 'clicked: ' + label; }}
                      return 'not-found: ' + label;
                    }})()
                    """
                )
                print(f">>> 选择策略: {chosen}")
                cdp.wait(0.5)
                # 设置 k 值（输入框，容错：失败则跳过，用默认值）
                if args.k:
                    try:
                        k_set = cdp.eval_value(
                            f"""
                            (() => {{
                              const el = document.querySelector('#retrieval-k') ||
                                         document.querySelector('.arco-modal input[type="number"]');
                              if (!el) return 'no-k-input';
                              const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
                                           : (el instanceof HTMLInputElement ? HTMLInputElement.prototype : null);
                              if (!proto) return 'not-native-input';
                              const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                              setter.call(el, {args.k});
                              el.dispatchEvent(new Event('input', {{bubbles: true}}));
                              el.dispatchEvent(new Event('change', {{bubbles: true}}));
                              return 'k=' + el.value;
                            }})()
                            """
                        )
                        print(f">>> 设置 k: {k_set}")
                        cdp.wait(0.5)
                    except Exception as e:
                        print(f">>> 设置 k 跳过（{e}）")
                # 保存设置
                saved = cdp.eval_value(
                    """
                    (() => {
                      const btns = [...document.querySelectorAll('.arco-modal button')];
                      const s = btns.find(b => b.innerText.includes('保存'));
                      if (s) { s.click(); return 'clicked'; }
                      return 'not-found';
                    })()
                    """
                )
                print(f">>> 保存检索设置: {saved}")
                cdp.wait(1.5)

        # 9、点击弹窗内"召回测试"提交按钮
        submitted = cdp.eval_value(
            """
            (() => {
              const btns = [...document.querySelectorAll('.arco-modal button')];
              const hit = btns.find(b => b.innerText.includes('召回测试') && !b.disabled);
              if (hit) { hit.click(); return 'clicked'; }
              return 'not-found';
            })()
            """
        )
        print(f">>> 点击执行召回测试: {submitted}")

        # 10、等待结果
        cdp.wait(6)
        cdp.screenshot(str(SHOT_DIR / "04_hit_results.png"), )
        cdp.screenshot(str(SHOT_DIR / "04_hit_results_full.png"))

        # 11、读取召回结果
        result_text = cdp.eval_value(
            """
            (() => {
              const m = document.querySelector('.arco-modal');
              if (!m) return 'no-modal';
              const t = m.innerText;
              const hitMatch = t.match(/共召回[^\\n]*/);
              return hitMatch ? hitMatch[0] : t.slice(0, 600);
            })()
            """
        )
        print(">>> 召回结果:", (result_text or "")[:800])

        # 12、读取每个片段卡片的得分 + 内容 + 文档名
        segments_info = cdp.eval_value(
            """
            (() => {
              const cards = [...document.querySelectorAll('.arco-modal .arco-col')];
              return cards.map(card => {
                const text = card.innerText;
                const scoreMatch = text.match(/(\\d+\\.\\d{2})/);
                const lines = text.split('\\n').filter(l => l.trim());
                return {
                  score: scoreMatch ? scoreMatch[1] : '',
                  content: (lines[0] || '').slice(0, 50),
                  doc: lines[lines.length - 1] || '',
                };
              });
            })()
            """
        )
        print(f">>> 片段详情 ({len(segments_info)} 条):")
        for i, seg in enumerate(segments_info, 1):
            print(f"  [{i}] score={seg['score']} doc={seg['doc']} | {seg['content']}")

        # 13、记录策略标签
        strategy_label = cdp.eval_value(
            """
            (() => {
              const btns = [...document.querySelectorAll('.arco-modal button')];
              const s = btns.find(b => ['相似性检索','全文检索','混合策略'].some(x => b.innerText.includes(x)));
              return s ? s.innerText : '';
            })()
            """
        )
        print(f">>> 当前检索策略: {strategy_label}")

    finally:
        cdp.close()
    print(">>> 完成，截图在 scripts/_screenshots/")


if __name__ == "__main__":
    main()

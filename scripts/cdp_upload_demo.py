#!/usr/bin/env python
"""
@Time    : 2026/5/20
@File    : cdp_upload_demo.py

通过 CDP 控制真实浏览器，演示页面上传大文件（天辰_utf8.txt）到知识库的完整流程：
1. 打开知识库文档页 → 点击"添加文件"
2. 选择文件（注入 input[type=file]）
3. 步骤2 选择"自动分段与清洗" → 下一步
4. 步骤3 显示处理进度
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cdp_client import CDP, new_tab

DATASET_ID = "be2f9b05-805d-46d2-a01b-b2292f1b7da5"
BASE_URL = "http://localhost:5173"
FILE_PATH = r"H:\ai-code-llmops\天辰_utf8.txt"


def main() -> None:
    ws = new_tab()
    cdp = CDP(ws)
    try:
        # 1、打开添加文件页
        url = f"{BASE_URL}/space/datasets/{DATASET_ID}/documents/create"
        print(f">>> 打开添加文件页: {url}")
        cdp.navigate(url)
        cdp.wait(3.5)
        cdp.screenshot(str(Path(__file__).resolve().parent / "_screenshots" / "30_upload_step1.png"))

        # 2、找到 a-upload 内部隐藏的 input[type=file] 并注入文件（用 nodeId 方式）
        has_input = cdp.eval_value(
            "!!document.querySelector('.arco-upload input[type=file]')"
        )
        print(f">>> 找到上传 input: {has_input}")
        if has_input:
            # 通过 DOM.querySelector 拿 nodeId，再 DOM.setFileInputFiles
            doc = cdp.send("DOM.getDocument")
            node = cdp.send("DOM.querySelector", {
                "nodeId": doc["root"]["nodeId"],
                "selector": ".arco-upload input[type=file]",
            })
            if node.get("nodeId"):
                cdp.send("DOM.setFileInputFiles", {
                    "files": [FILE_PATH],
                    "nodeId": node["nodeId"],
                })
                print(">>> 文件已注入 input[type=file] (nodeId)")
                cdp.wait(1)
                # 触发 change 事件让 a-upload 感知
                cdp.eval_value("""
                (() => {
                  const input = document.querySelector('.arco-upload input[type=file]');
                  input.dispatchEvent(new Event('change', {bubbles: true}));
                  return 'dispatched';
                })()
                """)
                cdp.wait(4)
                cdp.screenshot(str(Path(__file__).resolve().parent / "_screenshots" / "31_upload_file_selected.png"))

        # 3、检查上传是否触发（文件列表 + 上传请求）
        state = cdp.eval_value("""
        (() => {
          const uploadItems = document.querySelectorAll('.arco-upload-list-item, .arco-upload-list');
          const text = document.body.innerText;
          return {
            hasUploadList: uploadItems.length > 0,
            hasFileName: text.includes('天辰_utf8'),
            pageText: text.slice(0, 200),
          };
        })()
        """)
        print(">>> 上传状态:", json.dumps(state, ensure_ascii=False))

        # 4、如果文件已上传到列表，点"下一步"进入分段设置
        next_clicked = cdp.eval_value("""
        (() => {
          const btns = [...document.querySelectorAll('button')];
          const n = btns.find(b => b.innerText.trim() === '下一步');
          if (n && !n.disabled) { n.click(); return 'clicked'; }
          return 'not-ready: ' + btns.map(b => b.innerText.trim() + (b.disabled ? '(disabled)' : '')).join(',');
        })()
        """)
        print(f">>> 点击下一步: {next_clicked}")
        cdp.wait(1.5)
        cdp.screenshot(str(Path(__file__).resolve().parent / "_screenshots" / "32_upload_step2.png"))

        # 5、步骤2：选自动分段 → 下一步
        auto_clicked = cdp.eval_value("""
        (() => {
          const divs = [...document.querySelectorAll('div')];
          const auto = divs.find(d => d.innerText.includes('自动分段与清洗') && d.innerText.includes('自动分段与预处理规则'));
          if (auto) { auto.click(); return 'clicked'; }
          return 'not-found';
        })()
        """)
        print(f">>> 选择自动分段: {auto_clicked}")
        cdp.wait(0.5)
        next2 = cdp.eval_value("""
        (() => {
          const btns = [...document.querySelectorAll('button')];
          const n = btns.find(b => b.innerText.trim() === '下一步' && !b.disabled);
          if (n) { n.click(); return 'clicked'; }
          return 'no-next';
        })()
        """)
        print(f">>> 下一步: {next2}")
        cdp.wait(2)
        cdp.screenshot(str(Path(__file__).resolve().parent / "_screenshots" / "33_upload_processing.png"))

        # 6、显示处理进度（轮询几秒）
        for i in range(4):
            time.sleep(5)
            progress = cdp.eval_value("""
            (() => {
              const text = document.body.innerText;
              const m = text.match(/天辰[^\\n]*/);
              const pct = text.match(/(\\d+\\.\\d{2})%/);
              return { fileLine: m ? m[0] : '', pct: pct ? pct[1] : '' };
            })()
            """)
            print(f"  [{i+1}] {json.dumps(progress, ensure_ascii=False)}")
        cdp.screenshot(str(Path(__file__).resolve().parent / "_screenshots" / "34_upload_final.png"))
    finally:
        cdp.close()
    print(">>> 演示结束，截图在 scripts/_screenshots/")


if __name__ == "__main__":
    main()

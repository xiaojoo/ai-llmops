#!/usr/bin/env python
"""
@Time    : 2026/1/25 1:06
@Author  : sunxiaojie
@File    : code_node.py
"""
import ast
import json
import os
import subprocess
import sys
import time
from typing import Any

from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.variable_entity import (
    VARIABLE_TYPE_DEFAULT_VALUE_MAP,
)
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.core.workflow.utils.helper import extract_variables_from_state
from internal.exception import FailedException

from .code_entity import CodeNodeData

# 代码节点执行限额（防滥用/防挂死）
CODE_EXECUTION_TIMEOUT_SECONDS = 30  # 单次执行超时时间（秒）
CODE_OUTPUT_MAX_BYTES = 1024 * 1024  # 执行结果最大字节数（1MB）

# 子进程执行模板（前缀部分）：在隔离子进程中安装审计钩子。
# sys.addaudithook 由解释器 C 层持有，用户代码拿不到钩子引用无法移除；
# 危险操作（文件/网络/进程/动态库加载等）一律抛错，无法被绕过。
_CHILD_PREFIX = r'''
import json
import sys

# 隔离模式（-I）会忽略 PYTHONIOENCODING 环境变量，这里显式统一为 UTF-8，
# 保证中文错误信息/结果在父子进程间无损传输
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _audit_hook(event: str, args: tuple):
    """拦截危险操作：文件、网络、进程、动态加载等"""
    denied = {
        "open",
        "os.system",
        "os.fork",
        "os.spawn",
        "os.posix_spawn",
        "os.kill",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.run",
        "subprocess.check_call",
        "subprocess.check_output",
        "socket.__new__",
        "socket.connect",
        "socket.bind",
        "socket.listen",
        "socket.accept",
        "socket.getaddrinfo",
        "ctypes.dlopen",
        "ctypes.dlsym",
        "urllib.request.urlopen",
        "http.client.connect",
        "ftplib.connect",
        "telnetlib.connect",
        "shutil.rmtree",
        "shutil.move",
        "shutil.copyfile",
        "shutil.copy",
        "os.removedirs",
        "os.remove",
        "os.unlink",
        "os.rename",
        "os.chmod",
        "os.chown",
        "os.mkdir",
        "os.makedirs",
        "os.rmdir",
        "os.truncate",
        "os.replace",
        "os.link",
        "os.symlink",
    }
    if event in denied:
        raise RuntimeError("代码节点禁止的操作: %s" % event)


sys.addaudithook(_audit_hook)
'''

# 子进程执行模板（后缀部分）：读取 stdin JSON 入参，调用 main 并把结果输出到 stdout
_CHILD_RUNNER = r'''
try:
    payload = sys.stdin.buffer.read().decode("utf-8")
    params = json.loads(payload)
    result = main(params)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write("%s: %s" % (type(e).__name__, e))
    sys.exit(1)
'''


class CodeNode(BaseNode):
    """Python代码运行节点"""
    node_data: CodeNodeData

    def run(self, state: WorkflowState, config: RunnableConfig | None = None, **kwargs: Any) -> WorkflowState:
        """Python代码运行节点，执行的代码函数名字必须为main，并且参数名为params，有且只有一个参数、不允许有额外的其他语句"""
        # 1、提取节点中的输入数据
        start_at = time.perf_counter()
        inputs_dict = extract_variables_from_state(self.node_data.inputs, state)

        # 2、在隔离子进程中执行用户代码（子进程 + 审计钩子 + 超时，防止 RCE/挂死）
        result = self._execute_function(self.node_data.code, params=inputs_dict)

        # 3、检测函数的返回值是否为字典
        if not isinstance(result, dict):
            raise FailedException("main函数的返回值必须是一个字典")

        # 4、提取输出数据
        outputs_dict = {}
        outputs = self.node_data.outputs
        for output in outputs:
            # 5、提取输出数据(非严格校验)
            outputs_dict[output.name] = result.get(
                output.name,
                VARIABLE_TYPE_DEFAULT_VALUE_MAP.get(output.type),
            )

        # 6、构建响应状态并返回
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED,
                    outputs=outputs_dict,
                    latency=(time.perf_counter() - start_at),
                )
            ]
        }

    @classmethod
    def _execute_function(cls, code: str, *args, **kwargs):
        """在隔离子进程中执行用户代码（替代原 exec 直接执行，防 RCE）：

        - 父进程先做 AST 结构校验（只允许 main(params) 函数定义，快速失败）；
        - 子进程以 `python -I`（隔离模式，忽略 PYTHONPATH/用户 site）+ 审计钩子
          （拦截文件/网络/进程/动态库操作）+ 超时/输出上限执行；
        - 入参经 stdin JSON 传递，结果经 stdout JSON 返回，必须可 JSON 序列化
          （与节点输出最终落库为 JSON 的要求一致）。
        """
        # 1、解析代码为 AST（抽象语法树），结构校验
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise FailedException(f"Python代码语法错误: {e}")

        # 2、定义变量用于检查是否找到main函数
        main_func = None

        # 3、循环遍历语法树
        for node in tree.body:
            # 4、判断节点类型是否为函数
            if isinstance(node, ast.FunctionDef):
                # 5、检查函数名称是否为main
                if node.name == "main":
                    if main_func:
                        raise FailedException("代码中只能有一个main函数")

                    # 6、检测main函数的参数是否为params，如果不是则抛出错误
                    if len(node.args.args) != 1 or node.args.args[0].arg != "params":
                        raise FailedException("main函数必须只有一个参数，且参数为params")
                    main_func = node
                else:
                    # 7、其他函数的情况，直接抛出错误
                    raise FailedException("代码中不能包含其他函数，只能有main函数")
            else:
                # 8、非函数的情况，直接抛出错误
                raise FailedException("代码中只能包含函数定义，不允许其他语句存在")

        # 9、判断下是否找到main函数
        if not main_func:
            raise FailedException("代码中必须包含名为main的函数")

        # 10、序列化入参（入参需可 JSON 序列化）
        params = kwargs.get("params", args[0] if args else {})
        try:
            payload = json.dumps(params, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            raise FailedException(f"代码节点输入参数无法序列化: {e}")

        # 11、拼接子进程脚本：审计钩子 + 用户代码 + 执行器
        child_code = _CHILD_PREFIX + "\n" + code + "\n" + _CHILD_RUNNER

        # 12、构造最小化环境变量，避免子进程继承敏感配置（DB URI、密钥等）
        env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),  # Windows 运行库依赖
            "TEMP": os.environ.get("TEMP", ""),
            "TMP": os.environ.get("TMP", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONHASHSEED": "random",
        }

        # 13、启动隔离子进程并执行
        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
        }
        if os.name == "posix":
            # 独立会话，便于超时后整组终止（含孙进程）
            popen_kwargs["start_new_session"] = True
        else:
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", "-c", child_code],
                **popen_kwargs,
            )
            try:
                stdout_bytes, stderr_bytes = proc.communicate(
                    input=payload.encode("utf-8"),
                    timeout=CODE_EXECUTION_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                cls._terminate_process(proc)
                raise FailedException(f"Python代码执行超时（{CODE_EXECUTION_TIMEOUT_SECONDS}秒）")
        except OSError as e:
            raise FailedException(f"Python代码执行环境启动失败: {e}")

        # 14、子进程执行失败：透出真实错误信息（便于排查）
        if proc.returncode != 0:
            err_msg = stderr_bytes.decode("utf-8", errors="replace").strip()
            raise FailedException(f"Python代码执行出错: {err_msg or f'退出码 {proc.returncode}'}")

        # 15、校验输出大小并解析结果
        if len(stdout_bytes) > CODE_OUTPUT_MAX_BYTES:
            raise FailedException("Python代码执行结果过大，超过1MB上限")
        try:
            return json.loads(stdout_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise FailedException(f"Python代码执行结果解析失败: {e}")

    @staticmethod
    def _terminate_process(proc: subprocess.Popen) -> None:
        """终止子进程及其进程组，避免超时后残留子/孙进程"""
        try:
            if os.name == "posix":
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True,
                        timeout=5,
                    )
                except Exception:
                    pass
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

"""Start or reuse the full local workbench for a desktop browser or provider."""

import argparse
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit


@contextmanager
def startup_lock(data):
    """Serialize startup across the desktop, batch and headless entry points."""
    data.mkdir(parents=True, exist_ok=True)
    with (data / ".startup.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        # Closing the file releases the operating-system lock, also after a crash.
        yield


def process_running(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def running_session(data):
    """Read the workstation's own launch record and verify it against loopback."""
    try:
        info = json.loads((data / "session.json").read_text(encoding="utf-8"))
        parts = urlsplit(info["url"])
        port = info["port"]
        if type(port) is not int or not 0 < port < 65536 or (
            parts.scheme, parts.netloc, parts.path, parts.query
        ) != ("http", f"127.0.0.1:{port}", "/", ""):
            return None
        if "pid" in info and not process_running(info["pid"]):
            return None
        token, = parse_qs(parts.fragment)["token"]
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", "/api/bootstrap", headers={"X-Workbench-Token": token})
            response = connection.getresponse()
            if response.status == 200 and "workspaces" in json.loads(response.read()):
                return info
        finally:
            connection.close()
    except (FileNotFoundError, ConnectionError, HTTPException, ValueError, KeyError, TypeError):
        return None
    except TimeoutError as exc:
        raise RuntimeError("本机工作站响应超时，请稍后再打开。") from exc
    return None


def ensure_session(project, data=None):
    from user_tools.workbench.server import APP_VERSION

    folder = data if data is not None else project / "data" / "workbench_scalar10"
    session = running_session(folder)
    if session is None:
        args = [sys.executable, "-m", "user_tools.research_workbench", "--project", str(project), "--no-browser"]
        if data is not None:
            args.extend(["--data", str(data)])
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / "startup.log"
        with log.open("ab") as errors:
            process = subprocess.Popen(
                args, cwd=project, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), start_new_session=os.name != "nt",
            )
        deadline = time.monotonic() + 35
        while session is None:
            session = running_session(folder)
            if session is not None:
                break
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError(f"科研工作站未就绪。启动日志保存在 {log}")
            time.sleep(0.2)
    if session.get("entry_version") != APP_VERSION:
        raise RuntimeError("旧版本科研工作站正在使用同一数据目录。请保存后从旧版页面关闭程序，再打开新版。")
    return session["url"]


def copy_for_desktop(url):
    if os.name != "nt":
        raise RuntimeError("复制到毕昇内置浏览器的入口需要 Windows。")
    subprocess.run(["clip.exe"], input=url.encode("ascii"), check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main():
    parser = argparse.ArgumentParser(description="在毕昇中打开完整的 Fangzhen 科研工作站")
    parser.add_argument("--json", action="store_true", help="供本机工作台组件读取启动地址")
    parser.add_argument("--data", type=Path, help="使用指定的工作站数据目录")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    url = ensure_session(project, args.data.resolve() if args.data else None)
    if args.json:
        print(json.dumps({"url": url}))
    else:
        copy_for_desktop(url)
        print("完整工作站已就绪，地址已复制。请在毕昇按 Ctrl+Alt+T，在内置浏览器地址栏粘贴并回车。")


if __name__ == "__main__":
    main()

"""Cross-platform OS helpers (POSIX + native Windows).

Every piece of AgentGuard that touches processes, signals, ``/proc``,
file permissions or hardware introspection must go through this module
so the rest of the codebase stays platform-agnostic.

Why this exists — two Windows traps the original POSIX code fell into:

* ``os.kill(pid, 0)`` is a liveness probe on POSIX, but on Windows it calls
  ``TerminateProcess(pid, 0)`` and **kills the target**.
* ``subprocess.Popen(start_new_session=True)`` is silently ignored on
  Windows, so "daemonised" children die with the parent console.

``psutil`` is a hard dependency on Windows (see ``pyproject.toml``) and an
optional accelerator elsewhere; every function degrades gracefully without it.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

try:  # pragma: no cover - availability depends on the environment
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None  # type: ignore

# Windows process-creation flags (defined literally so this module imports on POSIX)
CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5


# --------------------------------------------------------------------------- processes
def _hidden_run_kwargs() -> dict:
    """kwargs for short helper commands (taskkill, icacls, ...) — no console flash."""
    return {"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}


def is_pid_alive(pid: int | None) -> bool:
    """True if a process with ``pid`` exists. Never signals/kills the process."""
    if not pid or pid <= 0:
        return False
    if psutil is not None:
        try:
            if not psutil.pid_exists(pid):
                return False
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except psutil.AccessDenied:
            return True
        except Exception:
            return False
    if IS_WINDOWS:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return kernel32.GetLastError() == _ERROR_ACCESS_DENIED
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def terminate(pid: int, *, tree: bool = False, force: bool = False) -> bool:
    """Ask ``pid`` (optionally with all descendants) to exit.

    POSIX: SIGTERM (or SIGKILL with ``force``); ``tree`` targets the process group.
    Windows: ``taskkill /PID n [/T] /F`` — console/no-window processes ignore the
    non-forced WM_CLOSE path, so Windows always force-terminates.
    Returns True if a termination request was delivered.
    """
    if not pid or pid <= 0 or pid == os.getpid():
        return False
    if IS_WINDOWS:
        if psutil is not None:
            try:
                proc = psutil.Process(pid)
                targets = (proc.children(recursive=True) if tree else []) + [proc]
                for p in targets:
                    with contextlib.suppress(Exception):
                        p.kill()
                return True
            except Exception:
                pass
        cmd = ["taskkill", "/PID", str(pid), "/F"]
        if tree:
            cmd.insert(3, "/T")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15, **_hidden_run_kwargs())
            return res.returncode == 0
        except Exception:
            return False
    sig = signal.SIGKILL if force else signal.SIGTERM
    if tree:
        try:
            pgid = os.getpgid(pid)
            if pgid != os.getpgrp():
                os.killpg(pgid, sig)
                return True
        except (PermissionError, ProcessLookupError, OSError):
            pass
    try:
        os.kill(pid, sig)
        return True
    except (PermissionError, ProcessLookupError, OSError):
        return False


def wait_for_exit(pid: int, timeout: float = 5.0, interval: float = 0.15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_pid_alive(pid):
            return True
        time.sleep(interval)
    return not is_pid_alive(pid)


def detached_popen_kwargs(*, detached: bool = True) -> dict:
    """Popen kwargs so a child survives the parent's console/session.

    ``detached=True``  — long-lived daemon (no console at all on Windows).
    ``detached=False`` — helper child that should merely be windowless.
    """
    if IS_WINDOWS:
        flags = CREATE_NEW_PROCESS_GROUP | (DETACHED_PROCESS if detached else CREATE_NO_WINDOW)
        return {"creationflags": flags}
    return {"start_new_session": True}


def process_cmdline(pid: int) -> str:
    """Best-effort full command line for ``pid`` ('' if unknown)."""
    if not pid or pid <= 0:
        return ""
    if psutil is not None:
        with contextlib.suppress(Exception):
            return " ".join(psutil.Process(pid).cmdline())
    proc_file = Path("/proc") / str(pid) / "cmdline"
    with contextlib.suppress(OSError):
        if proc_file.is_file():
            return proc_file.read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore").strip()
    if IS_WINDOWS:
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            with contextlib.suppress(Exception):
                out = subprocess.run(
                    [ps, "-NoProfile", "-Command",
                     f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                    capture_output=True, text=True, timeout=10, **_hidden_run_kwargs(),
                )
                return out.stdout.strip()
        return ""
    ps_bin = shutil.which("ps")
    if ps_bin:
        with contextlib.suppress(Exception):
            out = subprocess.run([ps_bin, "-p", str(pid), "-o", "args="], capture_output=True, text=True, timeout=5)
            return out.stdout.strip()
    return ""


def kill_matching(fragment: str) -> bool:
    """Kill every process (except ourselves) whose command line contains ``fragment``."""
    if not fragment:
        return False
    me = os.getpid()
    killed = False
    if psutil is not None:
        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                if p.info["pid"] == me:
                    continue
                cmd = " ".join(p.info.get("cmdline") or [])
                if fragment in cmd:
                    p.kill()
                    killed = True
            except Exception:
                continue
        return killed
    if IS_WINDOWS:
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if not ps:
            return False
        safe = fragment.replace("'", "''")
        script = (
            "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne " + str(me) +
            " -and $_.CommandLine -like '*" + safe + "*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; 'killed' }"
        )
        with contextlib.suppress(Exception):
            out = subprocess.run([ps, "-NoProfile", "-Command", script],
                                 capture_output=True, text=True, timeout=20, **_hidden_run_kwargs())
            return "killed" in out.stdout
        return False
    pkill = shutil.which("pkill")
    if pkill:
        with contextlib.suppress(Exception):
            r = subprocess.run([pkill, "-f", fragment], capture_output=True, timeout=5)
            return r.returncode == 0
    return False


def ancestor_pids(pid: int | None = None, limit: int = 32) -> list[int]:
    """Parent chain of ``pid`` (default: this process), nearest first."""
    pid = pid or os.getpid()
    if psutil is not None:
        with contextlib.suppress(Exception):
            return [p.pid for p in psutil.Process(pid).parents()][:limit]
    if pid == os.getpid():
        return [os.getppid()]
    return []


# --------------------------------------------------------------------------- hardware
def memory_info() -> tuple[int, int]:
    """(total_mb, available_mb); (0, 0) if undetectable."""
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        mem: dict[str, int] = {}
        with contextlib.suppress(Exception):
            for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    mem[k.strip()] = int(v.strip().split()[0]) // 1024
        total = mem.get("MemTotal", 0)
        return total, mem.get("MemAvailable", mem.get("MemFree", 0))
    if psutil is not None:
        with contextlib.suppress(Exception):
            vm = psutil.virtual_memory()
            return int(vm.total // 2**20), int(vm.available // 2**20)
    if IS_WINDOWS:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        with contextlib.suppress(Exception):
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
                return int(stat.ullTotalPhys // 2**20), int(stat.ullAvailPhys // 2**20)
    if IS_MACOS:
        with contextlib.suppress(Exception):
            total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()) // 2**20
            return total, total // 2
    return 0, 0


# IsProcessorFeaturePresent ids -> /proc/cpuinfo-style flag names
_WIN_CPU_FEATURES = {10: "sse2", 37: "sse4_1", 38: "sse4_2", 39: "avx", 40: "avx2", 41: "avx512f"}


def cpu_info() -> tuple[str, set[str]]:
    """(cpu model string, lowercase feature flags) — flags empty if unknown."""
    import platform as _platform

    model = _platform.processor() or _platform.machine() or "Unknown CPU"
    flags: set[str] = set()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        with contextlib.suppress(Exception):
            for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                low = line.lower()
                if low.startswith("model name") and ":" in line:
                    model = line.split(":", 1)[1].strip()
                elif low.startswith(("flags", "features")) and ":" in line:
                    flags.update(line.split(":", 1)[1].strip().lower().split())
        return model, flags
    if IS_WINDOWS:
        with contextlib.suppress(Exception):
            import winreg  # type: ignore

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                model = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip() or model
        with contextlib.suppress(Exception):
            import ctypes

            present = ctypes.windll.kernel32.IsProcessorFeaturePresent  # type: ignore[attr-defined]
            for fid, name in _WIN_CPU_FEATURES.items():
                if present(fid):
                    flags.add(name)
        return model, flags
    if IS_MACOS:
        with contextlib.suppress(Exception):
            out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
            model = out or model
    return model, flags


# --------------------------------------------------------------------------- files
def secure_file(path: Path) -> None:
    """Restrict ``path`` to the current user (0600 / owner-only ACL)."""
    path = Path(path)
    if IS_WINDOWS:
        user = os.environ.get("USERNAME")
        if not user:
            return
        domain = os.environ.get("USERDOMAIN")
        principal = f"{domain}\\{user}" if domain else user
        with contextlib.suppress(Exception):
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{principal}:F"],
                capture_output=True, timeout=10, **_hidden_run_kwargs(),
            )
        return
    with contextlib.suppress(OSError):
        path.chmod(0o600)


def make_executable(path: Path) -> None:
    """chmod +x on POSIX; no-op on Windows (executability is by extension)."""
    if IS_WINDOWS:
        return
    with contextlib.suppress(OSError):
        Path(path).chmod(0o755)


def is_executable_file(path: Path) -> bool:
    path = Path(path)
    if not path.is_file():
        return False
    if IS_WINDOWS:
        return path.suffix.lower() in {".exe", ".cmd", ".bat", ".com"}
    return os.access(path, os.X_OK)


def exe_name(name: str) -> str:
    return f"{name}.exe" if IS_WINDOWS and not name.lower().endswith(".exe") else name


# --------------------------------------------------------------------------- python / hooks
def hook_command(script: Path, python: str | None = None) -> str:
    """Shell command an agent CLI runs to invoke a Python hook script.

    Uses the *current* interpreter (venv) rather than ``python3`` — on
    Windows ``python3`` is usually missing or the Microsoft Store stub.
    Paths are quoted and use forward slashes, which work unchanged in
    cmd.exe, PowerShell and the Git Bash shell Claude Code uses on Windows.
    """
    py = Path(python or sys.executable)
    if IS_WINDOWS:
        return f'"{py.as_posix()}" "{Path(script).as_posix()}"'
    import shlex

    return f"{shlex.quote(str(py))} {shlex.quote(str(script))}"


def background_python() -> str:
    """Interpreter for windowless background runs (``pythonw.exe`` on Windows)."""
    exe = Path(sys.executable)
    if IS_WINDOWS:
        candidate = exe.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return str(exe)

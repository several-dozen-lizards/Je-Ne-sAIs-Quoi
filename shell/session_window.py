"""Bounded Windows controls for the browser window owned by JNSQ.

The router may ask for exactly three operations against the recorded session
browser: minimize, toggle maximize/restore, or post a normal close message. It
cannot launch processes, target an arbitrary PID, or perform any other
shell/desktop action. The launcher may also remove the browser caption while
retaining its native resize frame.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import time
import uuid


TH32CS_SNAPPROCESS = 0x00000002
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
SW_MAXIMIZE = 3
SW_MINIMIZE = 6
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
WM_CLOSE = 0x0010
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
VT_LPWSTR = 31


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value: str):
        raw = uuid.UUID(value).bytes_le
        return cls.from_buffer_copy(raw)


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", wintypes.USHORT),
                ("wReserved1", wintypes.USHORT),
                ("wReserved2", wintypes.USHORT),
                ("wReserved3", wintypes.USHORT),
                ("pwszVal", wintypes.LPWSTR)]


IID_IPROPERTY_STORE = GUID.parse("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")
APP_USER_MODEL_FMTID = GUID.parse("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3")
PKEY_APP_USER_MODEL_RELAUNCH_COMMAND = PROPERTYKEY(APP_USER_MODEL_FMTID, 2)
PKEY_APP_USER_MODEL_RELAUNCH_ICON = PROPERTYKEY(APP_USER_MODEL_FMTID, 3)
PKEY_APP_USER_MODEL_ID = PROPERTYKEY(APP_USER_MODEL_FMTID, 5)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _process_tree(root_pid: int) -> set[int]:
    """Return the recorded browser process and its current descendants."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD,
                                                  wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE,
                                        ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE,
                                       ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), "process snapshot failed")
    parents: dict[int, int] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        available = bool(kernel32.Process32FirstW(snapshot,
                                                  ctypes.byref(entry)))
        while available:
            parents[int(entry.th32ProcessID)] = int(
                entry.th32ParentProcessID)
            available = bool(kernel32.Process32NextW(
                snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)

    owned = {int(root_pid)}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in owned and pid not in owned:
                owned.add(pid)
                changed = True
    return owned


def _owned_windows(root_pid: int) -> list[int]:
    """Find visible top-level windows in only the owned browser tree."""
    owned_pids = _process_tree(root_pid)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL

    windows: list[int] = []

    @callback_type
    def visit(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) in owned_pids and user32.IsWindowVisible(hwnd):
            windows.append(int(hwnd))
        return True

    if not user32.EnumWindows(visit, 0):
        raise OSError(ctypes.get_last_error(), "window enumeration failed")
    return windows


def _window_title(hwnd: int) -> str:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                      ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, len(title))
    return title.value


def _apply_window_action(hwnd: int, action: str) -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if action in {"minimize", "toggle-maximize"}:
        user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindowAsync.restype = wintypes.BOOL
        command = SW_MINIMIZE
        if action == "toggle-maximize":
            user32.IsZoomed.argtypes = [wintypes.HWND]
            user32.IsZoomed.restype = wintypes.BOOL
            command = SW_RESTORE if user32.IsZoomed(hwnd) else SW_MAXIMIZE
        return bool(user32.ShowWindowAsync(hwnd, command))
    if action == "close":
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                        wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
        return bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
    raise ValueError("unsupported session-window action")


def _window_is_maximized(hwnd: int) -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.IsZoomed.restype = wintypes.BOOL
    return bool(user32.IsZoomed(hwnd))


def _make_frameless_resizable(hwnd: int) -> bool:
    """Remove browser caption chrome but preserve native edge resizing."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    get_style = user32.GetWindowLongPtrW
    set_style = user32.SetWindowLongPtrW
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_style.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                    ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int,
                                    wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindowAsync.restype = wintypes.BOOL

    style = int(get_style(hwnd, GWL_STYLE))
    if not style:
        return False
    resizable = ((style & ~WS_CAPTION) | WS_THICKFRAME | WS_MINIMIZEBOX
                 | WS_MAXIMIZEBOX | WS_SYSMENU)
    ctypes.set_last_error(0)
    previous = set_style(hwnd, GWL_STYLE, resizable)
    if not previous and ctypes.get_last_error():
        return False
    frame_changed = user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE
        | SWP_FRAMECHANGED)
    maximized = user32.ShowWindowAsync(hwnd, SW_MAXIMIZE)
    return bool(frame_changed and maximized)


def _set_property_store_string(store: int, key: PROPERTYKEY,
                               value: str) -> bool:
    vtable = ctypes.cast(
        store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    set_value_type = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY),
        ctypes.POINTER(PROPVARIANT))
    set_value = set_value_type(vtable[6])
    text = ctypes.create_unicode_buffer(value)
    prop = PROPVARIANT(VT_LPWSTR, 0, 0, 0,
                       ctypes.cast(text, wintypes.LPWSTR))
    return int(set_value(store, ctypes.byref(key), ctypes.byref(prop))) >= 0


def _set_window_identity(hwnd: int, icon_path: str,
                         relaunch_command: str) -> bool:
    """Give the Edge-hosted window a JNSQ taskbar identity and icon."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.SHGetPropertyStoreForWindow.argtypes = [
        wintypes.HWND, ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
    store = ctypes.c_void_p()
    result = shell32.SHGetPropertyStoreForWindow(
        hwnd, ctypes.byref(IID_IPROPERTY_STORE), ctypes.byref(store))
    if result < 0 or not store.value:
        return False
    vtable = ctypes.cast(
        store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[7])
    release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtable[2])
    try:
        assigned = _set_property_store_string(
            store, PKEY_APP_USER_MODEL_ID, "JeNeSaisQuoi.Household")
        if relaunch_command:
            assigned = (_set_property_store_string(
                store, PKEY_APP_USER_MODEL_RELAUNCH_COMMAND,
                relaunch_command) and assigned)
        if icon_path:
            assigned = (_set_property_store_string(
                store, PKEY_APP_USER_MODEL_RELAUNCH_ICON,
                f"{icon_path},0") and assigned)
        assigned = int(commit(store)) >= 0 and assigned
    finally:
        release(store)

    if icon_path and os.path.isfile(icon_path):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                      wintypes.UINT, ctypes.c_int,
                                      ctypes.c_int, wintypes.UINT]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                        wintypes.WPARAM, wintypes.LPARAM]
        # ctypes.wintypes does not expose LRESULT on every supported Python
        # build. It is a pointer-sized signed integer on Windows.
        user32.SendMessageW.restype = ctypes.c_ssize_t
        for size, kind in ((32, ICON_BIG), (16, ICON_SMALL)):
            icon = user32.LoadImageW(
                None, icon_path, IMAGE_ICON, size, size, LR_LOADFROMFILE)
            if icon:
                user32.SendMessageW(hwnd, WM_SETICON, kind, icon)
    return assigned


def prepare_session_window(root_pid: int, timeout: float = 15.0, *,
                           expected_title: str = "Je Ne Sais Quoi",
                           icon_path: str = "",
                           relaunch_command: str = "") -> dict:
    """Turn the launched Chromium app into a frameless resizable JNSQ shell."""
    if os.name != "nt":
        return {"ok": False, "error": "windows_only"}
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        try:
            windows = _owned_windows(int(root_pid))
            if expected_title:
                windows = [hwnd for hwnd in windows
                           if _window_title(hwnd) == expected_title]
            prepared = sum(1 for hwnd in windows
                           if _make_frameless_resizable(hwnd))
        except (OSError, TypeError, ValueError):
            prepared = 0
        if prepared:
            identified = sum(
                1 for hwnd in windows
                if _set_window_identity(hwnd, icon_path, relaunch_command))
            return {"ok": True, "windows": prepared,
                    "resizable": True, "maximized": True,
                    "identified": identified}
        if time.monotonic() >= deadline:
            return {"ok": False, "error": "owned_window_not_found"}
        time.sleep(.05)


def control_session_window(runfile: str, action: str) -> dict:
    """Apply a bounded action to the exact session browser in ``runfile``."""
    if action not in {"minimize", "toggle-maximize", "close"}:
        return {"ok": False, "error": "unsupported_action"}
    if os.name != "nt":
        return {"ok": False, "error": "windows_only"}
    try:
        with open(runfile, encoding="utf-8") as handle:
            run = json.load(handle)
        browser_pid = int(run.get("session_browser_pid") or 0)
    except (FileNotFoundError, OSError, TypeError, ValueError,
            json.JSONDecodeError):
        return {"ok": False, "error": "session_receipt_unavailable"}
    if browser_pid <= 0:
        return {"ok": False, "error": "session_window_unavailable"}
    try:
        windows = _owned_windows(browser_pid)
        applied = sum(1 for hwnd in windows
                      if _apply_window_action(hwnd, action))
    except OSError:
        return {"ok": False, "error": "window_control_failed"}
    if not applied:
        return {"ok": False, "error": "owned_window_not_found"}
    result = {"ok": True, "action": action, "windows": applied}
    if action == "toggle-maximize":
        result["maximized"] = any(_window_is_maximized(hwnd)
                                  for hwnd in windows)
    return result

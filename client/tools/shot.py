"""Capture a window of a process to PNG (PrintWindow + PW_RENDERFULLCONTENT; no dependencies).

    python shot.py <pid> <out.png> [scale]
"""
import ctypes
import ctypes.wintypes as wt
import struct
import sys
import zlib

u32 = ctypes.WinDLL("user32", use_last_error=True)
g32 = ctypes.WinDLL("gdi32", use_last_error=True)
u32.SetProcessDPIAware()
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
u32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
u32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
u32.GetDC.argtypes = [wt.HWND]
u32.GetDC.restype = wt.HDC
u32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
g32.CreateCompatibleDC.argtypes = [wt.HDC]
g32.CreateCompatibleDC.restype = wt.HDC
g32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD]
g32.CreateDIBSection.restype = wt.HBITMAP
g32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
g32.SelectObject.restype = wt.HGDIOBJ
g32.DeleteObject.argtypes = [wt.HGDIOBJ]
g32.DeleteDC.argtypes = [wt.HDC]


def windows_of(pid):
    out = []

    def cb(hwnd, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, buf, 256)
            r = wt.RECT()
            u32.GetClientRect(hwnd, ctypes.byref(r))
            out.append((hwnd, buf.value, r.right - r.left, r.bottom - r.top))
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def png(path, w, h, rgb):
    raw = b"".join(b"\0" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(t, data):
        c = struct.pack(">I", len(data)) + t + data
        return c + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def capture(pid, path, scale=0.5):
    wins = sorted(windows_of(pid), key=lambda x: -x[2] * x[3])
    if not wins:
        return None
    hwnd, title, w, h = wins[0]
    if w <= 0 or h <= 0:
        return None
    sdc = u32.GetDC(hwnd)
    mdc = g32.CreateCompatibleDC(sdc)
    bmi = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    hbmp = g32.CreateDIBSection(mdc, bmi, 0, ctypes.byref(bits), None, 0)
    old = g32.SelectObject(mdc, hbmp)
    ok = u32.PrintWindow(hwnd, mdc, 3)  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    data = ctypes.string_at(bits, w * h * 4)
    g32.SelectObject(mdc, old)
    g32.DeleteObject(hbmp)
    g32.DeleteDC(mdc)
    u32.ReleaseDC(hwnd, sdc)
    step = max(1, round(1 / scale))
    ow, oh = w // step, h // step
    rgb = bytearray(ow * oh * 3)
    for y in range(oh):
        row = data[(y * step) * w * 4:(y * step + 1) * w * 4]
        o = y * ow * 3
        for x in range(ow):
            i = x * step * 4
            rgb[o + 3 * x] = row[i + 2]
            rgb[o + 3 * x + 1] = row[i + 1]
            rgb[o + 3 * x + 2] = row[i]
    png(path, ow, oh, bytes(rgb))
    return dict(title=title, w=w, h=h, ok=ok)


if __name__ == "__main__":
    print(capture(int(sys.argv[1]), sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 0.5))

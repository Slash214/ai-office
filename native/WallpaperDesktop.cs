using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

// Keeps a window owned by this process behind the icons on the primary display.
// All methods run on the WinForms UI thread. Dispose before destroying the form.
internal sealed class WallpaperDesktop : IDisposable
{
    private const int Style = -16, ExStyle = -20;
    private const int Child = 0x40000000, Popup = unchecked((int)0x80000000);
    private const int Frame = 0x00C40000, Disabled = 0x08000000, Visible = 0x10000000;
    private const int NoActivate = 0x08000000, Transparent = 0x20, Layered = 0x80000;
    private const int AppWindow = 0x40000, NoRedirectionBitmap = 0x200000;
    private const uint FrameChanged = 0x20, Show = 0x40, NoZOrder = 4, DoNotActivate = 0x10;
    private const uint NoOwnerZOrder = 0x200, NextWindow = 2;
    private IntPtr window, parent, icons, background;
    private int originalStyle, originalExStyle;

    [StructLayout(LayoutKind.Sequential)]
    private struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)]
    private struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)]
    private struct MonitorInfo { public int Size; public Rect Bounds, Work; public uint Flags; }
    private delegate bool EnumProc(IntPtr hwnd, IntPtr data);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr FindWindow(string cls, string title);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr FindWindowEx(IntPtr p, IntPtr after, string cls, string title);
    [DllImport("user32.dll")] private static extern IntPtr GetShellWindow();
    [DllImport("user32.dll")] private static extern IntPtr GetParent(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern IntPtr GetWindow(IntPtr hwnd, uint direction);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumProc callback, IntPtr data);
    [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("kernel32.dll")] private static extern uint GetCurrentProcessId();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern IntPtr SendMessageTimeout(IntPtr hwnd, uint message, IntPtr wParam, IntPtr lParam, uint flags, uint timeout, out IntPtr result);
    [DllImport("user32.dll")] private static extern int GetWindowLong(IntPtr hwnd, int index);
    [DllImport("user32.dll", SetLastError = true)] private static extern int SetWindowLong(IntPtr hwnd, int index, int value);
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr SetParent(IntPtr child, IntPtr p);
    [DllImport("user32.dll", SetLastError = true)] private static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll", SetLastError = true)] private static extern bool SetLayeredWindowAttributes(IntPtr hwnd, uint key, byte alpha, uint flags);
    [DllImport("user32.dll")] private static extern bool ScreenToClient(IntPtr hwnd, ref Point p);
    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hwnd, out Rect area);
    [DllImport("user32.dll")] private static extern IntPtr MonitorFromPoint(Point p, uint flags);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern bool GetMonitorInfo(IntPtr monitor, ref MonitorInfo monitorInfo);
    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr hwnd, int command);
    [DllImport("user32.dll")] private static extern bool InvalidateRect(IntPtr hwnd, IntPtr rect, bool erase);

    private static uint OwnerProcess(IntPtr hwnd)
    {
        uint pid;
        GetWindowThreadProcessId(hwnd, out pid);
        return pid;
    }

    // Shell children are enumerated from front to back. The cap handles shell churn.
    private static bool IsBelow(IntPtr front, IntPtr back)
    {
        for (int i = 0; i < 256 && front != IntPtr.Zero; ++i)
        {
            front = GetWindow(front, NextWindow);
            if (front == back) return back != IntPtr.Zero;
        }
        return false;
    }

    private static bool FindLayers(IntPtr progman, uint explorer, out IntPtr target, out IntPtr view, out IntPtr paper)
    {
        target = IntPtr.Zero;
        view = FindWindowEx(progman, IntPtr.Zero, "SHELLDLL_DefView", null);
        paper = FindWindowEx(progman, IntPtr.Zero, "WorkerW", null);
        if ((GetWindowLong(progman, ExStyle) & NoRedirectionBitmap) != 0)
        {
            // Windows 11 raised desktop: icons, our layered window, system background.
            if (view == IntPtr.Zero || paper == IntPtr.Zero || !IsBelow(view, paper)) return false;
            target = progman;
            return true;
        }

        // Earlier shell layout: a separate top-level WorkerW below the icon host.
        IntPtr legacy = IntPtr.Zero;
        EnumWindows(delegate(IntPtr top, IntPtr unused)
        {
            if (OwnerProcess(top) != explorer || FindWindowEx(top, IntPtr.Zero, "SHELLDLL_DefView", null) == IntPtr.Zero) return true;
            IntPtr next = top;
            while ((next = FindWindowEx(IntPtr.Zero, next, "WorkerW", null)) != IntPtr.Zero)
            {
                if (OwnerProcess(next) != explorer || FindWindowEx(next, IntPtr.Zero, "SHELLDLL_DefView", null) != IntPtr.Zero) continue;
                legacy = next;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        target = legacy;
        view = paper = IntPtr.Zero;
        return target != IntPtr.Zero;
    }

    private static bool Resolve(out IntPtr target, out IntPtr view, out IntPtr paper)
    {
        target = view = paper = IntPtr.Zero;
        IntPtr shell = GetShellWindow(), manager = FindWindow("Progman", null);
        uint explorer = OwnerProcess(shell);
        if (manager == IntPtr.Zero || explorer == 0 || OwnerProcess(manager) != explorer) return false;
        if (FindLayers(manager, explorer, out target, out view, out paper)) return true;
        // Ask Explorer to create its normal wallpaper layer. A hung Explorer cannot block the UI.
        IntPtr result;
        SendMessageTimeout(manager, 0x052C, new IntPtr(13), new IntPtr(1), 2, 800, out result);
        return FindLayers(manager, explorer, out target, out view, out paper);
    }

    private bool OwnsWindow { get { return window != IntPtr.Zero && IsWindow(window) && OwnerProcess(window) == GetCurrentProcessId(); } }

    public bool IsAttached
    {
        get
        {
            if (!OwnsWindow || parent == IntPtr.Zero || GetParent(window) != parent) return false;
            return icons == IntPtr.Zero || (IsBelow(icons, window) && IsBelow(window, background));
        }
    }

    public bool TryAttach(IntPtr hwnd, out string error)
    {
        error = null;
        if (window != IntPtr.Zero)
        {
            if (window == hwnd) return TryRefresh(out error);
            error = "壁纸窗口已在使用。";
            return false;
        }
        if (!IsWindow(hwnd) || OwnerProcess(hwnd) != GetCurrentProcessId() || GetParent(hwnd) != IntPtr.Zero)
        {
            error = "请先创建独立的工作室壁纸窗口。";
            return false;
        }
        window = hwnd;
        originalStyle = GetWindowLong(window, Style);
        originalExStyle = GetWindowLong(window, ExStyle);
        if (TryRefresh(out error)) return true;
        Dispose();
        return false;
    }

    public bool TryRefresh(out string error)
    {
        error = null;
        IntPtr target, view, paper;
        if (!OwnsWindow) { error = "壁纸窗口已关闭，请重新开启。"; return false; }
        if (!Resolve(out target, out view, out paper))
        {
            error = "Windows 资源管理器的桌面图层暂不可用，请在普通桌面重新开启壁纸。";
            return false;
        }
        bool reparent = GetParent(window) != target || parent != target;
        if (reparent)
        {
            int style = (originalStyle | Child | Disabled) & ~(Popup | Frame);
            int exStyle = (originalExStyle | NoActivate | Transparent) & ~AppWindow;
            if (view != IntPtr.Zero) exStyle |= Layered;
            SetWindowLong(window, Style, style);
            SetWindowLong(window, ExStyle, exStyle);
            if (view != IntPtr.Zero && !SetLayeredWindowAttributes(window, 0, 255, 2))
            {
                error = "无法创建桌面合成图层。" + new Win32Exception().Message;
                return false;
            }
            SetParent(window, target);
            if (GetParent(window) != target)
            {
                error = "无法嵌入 Windows 桌面。" + new Win32Exception().Message;
                return false;
            }
        }
        parent = target;
        icons = view;
        background = paper;
        MonitorInfo monitor = new MonitorInfo { Size = Marshal.SizeOf(typeof(MonitorInfo)) };
        if (!GetMonitorInfo(MonitorFromPoint(new Point(), 1), ref monitor))
        {
            error = "无法读取主显示器范围。";
            return false;
        }
        Rect actual, bounds = monitor.Bounds;
        bool ordered = IsAttached;
        if (!reparent && ordered && GetWindowRect(window, out actual)
            && actual.Left == bounds.Left && actual.Top == bounds.Top && actual.Right == bounds.Right && actual.Bottom == bounds.Bottom) return true;
        Point origin = new Point { X = bounds.Left, Y = bounds.Top };
        uint flags = DoNotActivate | NoOwnerZOrder | Show;
        if (reparent) flags |= FrameChanged;
        if (ordered && view == IntPtr.Zero) flags |= NoZOrder;
        if (!ScreenToClient(target, ref origin)
            || !SetWindowPos(window, view, origin.X, origin.Y, bounds.Right - bounds.Left, bounds.Bottom - bounds.Top, flags)
            || !IsAttached)
        {
            error = "无法将工作室安全地放在桌面图标下方。";
            return false;
        }
        return true;
    }

    public void Dispose()
    {
        if (OwnsWindow && (parent != IntPtr.Zero || GetWindowLong(window, Style) != originalStyle))
        {
            ShowWindow(window, 0);
            SetParent(window, IntPtr.Zero);
            SetWindowLong(window, Style, originalStyle & ~Visible);
            SetWindowLong(window, ExStyle, originalExStyle);
            if (IsWindow(parent)) InvalidateRect(parent, IntPtr.Zero, false);
        }
        window = parent = icons = background = IntPtr.Zero;
    }
}

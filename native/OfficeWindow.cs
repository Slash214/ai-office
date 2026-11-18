using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal sealed class OfficeWindow : Form
{
    private readonly Uri home = new Uri("http://127.0.0.1:" + Program.Port + "/");
    private readonly Color night = Color.FromArgb(12, 17, 35);
    private readonly NotifyIcon tray;
    private readonly ToolStripMenuItem toggle;
    private readonly ToolStripMenuItem reminders = new ToolStripMenuItem("打开待办提醒") { Visible = false };
    private readonly Timer refresh = new Timer { Interval = 3000 };
    private readonly Timer attentionPoll = new Timer { Interval = 10000 };
    private readonly Timer releaseHiddenOffice = new Timer { Interval = 12000 };
    private readonly ContextMenuStrip menu = new ContextMenuStrip();
    private readonly JavaScriptSerializer serializer = new JavaScriptSerializer();
    private readonly Label loading;
    private readonly Icon officeIcon;
    private readonly string attentionLedger = Path.Combine(Program.Root, ".office-data", "tray-seen-" + Program.Port + ".txt");
    private HashSet<string> seenAttention;
    private bool pollingAttention, balloonOpen, deliveringTask;
    private string balloonTask, requestedTask;
    private string reminderSignature;
    private bool serviceReady;
    private WebView2 browser;
    private Form wallpaper;
    private WallpaperDesktop desktop;
    private bool changing, exit, startWallpaper, openingView, officeRequested, mayReleaseWhileHidden;
    private int visibilityChange;
    private bool? lastOfficeVisible;
    private string lastError;
    [StructLayout(LayoutKind.Sequential)]
    private struct ClientRect { internal int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr window, out ClientRect rect);
    [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int width, int height, uint flags);

    internal OfficeWindow(bool startWallpaper)
    {
        this.startWallpaper = startWallpaper;
        officeRequested = !startWallpaper;
        if (startWallpaper) { ShowInTaskbar = false; WindowState = FormWindowState.Minimized; }
        Text = Program.Title;
        BackColor = night;
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Dpi;
        Rectangle area = Screen.FromPoint(Cursor.Position).WorkingArea;
        Size = new Size(Math.Min(1480, (int)(area.Width * .9)), Math.Min(994, (int)(area.Height * .9)));
        MinimumSize = new Size(420, 360);
        officeIcon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        Icon = officeIcon;
        loading = new Label { Text = "正在打开办公室…", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter,
            ForeColor = Color.WhiteSmoke, BackColor = night, Font = new Font("Microsoft YaHei UI", 13) };
        Controls.Add(loading);
        menu.Items.Add(reminders);
        menu.Items.Add("打开工作室", null, delegate { RestoreOffice(); });
        toggle = new ToolStripMenuItem("开启桌面壁纸", null, async delegate { await ChangeWallpaper(wallpaper == null); });
        toggle.Enabled = false;
        menu.Items.Add(toggle);
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("退出工作室", null, delegate { exit = true; Close(); });
        tray = new NotifyIcon { Icon = officeIcon, Text = Program.Title, ContextMenuStrip = menu, Visible = true };
        tray.DoubleClick += delegate { RestoreOffice(); };
        tray.BalloonTipClicked += delegate {
            string task = balloonTask;
            ReleaseBalloon();
            if (task != null) requestedTask = task;
            RestoreOffice();
        };
        tray.BalloonTipClosed += delegate { ReleaseBalloon(); };
        attentionPoll.Tick += delegate { PollAttention(); };
        refresh.Tick += RefreshDesktop;
        releaseHiddenOffice.Tick += delegate {
            releaseHiddenOffice.Stop();
            if (OfficeVisible || !mayReleaseWhileHidden || wallpaper == null || browser == null) return;
            var old = browser;
            browser = null;
            lastOfficeVisible = null;
            mayReleaseWhileHidden = false;
            // Close the controller while still attached to its own form.
            var core = old.CoreWebView2;
            if (core != null && core.IsSuspended) core.Resume();
            old.Dispose();
            loading.Visible = true;
        };
        Resize += delegate { ScheduleViewportLayout(); UpdateOfficeActivity(); };
        VisibleChanged += delegate { UpdateOfficeActivity(); };
        LocationChanged += delegate { ScheduleViewportLayout(); };
        Activated += delegate { ScheduleViewportLayout(); };
        Shown += async delegate { await OpenOffice(); };
    }

    internal void QueueCommand(bool? requestWallpaper)
    {
        if (!IsHandleCreated || IsDisposed) return;
        try { BeginInvoke(new Action(async delegate {
            if (!requestWallpaper.HasValue) { RestoreOffice(); return; }
            if (!serviceReady) startWallpaper = requestWallpaper.Value;
            else await ChangeWallpaper(requestWallpaper.Value);
        })); }
        catch (InvalidOperationException) { }
    }

    private void RestoreOffice()
    {
        officeRequested = true;
        ShowInTaskbar = true;
        Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
        ScheduleViewportLayout();
        if (browser != null) browser.Focus();
        else if (serviceReady) OpenManager();
        FocusRequestedTask();
    }

    private bool OfficeVisible { get { return Visible && WindowState != FormWindowState.Minimized; } }

    private void ReleaseBalloon()
    {
        balloonOpen = false;
        balloonTask = null;
    }

    private void ShowBalloon(int duration, string title, string body, ToolTipIcon icon, string task = null)
    {
        if (balloonOpen) return;
        balloonOpen = true;
        balloonTask = task;
        tray.ShowBalloonTip(duration, title, body, icon);
    }

    private async void PollAttention()
    {
        FocusRequestedTask();
        if (pollingAttention || exit || IsDisposed) return;
        pollingAttention = true;
        try {
            var notifications = await Program.ReadNotifications();
            if (exit || IsDisposed) return;
            var active = new List<Tuple<string, string, string>>();
            foreach (var item in notifications) {
                Guid task;
                if (item == null || string.IsNullOrEmpty(item.id) || item.id.Length > 512 ||
                    !Guid.TryParseExact(item.taskId, "D", out task) || task == Guid.Empty) continue;
                string title;
                switch (item.kind) {
                    case "review": title = "工作室任务待验收"; break;
                    case "input": title = "工作室任务需要你补充信息"; break;
                    case "failed": title = "工作室有任务步骤失败"; break;
                    default: continue;
                }
                active.Add(Tuple.Create(item.id, task.ToString("D"), title));
            }
            UpdateReminderMenu(active);
            if (balloonOpen) return;
            foreach (var item in active) {
                if (!RememberAttention(item.Item1)) continue;
                ShowBalloon(7000, item.Item3, "点击查看对应任务。", ToolTipIcon.Info, item.Item2);
                break;
            }
        }
        catch (WebException) { }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        catch (ArgumentException) { }
        catch (InvalidOperationException) { }
        finally { pollingAttention = false; }
    }

    private void UpdateReminderMenu(List<Tuple<string, string, string>> active)
    {
        string signature = string.Join("\n", active.ConvertAll(item => item.Item2 + item.Item3));
        if (reminderSignature == signature) return;
        reminderSignature = signature;
        while (reminders.DropDownItems.Count > 0) reminders.DropDownItems[0].Dispose();
        for (int index = 0; index < active.Count; index++) {
            var item = active[index];
            string label = active.Count == 1 ? item.Item3 : (index + 1) + ". " + item.Item3;
            reminders.DropDownItems.Add(label, null, delegate {
                requestedTask = item.Item2;
                RestoreOffice();
            });
        }
        reminders.Visible = active.Count > 0;
    }

    private bool RememberAttention(string id)
    {
        string fingerprint;
        using (var sha = SHA256.Create())
            fingerprint = Convert.ToBase64String(sha.ComputeHash(Encoding.UTF8.GetBytes(id)));
        if (seenAttention == null) {
            Directory.CreateDirectory(Path.GetDirectoryName(attentionLedger));
            seenAttention = new HashSet<string>(File.Exists(attentionLedger) ? File.ReadAllLines(attentionLedger) : new string[0]);
        }
        if (seenAttention.Contains(fingerprint)) return false;
        File.AppendAllText(attentionLedger, fingerprint + Environment.NewLine);
        seenAttention.Add(fingerprint);
        return true;
    }

    private async void FocusRequestedTask()
    {
        if (requestedTask == null || deliveringTask || !OfficeVisible || browser == null || browser.IsDisposed) return;
        var core = browser.CoreWebView2;
        if (core == null || core.IsSuspended) return;
        string task = requestedTask;
        deliveringTask = true;
        try {
            string delivered = await core.ExecuteScriptAsync(
                "typeof window.officeOpenTask === 'function' && (window.officeOpenTask(" + serializer.Serialize(task) + "), true)");
            if (delivered == "true" && requestedTask == task) requestedTask = null;
        }
        catch (InvalidOperationException) { }
        catch (COMException) { }
        finally { deliveringTask = false; }
        if (requestedTask != task) FocusRequestedTask();
    }

    private async void UpdateOfficeActivity()
    {
        var view = browser;
        if (exit || IsDisposed || view == null || view.IsDisposed || view.CoreWebView2 == null) return;
        if (lastOfficeVisible == OfficeVisible) return;
        lastOfficeVisible = OfficeVisible;
        int request = ++visibilityChange;
        mayReleaseWhileHidden = false;
        releaseHiddenOffice.Stop();
        var core = view.CoreWebView2;
        try
        {
            if (OfficeVisible) {
                view.Visible = true;
                if (core.IsSuspended) core.Resume();
                core.MemoryUsageTargetLevel = CoreWebView2MemoryUsageTargetLevel.Normal;
                PublishState(core);
                return;
            }
            view.Visible = false;
            if (core.IsSuspended) return;
            // A draft or an open task keeps its WebView. Its DOM survives suspension.
            string idle = await core.ExecuteScriptAsync("Boolean(window.officeMayReleaseView && window.officeMayReleaseView())");
            if (request != visibilityChange || OfficeVisible || browser != view || view.IsDisposed) return;
            core.MemoryUsageTargetLevel = CoreWebView2MemoryUsageTargetLevel.Low;
            mayReleaseWhileHidden = idle == "true";
            ScheduleHiddenRelease();
            await core.TrySuspendAsync();
            if (browser == view && !view.IsDisposed && OfficeVisible && core.IsSuspended) core.Resume();
        }
        catch (InvalidOperationException) { }
        catch (NotImplementedException) { }
        catch (COMException) { }
    }

    private void ScheduleHiddenRelease()
    {
        if (!OfficeVisible && browser != null && wallpaper != null && mayReleaseWhileHidden)
            releaseHiddenOffice.Start();
        else
            releaseHiddenOffice.Stop();
    }

    private async void OpenManager()
    {
        if (openingView || browser != null || IsDisposed || exit) return;
        openingView = true;
        string task = requestedTask;
        try {
            string path = "?desktop=1" + (task == null ? "" : "&task=" + task) + "#office";
            browser = await OpenView(this, path, false);
            if (requestedTask == task) requestedTask = null;
            if (IsDisposed) return;
            loading.Visible = false;
            ScheduleViewportLayout();
            if (OfficeVisible) browser.Focus(); else UpdateOfficeActivity();
            FocusRequestedTask();
        }
        catch (Exception ex) {
            if (!IsDisposed) { loading.Text = "办公室未能打开"; MessageBox.Show(this, ex.GetBaseException().Message, Program.Title); }
        }
        finally { openingView = false; }
    }

    private void ScheduleViewportLayout()
    {
        if (browser == null || !IsHandleCreated || IsDisposed || WindowState == FormWindowState.Minimized || !Visible) return;
        BeginInvoke(new Action(delegate {
            if (browser == null || browser.IsDisposed || !browser.IsHandleCreated || WindowState == FormWindowState.Minimized || !Visible) return;
            // Explorer can reposition a top-level host after it has been minimized.
            // Anchor the real WebView child HWND even if WinForms cached a stale origin.
            ClientRect client;
            if (GetClientRect(Handle, out client))
                SetWindowPos(browser.Handle, IntPtr.Zero, 0, 0, client.Right, client.Bottom, 0x14);
        }));
    }

    private async Task OpenOffice()
    {
        try
        {
            await Program.StartService();
            if (IsDisposed) return;
            serviceReady = true;
            toggle.Enabled = true;
            attentionPoll.Start();
            PollAttention();
            if (startWallpaper) {
                if (!officeRequested) Hide();
                startWallpaper = false;
                await ChangeWallpaper(true);
                if (wallpaper == null && !officeRequested && !IsDisposed) RestoreOffice();
            }
            if (officeRequested && !IsDisposed) OpenManager();
            else if (wallpaper == null && !IsDisposed) RestoreOffice();
        }
        catch (Exception ex)
        {
            if (IsDisposed) return;
            loading.Text = "办公室未能打开";
            MessageBox.Show(this, ex.GetBaseException().Message, Program.Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            exit = true;
            Close();
        }
    }

    private bool LocalDocument(string value)
    {
        Uri uri;
        return Uri.TryCreate(value, UriKind.Absolute, out uri) && uri.Scheme == home.Scheme &&
            uri.Host == home.Host && uri.Port == home.Port && uri.UserInfo == "" &&
            (uri.AbsolutePath == "/" || uri.AbsolutePath == "/wallpaper.html" || uri.AbsolutePath == "/index.html");
    }

    private void OpenDotLink(string value, bool clicked, bool background)
    {
        Uri uri;
        if (background || !clicked || !Uri.TryCreate(value, UriKind.Absolute, out uri) ||
            uri.Scheme != "https" || uri.Host != "chatgpt.com" || !uri.IsDefaultPort ||
            uri.UserInfo != "" || uri.Query != "" || uri.Fragment != "") return;
        if (uri.AbsolutePath != "/" && !Regex.IsMatch(uri.AbsolutePath,
            @"^/dots/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}~[0-9a-f]{32}/?$",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)) return;
        try { Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true }); }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "打开 Dot 会话", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }

    private async Task<WebView2> OpenView(Form host, string path, bool background)
    {
        var view = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = night, TabStop = !background };
        host.Controls.Add(view);
        view.BringToFront();
        try
        {
            // Wallpaper has its own browser process. Releasing a suspended task window
            // must never terminate the renderer attached to the Windows desktop.
            string profile = background ? "wallpaper-webview" : "desktop-webview";
            var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(Program.Root, ".office-data", profile));
            await view.EnsureCoreWebView2Async(environment);
            var web = view.CoreWebView2;
            web.Settings.AreDefaultContextMenusEnabled = false;
            web.Settings.IsStatusBarEnabled = false;
            web.Settings.AreDevToolsEnabled = false;
            web.Settings.AreHostObjectsAllowed = false;
            web.Settings.IsWebMessageEnabled = !background;
            if (background) web.IsMuted = true;
            web.PermissionRequested += (sender, e) => { e.State = CoreWebView2PermissionState.Deny; };
            web.NewWindowRequested += (sender, e) => { e.Handled = true; OpenDotLink(e.Uri, e.IsUserInitiated, background); };
            web.NavigationStarting += (sender, e) => {
                if (LocalDocument(e.Uri)) return;
                if (!background && e.IsUserInitiated &&
                    string.Equals(e.Uri, new Uri(home, "join/office-connector.zip").AbsoluteUri, StringComparison.Ordinal)) return;
                e.Cancel = true;
                OpenDotLink(e.Uri, e.IsUserInitiated, background);
            };
            if (!background) web.WebMessageReceived += async (sender, e) => {
                if (!LocalDocument(e.Source) || IsDisposed) return;
                string message;
                try { message = e.TryGetWebMessageAsString(); } catch (ArgumentException) { return; }
                if (message == "wallpaper-status") PublishState(web);
                else if (message == "toggle-wallpaper") await ChangeWallpaper(wallpaper == null);
            };
            var loaded = new TaskCompletionSource<bool>();
            web.NavigationCompleted += (sender, e) => {
                if (e.IsSuccess) loaded.TrySetResult(true);
                else loaded.TrySetException(new InvalidOperationException("办公室网页加载失败 (" + e.WebErrorStatus + ")。"));
            };
            web.Navigate(new Uri(home, path).AbsoluteUri);
            if (await Task.WhenAny(loaded.Task, Task.Delay(20000)) != loaded.Task)
                throw new TimeoutException("等待办公室网页加载超时。");
            await loaded.Task;
            return view;
        }
        catch { view.Dispose(); throw; }
    }

    private void PublishState(CoreWebView2 web = null)
    {
        toggle.Enabled = serviceReady && !changing;
        toggle.Text = wallpaper == null ? "开启桌面壁纸" : "关闭桌面壁纸";
        if (web == null && browser != null && !browser.IsDisposed) web = browser.CoreWebView2;
        if (web != null && !web.IsSuspended)
            web.PostWebMessageAsJson(serializer.Serialize(new { type = "wallpaper", enabled = wallpaper != null && desktop != null && desktop.IsAttached,
                busy = changing, error = lastError }));
    }

    private async Task ChangeWallpaper(bool enable)
    {
        if (IsDisposed || changing || !serviceReady || enable == (wallpaper != null)) return;
        changing = true;
        lastError = null;
        PublishState();
        try
        {
            if (!enable) { RemoveWallpaper(); return; }
            var form = new WallpaperForm {
                Text = Program.Title + " · 桌面壁纸", FormBorderStyle = FormBorderStyle.None,
                StartPosition = FormStartPosition.Manual, Bounds = new Rectangle(SystemInformation.VirtualScreen.Right + 16, 0, 16, 16), BackColor = night
            };
            wallpaper = form;
            desktop = new WallpaperDesktop();
            string reason;
            form.Show();
            if (!desktop.TryAttach(form.Handle, out reason)) throw new InvalidOperationException(reason);
            await OpenView(form, "?wallpaper=1", true);
            if (IsDisposed) return;
            refresh.Start();
        }
        catch (Exception ex)
        {
            if (IsDisposed) return;
            RemoveWallpaper();
            ReportWallpaperError(ex.GetBaseException().Message);
        }
        finally { changing = false; if (!IsDisposed) { ScheduleHiddenRelease(); PublishState(); ScheduleViewportLayout(); } }
    }

    private void RefreshDesktop(object sender, EventArgs e)
    {
        if (changing || wallpaper == null) return;
        string reason = "Explorer 已关闭壁纸窗口。";
        if (!wallpaper.IsDisposed && wallpaper.IsHandleCreated && desktop.TryRefresh(out reason)) return;
        RemoveWallpaper();
        ReportWallpaperError(reason);
        PublishState();
    }

    private void ReportWallpaperError(string detail)
    {
        lastError = "壁纸未能保持开启。" + detail;
        if (Visible) MessageBox.Show(this, lastError, "桌面壁纸", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        else ShowBalloon(4500, "桌面壁纸已关闭", lastError, ToolTipIcon.Warning);
    }

    private void RemoveWallpaper()
    {
        refresh.Stop();
        releaseHiddenOffice.Stop();
        if (desktop != null) { desktop.Dispose(); desktop = null; }
        if (wallpaper != null) { wallpaper.Dispose(); wallpaper = null; }
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (!exit && wallpaper != null && e.CloseReason == CloseReason.UserClosing)
        {
            e.Cancel = true;
            Hide();
            ShowBalloon(2500, "办公室仍在桌面运行", "双击托盘图标可以回到工作室派单。", ToolTipIcon.Info);
        }
        base.OnFormClosing(e);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing && !IsDisposed)
        {
            RemoveWallpaper();
            refresh.Dispose();
            attentionPoll.Dispose();
            releaseHiddenOffice.Dispose();
            tray.Visible = false;
            tray.Dispose();
            menu.Dispose();
            officeIcon.Dispose();
        }
        base.Dispose(disposing);
    }

    private sealed class WallpaperForm : Form
    {
        protected override bool ShowWithoutActivation { get { return true; } }
        protected override CreateParams CreateParams
        {
            get
            {
                var p = base.CreateParams;
                p.ExStyle = (p.ExStyle | 0x80 | 0x08000000) & ~0x00040000; // Tool window, never activates.
                return p;
            }
        }
    }
}

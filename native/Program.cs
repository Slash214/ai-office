using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;

[assembly: AssemblyTitle("【呵呵】AI工作室")]
[assembly: AssemblyDescription("本地三维办公室与动态桌面")]
[assembly: AssemblyProduct("【呵呵】AI工作室")]
[assembly: AssemblyVersion("1.0.0.0")]

internal static class Program
{
    internal const string Title = "【呵呵】AI工作室";
    internal static readonly string Root = AppDomain.CurrentDomain.BaseDirectory;
    internal static readonly string Libraries = Path.Combine(Root, "native", "webview2");
    internal static int Port;

    internal sealed class AttentionNotification
    {
        public string id { get; set; }
        public string taskId { get; set; }
        public string kind { get; set; }
    }

    private sealed class NotificationResponse
    {
        public AttentionNotification[] notifications { get; set; }
    }

    internal static Task<AttentionNotification[]> ReadNotifications()
    {
        return Task.Run(delegate
        {
            var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + Port + "/api/notifications");
            request.Proxy = null;
            request.AllowAutoRedirect = false;
            request.Timeout = 3500;
            request.ReadWriteTimeout = 3500;
            request.Accept = "application/json";
            using (var response = (HttpWebResponse)request.GetResponse())
            using (var stream = response.GetResponseStream())
            using (var reader = new StreamReader(stream, Encoding.UTF8))
            {
                if (response.StatusCode != HttpStatusCode.OK) return new AttentionNotification[0];
                const int limit = 256 * 1024;
                var json = new StringBuilder();
                var buffer = new char[4096];
                int count;
                while ((count = reader.Read(buffer, 0, buffer.Length)) > 0)
                {
                    if (json.Length + count > limit) throw new InvalidDataException("Invalid notification response.");
                    json.Append(buffer, 0, count);
                }
                var value = new JavaScriptSerializer().Deserialize<NotificationResponse>(json.ToString());
                return value == null ? new AttentionNotification[0] : value.notifications ?? new AttentionNotification[0];
            }
        });
    }

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            AppDomain.CurrentDomain.AssemblyResolve += LoadWebViewAssembly;
            if (!int.TryParse(Environment.GetEnvironmentVariable("OFFICE_PORT") ?? "8765", out Port) ||
                Port < 1 || Port > 65535)
                throw new InvalidOperationException("OFFICE_PORT 需要是 1 到 65535 之间的端口号。");
            string mode = args.Length == 1 ? args[0] : "";
            return Run(mode);
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.GetBaseException().Message, Title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static Assembly LoadWebViewAssembly(object sender, ResolveEventArgs e)
    {
        string name = new AssemblyName(e.Name).Name;
        if (name != "Microsoft.Web.WebView2.Core" && name != "Microsoft.Web.WebView2.WinForms") return null;
        return Assembly.LoadFrom(Path.Combine(Libraries, name + ".dll"));
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int Run(string mode)
    {
        string signature;
        using (var hash = SHA256.Create())
            signature = BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(Root.ToUpperInvariant() + Port)), 0, 12).Replace("-", "");
        string name = @"Local\HeheAiOffice-" + signature;
        bool primary;
        using (var show = new EventWaitHandle(false, EventResetMode.AutoReset, name + "-show"))
        using (var wallpaper = new EventWaitHandle(false, EventResetMode.AutoReset, name + "-wallpaper"))
        using (var off = new EventWaitHandle(false, EventResetMode.AutoReset, name + "-wallpaper-off"))
        using (var single = new Mutex(true, name, out primary))
        {
            if (!primary)
            {
                (mode == "--wallpaper" ? wallpaper : mode == "--wallpaper-off" ? off : show).Set();
                return 0;
            }
            try
            {
                if (mode == "--wallpaper-off") return 0;
                CoreWebView2Environment.SetLoaderDllFolderPath(Libraries);
                if (string.IsNullOrEmpty(CoreWebView2Environment.GetAvailableBrowserVersionString()))
                    throw new InvalidOperationException("此电脑需要 Microsoft Edge WebView2 Runtime 才能显示办公室。");
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                using (var office = new OfficeWindow(mode == "--wallpaper"))
                {
                    IntPtr handle = office.Handle;
                    RegisteredWaitHandle a = ThreadPool.RegisterWaitForSingleObject(show, delegate { office.QueueCommand(null); }, null, Timeout.Infinite, false);
                    RegisteredWaitHandle b = ThreadPool.RegisterWaitForSingleObject(wallpaper, delegate { office.QueueCommand(true); }, null, Timeout.Infinite, false);
                    RegisteredWaitHandle c = ThreadPool.RegisterWaitForSingleObject(off, delegate { office.QueueCommand(false); }, null, Timeout.Infinite, false);
                    try { Application.Run(office); }
                    finally { a.Unregister(null); b.Unregister(null); c.Unregister(null); }
                }
                return 0;
            }
            finally { single.ReleaseMutex(); }
        }
    }

    internal static Task StartService()
    {
        return Task.Run(delegate
        {
            string launcher = Path.Combine(Root, "打开工作室.pyw");
            if (!File.Exists(launcher)) throw new FileNotFoundException("请将 AI工作室.exe 放在包含“打开工作室.pyw”和 server.py 的工作室文件夹内。");
            string last = "";
            foreach (string python in new[] { "py.exe", "python.exe" })
            {
                var info = new ProcessStartInfo(python, (python == "py.exe" ? "-3 " : "") + "-B \"" + launcher + "\" --ensure-server");
                info.WorkingDirectory = Root;
                info.UseShellExecute = false;
                info.CreateNoWindow = true;
                info.RedirectStandardError = true;
                info.StandardErrorEncoding = Encoding.UTF8;
                info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                info.EnvironmentVariables["OFFICE_PORT"] = Port.ToString();
                Process process;
                try { process = Process.Start(info); }
                catch (Win32Exception ex) { last = ex.Message; continue; }
                using (process)
                {
                    Task<string> error = process.StandardError.ReadToEndAsync();
                    if (!process.WaitForExit(22000))
                    {
                        process.Kill();
                        throw new TimeoutException("等待本机办公室服务超时。请稍后重新打开。");
                    }
                    if (process.ExitCode == 0) return;
                    last = error.Result.Trim();
                    if (last.Length > 0 && !last.StartsWith("No suitable Python", StringComparison.OrdinalIgnoreCase)) break;
                }
            }
            throw new InvalidOperationException("本机工作室服务启动失败。" + (last == "" ? "请检查 Python 3 是否可用。" : "\r\n" + last));
        });
    }
}

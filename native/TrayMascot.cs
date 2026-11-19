using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;

internal sealed class TrayMascot : IDisposable
{
    [DllImport("user32.dll")] private static extern bool DestroyIcon(IntPtr handle);
    private readonly Timer timer = new Timer();
    private readonly Icon[] frames;
    internal bool Working { get; set; }
    private int frame;
    internal int Frame { get { return frame; } }
    internal event Action FrameChanged;

    internal TrayMascot(NotifyIcon tray)
    {
        using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("pet-idle.png"))
        using (var gif = Image.FromStream(stream))
        {
            var size = SystemInformation.SmallIconSize;
            frames = new Icon[12];
            for (int i=0;i<frames.Length;i++) {
                using (var bitmap = new Bitmap(size.Width, size.Height, PixelFormat.Format32bppArgb))
                {
                    using (var g = Graphics.FromImage(bitmap))
                    {
                        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                        float lift=(float)(1-Math.Cos(i*Math.PI/6))*.5f;
                        g.DrawImage(gif,0,lift,size.Width,size.Height-lift);
                    }
                    var handle = bitmap.GetHicon();
                    try { frames[i] = (Icon)Icon.FromHandle(handle).Clone(); }
                    finally { DestroyIcon(handle); }
                }
            }
        }
        tray.Icon = frames[0];
        timer.Interval = 160;
        timer.Tick += delegate {
            frame = (frame + 1) % frames.Length;
            tray.Icon = frames[frame];
            timer.Interval = Working ? 95 : 160;
            if (FrameChanged != null) FrameChanged();
        };
        timer.Start();
    }

    public void Dispose()
    {
        timer.Dispose();
        foreach (var icon in frames) icon.Dispose();
    }
}

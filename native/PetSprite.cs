using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows.Forms;

// A per-pixel alpha window keeps the soft silhouette intact on any wallpaper.
internal sealed class PetSprite : Form
{
    private readonly Image[] poses = new Image[2];
    private readonly IntPtr[,] frames = new IntPtr[2, 12];
    private IntPtr memoryDC;
    private int cachedSize;
    private int lastIndex = -1;
    private Point lastPosition;

    internal PetSprite()
    {
        Text = "工作室桌宠形象";
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        AutoScaleMode = AutoScaleMode.None;
        TopMost = true;
        ShowInTaskbar = false;
        Cursor = Cursors.Hand;
        var assembly = Assembly.GetExecutingAssembly();
        for (int i=0; i<poses.Length; i++) {
            using (var stream = assembly.GetManifestResourceStream(i==0 ? "pet-idle.png" : "pet-coding.png"))
            using (var original = Image.FromStream(stream)) poses[i] = new Bitmap(original);
        }
        memoryDC = CreateCompatibleDC(IntPtr.Zero);
        if (memoryDC == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
    }
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams {
        get { var p=base.CreateParams; p.ExStyle |= 0x80000 | 0x80 | 0x08000000; return p; }
    }

    internal void PaintFrame(Rectangle bounds, int frame, bool coding)
    {
        int size=bounds.Width, pose=coding ? 1 : 0, index=pose*12+frame;
        if (cachedSize != size) { ClearFrames(); cachedSize=size; }
        if (Visible && index==lastIndex && bounds.Location==lastPosition) return;
        if (frames[pose,frame]==IntPtr.Zero) {
            using(var bitmap=new Bitmap(size,size,PixelFormat.Format32bppPArgb))
            using(var g=Graphics.FromImage(bitmap)) {
                double angle=2*Math.PI*frame/12;
                float bob=(float)(1-Math.Cos(angle));
                g.ScaleTransform(size/144f,size/144f);
                g.TranslateTransform(72,136);
                g.RotateTransform((float)Math.Sin(angle)*(coding?1.8f:1.1f));
                g.InterpolationMode=InterpolationMode.HighQualityBicubic;
                g.PixelOffsetMode=PixelOffsetMode.HighQuality;
                float height=(coding?132:134)-bob*(coding?2.1f:1.2f);
                g.DrawImage(poses[pose],new RectangleF(-67,-height-bob,134,height));
                frames[pose,frame]=bitmap.GetHbitmap(Color.FromArgb(0));
            }
        }
        var old=SelectObject(memoryDC,frames[pose,frame]);
        var target=bounds.Location; var extent=bounds.Size; var source=Point.Empty;
        var blend=new Blend { Alpha=255, Format=1 };
        try {
            if (!UpdateLayeredWindow(Handle,IntPtr.Zero,ref target,ref extent,memoryDC,ref source,0,ref blend,2))
                throw new System.ComponentModel.Win32Exception();
            lastIndex=index;lastPosition=target;
        } finally { SelectObject(memoryDC,old); }
    }
    private void ClearFrames() {
        for(int p=0;p<2;p++)for(int f=0;f<12;f++) {
            if(frames[p,f]!=IntPtr.Zero){DeleteObject(frames[p,f]);frames[p,f]=IntPtr.Zero;}
        }
        lastIndex=-1;
    }
    protected override void Dispose(bool disposing) {
        if(disposing && memoryDC!=IntPtr.Zero){
            ClearFrames();DeleteDC(memoryDC);memoryDC=IntPtr.Zero;
            foreach(var pose in poses)pose.Dispose();
        }
        base.Dispose(disposing);
    }
    [StructLayout(LayoutKind.Sequential, Pack=1)] private struct Blend {public byte Operation,Flags,Alpha,Format;}
    [DllImport("gdi32.dll")] private static extern IntPtr CreateCompatibleDC(IntPtr dc);
    [DllImport("gdi32.dll")] private static extern bool DeleteDC(IntPtr dc);
    [DllImport("gdi32.dll")] private static extern IntPtr SelectObject(IntPtr dc,IntPtr obj);
    [DllImport("gdi32.dll")] private static extern bool DeleteObject(IntPtr obj);
    [DllImport("user32.dll",SetLastError=true)] private static extern bool UpdateLayeredWindow(IntPtr window,IntPtr dest,ref Point at,ref Size size,IntPtr src,ref Point origin,int key,ref Blend blend,int flags);
}

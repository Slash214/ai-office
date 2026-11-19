using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Net;
using System.Windows.Forms;

internal sealed class DesktopPet : Form
{
    private readonly TrayMascot animation;
    private readonly string settings;
    private Point grabbed, origin;
    private bool sliding;
    private string headline = "正在连接工作室";
    private readonly Button review = new PetButton(PetButton.Mark.Inbox);
    private readonly TextBox brief = new TextBox();
    private readonly Button send = new PetButton(PetButton.Mark.Send);
    private readonly Button compose = new PetButton(PetButton.Mark.Pencil);
    private readonly PetSprite sprite = new PetSprite();
    private readonly Label commandBadge = new Label();
    private string commandTask, commandPhase;
    private DateTime showReviewUntil;
    private readonly Panel tools = new Panel(), entry = new Panel();
    private readonly ToolTip help = new ToolTip();
    private readonly Timer poll = new Timer { Interval = 3000 };
    private bool polling, coding, sending, hovering, editing;
    private string reviewId, retryBrief, requestId;
    private DateTime feedbackUntil;
    internal bool EnabledAtStart { get; private set; }

    internal DesktopPet(TrayMascot animation, Action openOffice, Action<string> openTask, ContextMenuStrip menu)
    {
        this.animation = animation;
        settings = Path.Combine(Program.Root, ".office-data", "desktop-pet-" + Program.Port + ".txt");
        Text = "呵呵工作室桌宠";
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        AutoScaleDimensions = new SizeF(96,96);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(296, 226);
        BackColor = TransparencyKey = Color.Magenta;
        DoubleBuffered = true;
        TopMost = true;
        ShowInTaskbar = false;
        ContextMenuStrip = menu;
        Cursor = Cursors.Hand;
        sprite.ContextMenuStrip=menu;
        sprite.MouseEnter += delegate { RevealTools(); };
        sprite.MouseDown += delegate(object sender,MouseEventArgs e){ PetDown(sprite,e); };
        sprite.MouseMove += delegate(object sender,MouseEventArgs e){ PetMove(sprite,e); };
        sprite.MouseUp += delegate(object sender,MouseEventArgs e){ PetUp(sprite,e); };
        sprite.MouseDoubleClick += delegate(object sender,MouseEventArgs e){ if(e.Button==MouseButtons.Left)openOffice(); };
        LocationChanged += delegate { if(Visible && sprite.Visible) DrawSprite(); };
        commandBadge.SetBounds(31,12,234,29);
        commandBadge.TextAlign=ContentAlignment.MiddleCenter;
        commandBadge.AutoEllipsis=true;
        commandBadge.BackColor=Color.FromArgb(34,48,78);
        commandBadge.ForeColor=Color.White;
        commandBadge.Visible=false;
        Controls.Add(commandBadge);Round(commandBadge);
        commandBadge.SizeChanged+=delegate {Round(commandBadge);};
        commandBadge.Click+=delegate {if(commandTask!=null)openTask(commandTask);};
        tools.SetBounds(104,184,88,36);
        entry.SetBounds(1,183,294,39);
        foreach (Panel bar in new[] { tools, entry }) {
            bar.BackColor=Color.White; bar.Visible=false; Controls.Add(bar); Round(bar); bar.SizeChanged += delegate {Round(bar);};
        }
        compose.SetBounds(5,2,35,32);
        compose.AccessibleName="输入任务";compose.ForeColor=Color.FromArgb(42,51,66);
        compose.Click += delegate { BeginCompose(); };
        tools.Controls.Add(compose);
        tools.Controls.Add(new Panel {Bounds=new Rectangle(44,10,1,16),BackColor=Color.Gainsboro});
        review.SetBounds(49,2,34,32);
        review.AccessibleName="查看任务";
        review.Click += delegate { if (reviewId != null) openTask(reviewId); else openOffice(); };
        tools.Controls.Add(review);
        brief.SetBounds(16,10,223,21);
        brief.BackColor = Color.White; brief.ForeColor = Color.FromArgb(33,39,50);
        brief.MaxLength = 4000;
        brief.AccessibleName = "分配给团队的任务";
        brief.Cursor = Cursors.IBeam;
        brief.BorderStyle = BorderStyle.None;
        brief.HandleCreated += delegate { SendMessage(brief.Handle, 0x1501, new IntPtr(1), "给团队写任务…"); };
        entry.Controls.Add(brief);
        send.SetBounds(255,4,31,31);
        send.AccessibleName="派发";
        send.Enabled=false;
        brief.TextChanged += delegate {send.Enabled=!sending && brief.Text.Trim().Length>0;};
        send.Click += async delegate { await Submit(); };
        entry.Controls.Add(send);
        help.SetToolTip(brief, "输入任务，按 Enter 或点派发");
        help.SetToolTip(compose,"输入任务");help.SetToolTip(send,"派发");
        KeyPreview=true;
        KeyDown += delegate(object sender, KeyEventArgs e) {
            if(e.KeyCode==Keys.Escape && editing){e.SuppressKeyPress=true; EndCompose();}
        };
        Deactivate += delegate { if(editing && !sending) EndCompose(); };
        MouseEnter += delegate { RevealTools(); };
        poll.Tick += delegate { RefreshStatus(); };
        VisibleChanged += delegate {
            if (Visible) { DrawSprite(); sprite.Show(this); poll.Start(); RefreshStatus(); }
            else { sprite.Hide(); poll.Stop(); hovering=false; EndCompose(); }
        };
        Rectangle area = Screen.PrimaryScreen.WorkingArea;
        Location = new Point(area.Right - Width - 34, area.Bottom - Height - 26);
        EnabledAtStart = true;
        try {
            if (File.Exists(settings)) {
                var values = File.ReadAllLines(settings);
                int x, y;
                if (values.Length == 3 && int.TryParse(values[1], out x) && int.TryParse(values[2], out y)) {
                    Location = OnScreen(new Point(x, y));
                    EnabledAtStart = values[0] != "hidden";
                }
            }
        } catch (IOException) { } catch (UnauthorizedAccessException) { }
        animation.FrameChanged += RefreshFrame;
        MouseDoubleClick += delegate(object sender, MouseEventArgs e) {
            if (e.Button == MouseButtons.Left) openOffice();
        };
    }

    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams {
        get {
            var p = base.CreateParams;
            p.ExStyle |= 0x80; // Tool window; clicking the task field must allow keyboard focus.
            return p;
        }
    }

    private Point OnScreen(Point p) {
        var area = Screen.FromRectangle(new Rectangle(p, Size)).WorkingArea;
        return new Point(Math.Max(area.Left, Math.Min(p.X, area.Right - Width)),
                         Math.Max(area.Top, Math.Min(p.Y, area.Bottom - Height)));
    }

    internal void Toggle() {
        if (Visible) Hide(); else { Location = OnScreen(Location); Show(); }
        Save();
    }

    private void Save() {
        try {
            Directory.CreateDirectory(Path.GetDirectoryName(settings));
            File.WriteAllLines(settings, new[] { Visible ? "visible" : "hidden", Left.ToString(), Top.ToString() });
        } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    [System.Runtime.InteropServices.DllImport("user32.dll", CharSet=System.Runtime.InteropServices.CharSet.Unicode)]
    private static extern IntPtr SendMessage(IntPtr hwnd, int message, IntPtr first, string text);

    private void Feedback(string message) {
        feedbackUntil = DateTime.UtcNow.AddSeconds(3);
        headline = message;
        help.SetToolTip(sprite,message);
        if(Visible)help.Show(message,this,88,156,2600);
    }

    private async System.Threading.Tasks.Task Submit() {
        var text = brief.Text.Trim();
        if (sending || text.Length == 0) { brief.Focus(); return; }
        if (retryBrief != text) { requestId = Guid.NewGuid().ToString("D"); retryBrief = text; }
        sending = true; send.Enabled = false; brief.ReadOnly = true;
        try {
            await PetApi.Dispatch(text, requestId);
            if (IsDisposed) return;
            brief.Clear(); retryBrief = requestId = null;
            Feedback("已派发，团队已收到");
            EndCompose();
            RefreshStatus();
        } catch (WebException) { if (!IsDisposed) Feedback("派单未确认，点派发可重试"); }
          catch (IOException) { if (!IsDisposed) Feedback("派单未确认，点派发可重试"); }
        finally { if (!IsDisposed) { send.Enabled = brief.Text.Trim().Length>0; brief.ReadOnly = false; } sending = false; }
    }

    private async void RefreshStatus() {
        if (polling || IsDisposed) return;
        polling = true;
        try {
            PetApi.Status state = null;
            try { state = await PetApi.Read(); }
            catch (WebException) { } catch (IOException) { } catch (ArgumentException) { } catch (InvalidOperationException) { }
            if (IsDisposed) return;
            if (DateTime.UtcNow >= feedbackUntil) headline = state == null ? "工作室离线 · 重连中" : state.headline;
            coding = state != null && state.coding;
            animation.Working=coding;
            var command=state==null?null:state.command;
            Guid taskId;
            var idText=command!=null && Guid.TryParseExact(command.id,"D",out taskId)?taskId.ToString("D"):null;
            if(command!=null && command.phase=="review" && commandTask==idText && commandPhase!="review")
                showReviewUntil=DateTime.UtcNow.AddSeconds(12);
            commandTask=idText;commandPhase=command==null?null:command.phase;
            commandBadge.Text=command==null?"":command.text;
            commandBadge.BackColor=commandPhase=="blocked"?Color.FromArgb(108,49,57):Color.FromArgb(34,48,78);
            commandBadge.Visible=commandTask!=null && !string.IsNullOrEmpty(commandBadge.Text)
                && (commandPhase!="review" || DateTime.UtcNow<showReviewUntil);
            Guid id;
            reviewId = state != null && state.reviews > 0 && Guid.TryParseExact(state.reviewId,"D",out id) ? id.ToString("D") : null;
            var hint=reviewId==null?headline:headline+" · "+state.reviews+" 项待验收";
            help.SetToolTip(sprite,hint);help.SetToolTip(review,reviewId==null?"查看工作室 · "+hint:hint);
            review.ForeColor=reviewId==null?Color.FromArgb(50,55,69):Color.FromArgb(76,77,175);
            review.AccessibleName=reviewId==null?"查看工作室":state.reviews+" 项待验收";
            if(reviewId!=null && state.reviews!=previousReviews && hovering && !editing)
                help.Show(hint,this,85,153,2500);
            previousReviews=state==null?0:state.reviews;
            if(Visible)DrawSprite();
        } finally { polling = false; }
    }

    private int previousReviews;
    private static void Round(Control control) {
        using(var path=new GraphicsPath()){
            int h=control.Height,w=control.Width;
            path.AddArc(0,0,h,h,90,180);path.AddArc(w-h,0,h,h,270,180);path.CloseFigure();
            var old=control.Region; control.Region=new Region(path); if(old!=null)old.Dispose();
        }
    }
    private void RevealTools() {
        if(!editing && !hovering){hovering=true; UpdateChrome();}
    }
    private void BeginCompose() {
        editing=true;UpdateChrome();Activate();brief.Focus();
    }
    private void EndCompose() {
        editing=false;ActiveControl=null;UpdateChrome();
    }
    private void UpdateChrome() {
        entry.Visible=editing;tools.Visible=hovering && !editing;
        AcceptButton=editing?send:null;
    }
    private void RefreshFrame() {
        if (!Visible)return;
        var mouse=PointToClient(Cursor.Position);
        float zoom=ClientSize.Width/296f;
        if(hovering && !editing && !Capture && !sprite.Capture && !new RectangleF(76,40,145,185).Contains(mouse.X/zoom,mouse.Y/zoom)){
            hovering=false;UpdateChrome();
        }
        DrawSprite();
    }
    private void DrawSprite() {
        float zoom=ClientSize.Width/296f;
        int size=(int)Math.Round(136*zoom);
        var p=PointToScreen(new Point((ClientSize.Width-size)/2,(int)Math.Round(46*zoom)));
        sprite.PaintFrame(new Rectangle(p,new Size(size,size)),animation.Frame,coding);
    }
    protected override void OnMouseDown(MouseEventArgs e) { base.OnMouseDown(e);PetDown(this,e); }
    protected override void OnMouseMove(MouseEventArgs e) { base.OnMouseMove(e);PetMove(this,e); }
    protected override void OnMouseUp(MouseEventArgs e) { base.OnMouseUp(e);PetUp(this,e); }
    private void PetDown(Control host,MouseEventArgs e){
        if (e.Button != MouseButtons.Left) return;
        grabbed = Cursor.Position;
        origin = Location;
        sliding = false;
        host.Capture = true;
    }

    private void PetMove(Control host,MouseEventArgs e) {
        if (!host.Capture || (MouseButtons & MouseButtons.Left) == 0) return;
        Point pointer = Cursor.Position;
        int dx = pointer.X - grabbed.X, dy = pointer.Y - grabbed.Y;
        if (!sliding && Math.Abs(dx) < SystemInformation.DragSize.Width / 2 &&
            Math.Abs(dy) < SystemInformation.DragSize.Height / 2) return;
        sliding = true;
        Location = OnScreen(new Point(origin.X + dx, origin.Y + dy));
    }

    private void PetUp(Control host,MouseEventArgs e) {
        if (e.Button != MouseButtons.Left) return;
        host.Capture = false;
        if (sliding) Save();
        sliding = false;
    }

    protected override void Dispose(bool disposing) {
        if (disposing) { animation.FrameChanged -= RefreshFrame; poll.Dispose(); help.Dispose(); sprite.Dispose(); }
        base.Dispose(disposing);
    }
}

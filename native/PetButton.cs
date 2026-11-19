using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

internal sealed class PetButton : Button
{
    internal enum Mark { Pencil, Inbox, Send }
    private readonly Mark mark;
    private bool over,pressed;
    internal PetButton(Mark mark){
        this.mark=mark;
        SetStyle(ControlStyles.UserPaint|ControlStyles.AllPaintingInWmPaint|ControlStyles.OptimizedDoubleBuffer,true);
        FlatStyle=FlatStyle.Flat;
        FlatAppearance.BorderSize=0;
        Cursor=Cursors.Hand;
        BackColor=Color.White;
    }
    protected override void OnMouseEnter(System.EventArgs e){base.OnMouseEnter(e);over=true;Invalidate();}
    protected override void OnMouseLeave(System.EventArgs e){base.OnMouseLeave(e);over=pressed=false;Invalidate();}
    protected override void OnMouseDown(MouseEventArgs e){base.OnMouseDown(e);pressed=true;Invalidate();}
    protected override void OnMouseUp(MouseEventArgs e){base.OnMouseUp(e);pressed=false;Invalidate();}
    protected override void OnPaint(PaintEventArgs e){
        var g=e.Graphics;g.Clear(Color.White);g.SmoothingMode=SmoothingMode.AntiAlias;
        g.TranslateTransform(Width*.5f,Height*.5f);float scale=System.Math.Min(Width,Height)/32f;
        g.ScaleTransform(scale,scale);
        bool submit=mark==Mark.Send;
        var color=submit?(Enabled?Color.FromArgb(48,89,192):Color.FromArgb(182,199,231)):ForeColor;
        if(submit||over||pressed||Focused&&ShowFocusCues)
            using(var fill=new SolidBrush(submit?color:pressed?Color.FromArgb(221,231,249):Color.FromArgb(238,243,252)))
                g.FillEllipse(fill,-14,-14,28,28);
        using(var pen=new Pen(submit?Color.White:color,1.65f)){
            pen.StartCap=pen.EndCap=LineCap.Round;pen.LineJoin=LineJoin.Round;
            if(mark==Mark.Pencil){
                g.DrawLines(pen,new[]{new PointF(-6,2),new PointF(3.5f,-7.5f),new PointF(7,-4),new PointF(-2.5f,5.5f),new PointF(-7,7),new PointF(-6,2)});
                g.DrawLine(pen,2,-6,5.5f,-2.5f);
            }else if(mark==Mark.Inbox){
                g.DrawLines(pen,new[]{new Point(-7,2),new Point(-4,-5),new Point(4,-5),new Point(7,2),new Point(7,6),new Point(-7,6),new Point(-7,2),new Point(-3,2),new Point(-1,4),new Point(1,4),new Point(3,2),new Point(7,2)});
            }else{g.DrawLine(pen,0,6,0,-6);g.DrawLines(pen,new[]{new Point(-5,-1),new Point(0,-6),new Point(5,-1)});}
            if(Focused&&ShowFocusCues)g.DrawEllipse(pen,-14,-14,28,28);
        }
    }
}

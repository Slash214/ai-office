"""Deliver UTF-8 text to the signed-in user's Desktop, never replacing an existing file."""
import ctypes
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile


def requested(brief):
    if re.search(r"(不要|不用|无需|别|禁止|不必).{0,15}(桌面|txt)|(?:don't|do not|never).{0,35}desktop", brief, re.I):
        return False
    return bool(re.search(r"桌面|\bdesktop\b", brief, re.I)
                and re.search(r"txt|文本文件|纯文本", brief, re.I)
                and re.search(r"生成|创建|建个|写|放|保存|交付|导出|输出|给|create|save|write|export", brief, re.I))


def directory():
    if os.name == "nt":
        path = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, path) != 0 or not path.value:
            raise OSError("无法读取当前 Windows 用户的桌面路径")
        return Path(path.value)
    return Path.home() / "Desktop"


def requested_html(brief):
    """Recognize an explicit request for a new standalone desktop page."""
    return (bool(re.search(r"桌面|\bdesktop\b", brief, re.I))
            and bool(re.search(r"\bhtml?\b|html页面|h5页面|H5\s*(?:展示|网页)|\.html", brief, re.I))
            and bool(re.search(r"创建|生成|制作|写一个|新建|保存|导出|create|generate|save", brief, re.I))
            and not re.search(r"(?:不要|不用|无需|禁止|别).{0,16}(?:桌面|保存|生成|写入)|do not|don't", brief, re.I))


def html_document(result):
    match = re.search(r"(<!doctype\s+html\s*>\s*<html\b[^>]*>.*?</html\s*>)", result, re.I | re.S)
    if not match or not re.search(r"<body\b", match[1], re.I):
        raise ValueError("执行成员未交付完整的 HTML 页面，请重试执行步骤。")
    return match[1].encode("utf-8")


def split_result(result, fallback):
    text = result.strip()
    header = re.match(r"(?:建议)?文件名\s*[:：]\s*([^\r\n]+?\.txt)[ `”」]*\r?\n+",text,re.I)
    if header:
        return header[1].strip(' `“「'), text[header.end():].lstrip()
    return fallback, text


def write(name, data, desktop=None, *, suffix=".txt"):
    if suffix not in (".txt", ".html"):
        raise ValueError("不支持的桌面文件格式")
    if not data.decode("utf-8-sig").strip() or len(data)>2*1024*1024:
        raise ValueError("TXT 内容为空或超出大小限制")
    folder = directory() if desktop is None else desktop
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", re.sub(re.escape(suffix)+"$", "", name, flags=re.I))[:70].strip(" .")
    if not stem or PureWindowsPath(stem+suffix).is_reserved():
        stem = "工作室交付"
    fd, temp = tempfile.mkstemp(prefix=".office-txt-",dir=folder)
    try:
        with os.fdopen(fd,"wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        for i in range(1,101):
            dest = folder / ((stem if i==1 else f"{stem} ({i})")+suffix)
            try:
                if os.name=="nt":
                    os.rename(temp,dest)
                else:
                    os.link(temp,dest)
            except FileExistsError:
                info=dest.lstat()
                if (not stat.S_ISREG(info.st_mode) or getattr(info,"st_file_attributes",0)&0x400
                        or info.st_size!=len(data) or dest.read_bytes()!=data):
                    continue
            if dest.read_bytes()!=data:
                raise OSError("桌面文件回读校验失败")
            return {"state":"saved", "filename":dest.name, "bytes":len(data)}
        raise OSError("同名文件过多")
    finally:
        Path(temp).unlink(missing_ok=True)

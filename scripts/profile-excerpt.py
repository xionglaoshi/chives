"""Extract a bounded local preview. Nothing is persisted or transmitted."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

LIMIT = 12000


def external(name, args):
    executable = shutil.which(name) or next((str(p) for root in ['/opt/homebrew/bin', '/usr/local/bin']
                                             if (p := Path(root, name)).is_file()), None)
    if not executable:
        raise ValueError('本机缺少 ' + name)
    with tempfile.TemporaryFile() as dest:
        subprocess.run([executable, *args], stdout=dest, stderr=subprocess.DEVNULL, check=True, timeout=18)
        dest.seek(0)
        return dest.read(100000).decode('utf-8', 'ignore')


def extract(kind, raw):
    if kind in {'csv', 'tsv', 'txt', 'md'}:
        for encoding in (['utf-16'] if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ['utf-8-sig', 'gb18030']):
            try:
                text = raw.decode(encoding)
                if '\x00' not in text:
                    return text
            except UnicodeError:
                pass
        raise ValueError('无法识别文本编码')
    if kind in {'xlsx', 'docx'}:
        with ZipFile(io.BytesIO(raw)) as archive:
            if sum(e.file_size for e in archive.infolist()) > 40_000_000:
                raise ValueError('解压后的文档过大')
            if kind == 'docx':
                root = ET.fromstring(archive.read('word/document.xml'))
                ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                return '\n'.join(''.join(t.text or '' for t in p.iter(ns+'t')) for p in root.iter(ns+'p'))
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            lines, size = [], 0
            for sheet in workbook:
                lines.append(sheet.title)
                for row in sheet.values:
                    line = '\t'.join('' if v is None else str(v) for v in row).strip()
                    if line:
                        lines.append(line)
                        size += len(line)+1
                    if size > LIMIT:
                        return '\n'.join(lines)
            return '\n'.join(lines)
        finally:
            workbook.close()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, 'input.'+kind)
        path.write_bytes(raw)
        if kind == 'pdf':
            return external('pdftotext', ['-layout', str(path), '-'])
        if kind in {'png','jpg','jpeg'}:
            from PIL import Image
            with Image.open(path) as img:
                if img.width*img.height > 30_000_000:
                    raise ValueError('图片分辨率过大')
            return external('tesseract', [str(path), 'stdout', '-l', 'chi_sim+eng'])
    raise ValueError('不支持此格式')


if __name__ == '__main__':
    try:
        text = extract(sys.argv[1], sys.stdin.buffer.read(4*1024*1024+1)).strip()
        if not text:
            raise ValueError('没有提取到可读正文，扫描版 PDF 请将相关页导出为图片')
        print(json.dumps({'text': text[:LIMIT], 'truncated': len(text)>LIMIT}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, ValueError) else '资料无法读取，请检查文件格式或重新导出'}))

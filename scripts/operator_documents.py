"""Document and SQLite access for the operator. Administrative files have no write mount."""
import hashlib
import os
import tempfile
from pathlib import Path


def document_roots(data):
    home = Path.home()
    roots = {"workspace": data / "bots/operator/workspace", "user-wiki": data / "user/wiki",
             "preferences": data / "user/preferences"}
    for label in ("Documents", "Downloads", "Desktop", "WPS"):
        folder = home / label
        if folder.is_dir() and not folder.is_symlink():
            roots[label] = folder
    for i, entry in enumerate(os.environ.get("CHIVES_OPERATOR_DOCUMENT_DIRS", "").split(os.pathsep)):
        if entry and Path(entry).is_absolute() and Path(entry).is_dir():
            roots[f"documents-{i+1}"] = Path(entry).resolve()
    return roots


def doc_path(data, mount, relative):
    roots = document_roots(data)
    part = Path(relative)
    if mount not in roots or part.is_absolute() or any(x.startswith(".") for x in part.parts):
        raise ValueError("请选择已登记的文档目录和相对路径")
    base = roots[mount]
    path = base / part
    if path.resolve() != path or not path.is_relative_to(base):
        raise ValueError("路径不能跨目录或穿过链接")
    if mount not in ("workspace","user-wiki","preferences") and any(
            path.is_relative_to(protected) for protected in (data, Path(__file__).resolve().parents[1])):
        raise ValueError("程序及人事配置不属于文档目录")
    return path


def read_document(data, mount, path, offset):
    if not mount:
        return {"roots":{k:str(v) for k,v in document_roots(data).items()}}
    file = doc_path(data,mount,path)
    if file.is_dir():
        return {"entries":sorted(p.name + ("/" if p.is_dir() else "") for p in file.iterdir()
                                 if not p.name.startswith(".") and not p.is_symlink())[:500]}
    if not file.is_file() or file.stat().st_size > 8_000_000:
        raise ValueError("请选择小于 8 MB 的文本文档")
    raw = file.read_bytes()
    txt = raw.decode("utf-8")
    start = max(0,offset)
    return {"text":txt[start:start+12000],"length":len(txt),"sha256":hashlib.sha256(raw).hexdigest()}


def write_document(data, mount, path, text, expected):
    file = doc_path(data,mount,path)
    extensions = {".md",".txt",".csv",".tsv",".json"}
    if file.suffix.lower() not in extensions or (mount in ("user-wiki","preferences") and file.suffix.lower() != ".md"):
        raise ValueError("写入支持 Markdown、文本、CSV、TSV 和 JSON，用户知识页使用 Markdown")
    raw = text.encode("utf-8")
    if len(raw)>8_000_000:
        raise ValueError("文档超过 8 MB")
    file.parent.mkdir(exist_ok=True,parents=True)
    if file.exists() and (not file.is_file() or file.stat().st_size>8_000_000 or
                           hashlib.sha256(file.read_bytes()).hexdigest()!=expected):
        raise ValueError("文件已经变化，请重读后再保存")
    if not file.exists() and expected:
        raise ValueError("原文件已经移走")
    fd, temp = tempfile.mkstemp(dir=file.parent)
    try:
        with os.fdopen(fd,"wb") as fp:
            fp.write(raw)
        if expected:
            os.replace(temp,file)
        else:
            os.link(temp,file)
    finally:
        Path(temp).unlink(missing_ok=True)
    return {"path":str(file),"sha256":hashlib.sha256(raw).hexdigest()}


def databases(data, runtime):
    result = {}
    ignored = {"node_modules","npm-cache","dependencies","ms-playwright","tmp","venv","__pycache__","secrets","credentials"}
    for prefix,root in (("data",data),("runtime",runtime)):
        if not root.is_dir():
            continue
        for folder,dirs,files in os.walk(root,followlinks=False):
            parent = Path(folder)
            dirs[:] = [d for d in dirs if d not in ignored and not d.startswith(".") and not (parent/d).is_symlink()]
            for name in files:
                path = parent/name
                if path.suffix.lower() in {".sqlite",".sqlite3",".db"} and path.resolve()==path and path.is_file():
                    result[prefix+"/"+path.relative_to(root).as_posix()] = path
    return result

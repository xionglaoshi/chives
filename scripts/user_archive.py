"""Maintain the local Chives user archive. The owner supplies reviewed evidence on stdin."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
import fcntl
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = ROOT / "presets/user-attributes"
TOPICS = ("关注的证券", "研究委托", "投资观点", "投资复盘")
REVIEW_DB = "reviews/attribute-proposals.sqlite"
REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
  source_id TEXT PRIMARY KEY, source_path TEXT NOT NULL, sha256 TEXT NOT NULL,
  effective_at TEXT NOT NULL, applied_at TEXT NOT NULL, origin TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proposals (
  id TEXT PRIMARY KEY, attribute TEXT NOT NULL, expected_value TEXT NOT NULL,
  suggested_value TEXT NOT NULL, base_revision INTEGER NOT NULL, bot TEXT NOT NULL,
  source_task TEXT NOT NULL, source_message TEXT NOT NULL, quote TEXT NOT NULL,
  reason TEXT NOT NULL, alternatives TEXT NOT NULL, created_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', reviewer TEXT, review_reason TEXT,
  UNIQUE(attribute,source_message,suggested_value,base_revision));
CREATE TABLE IF NOT EXISTS decisions (
  seq INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES batches(source_id),
  attribute TEXT NOT NULL, definition_version INTEGER NOT NULL, old_value TEXT NOT NULL,
  new_value TEXT NOT NULL, decision TEXT NOT NULL, evidence TEXT NOT NULL, reason TEXT NOT NULL,
  UNIQUE(source_id, attribute));
"""
TRADES_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
  id TEXT PRIMARY KEY, account TEXT NOT NULL, mode TEXT NOT NULL CHECK(mode IN ('live','simulation')),
  market TEXT NOT NULL, symbol TEXT NOT NULL, executed_at TEXT NOT NULL, side TEXT NOT NULL,
  quantity TEXT NOT NULL, price TEXT NOT NULL, currency TEXT NOT NULL, fees TEXT,
  source TEXT NOT NULL, source_trade_id TEXT NOT NULL, reverses TEXT REFERENCES trades(id),
  UNIQUE(account,mode,source,source_trade_id));
"""
INDEX_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS sections USING fts5(path UNINDEXED, title, body, tokenize='trigram');
"""
MAP = """## 资料地图
- 属性值见 attributes/values.json，中文赋值对照和待确认选项见 reviews/。
- 长期要求见 preferences/instructions.md，持仓口径和日期见 portfolio/holdings.json，成交见 portfolio/trades.sqlite。
- 过去的问题、委托、观点及复盘按主题查 wiki/，最近的断点见 recent-memory.md。
"""


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def publish(path, content):
    if not isinstance(content, bytes):
        content = content.encode()
    if path.exists() and path.read_bytes() == content:
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".writing-", delete=False) as tmp:
        try:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, path)
        finally:
            Path(tmp.name).unlink(missing_ok=True)


def definitions():
    fields = {}
    for path in sorted(DEFINITIONS.glob("*.json")):
        field = json.loads(path.read_text())
        key = field["key"]
        if key in fields or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ValueError(f"属性键重复或无效：{key}")
        fields[key] = field
    if not fields:
        raise ValueError("属性字典为空")
    return fields


def valid_value(field, value):
    if value is None:
        return True
    rule = field["domain"]
    kind, args = rule["kind"], rule["arguments"]
    number = type(value) in (int, float) and math.isfinite(value)
    short = isinstance(value, str) and 0 < len(value.strip()) <= 160
    def named(v):
        return v in args or ("其他：" in args and v.startswith("其他：") and len(v) > 3)
    if kind == "integer":
        return type(value) is int and args[0] <= value <= args[1]
    if kind == "boolean":
        return type(value) is bool
    if kind == "year":
        return value in args or type(value) is int and 1000 <= value <= date.today().year
    if kind == "months":
        return value in args or type(value) is int and value >= 0
    if kind == "percent":
        return value in args or number and 0 <= value <= 100
    if kind in ("enum", "named"):
        return short and named(value)
    if kind == "text":
        return short
    if kind in ("ordered", "list"):
        if not isinstance(value,list) or len(value)>40 or not all(isinstance(v,str) and 0<len(v.strip())<=120 for v in value):
            return False
        if len(set(value))!=len(value):
            return False
        return kind=="list" or (bool(value) and all(named(v) for v in value)
              and (len(value)==1 or not {"未形成固定方法","视机会而定"}.intersection(value)))
    if kind == "days_median":
        return number and value >= 1 and value * 2 == int(value * 2)
    if kind == "days_monthly":
        return number and 0 <= value <= 31 and round(value,1) == value
    raise ValueError(f"未知值域：{kind}")


@contextmanager
def locked(data):
    state = data / "user-archive-state"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def initialize(user):
    for name in ("attributes", "preferences", "portfolio", "sources", "reviews", "index", *("wiki/"+t for t in TOPICS)):
        (user/name).mkdir(parents=True, exist_ok=True, mode=0o700)
    for path, schema in ((REVIEW_DB, REVIEW_SCHEMA), ("portfolio/trades.sqlite", TRADES_SCHEMA),
                         ("index/wiki-search.sqlite", INDEX_SCHEMA)):
        with closing(sqlite3.connect(user/path)) as db:
            db.executescript(schema)
    for path, content in {"preferences/instructions.md":"# 用户长期要求\n",
                          "recent-memory.md":"",
                          "portfolio/holdings.json":dump({"version":1,"accounts":[],"live_coverage":"unknown"})}.items():
        if not (user/path).exists():
            publish(user/path, content)


def snapshot(user, db, fields):
    values = dict.fromkeys(fields)
    pending = {}
    evidence = {}
    provisional = set()
    for key, value, decision, reason, source, refs, origin in db.execute(
        "SELECT d.attribute,d.new_value,d.decision,d.reason,b.source_path,d.evidence,b.origin "
        "FROM decisions d JOIN batches b USING(source_id) ORDER BY d.seq"):
        if key not in fields:
            raise ValueError(f"在用属性定义缺失：{key}")
        if decision == "applied":
            values[key] = json.loads(value)
            pending.pop(key,None)
            evidence[key] = (source, reason, refs)
            if origin == "provisional":
                provisional.add(key)
            else:
                provisional.discard(key)
        elif values[key] is None:
            pending[key] = reason
    publish(user/"attributes/values.json", dump(values))
    questions = ["# 待确认的用户属性", "", "可按编号直接回复。暂时不清楚的项目可保留未知。", ""]
    for key, val in values.items():
        if val is None:
            f = fields[key]
            questions.extend([f"## {f['id']} {f['label']}", pending.get(key,"暂无足够依据。"), "", f["scale"], ""])
    if provisional:
        questions.extend(["## 留待新版问卷替换", "",
                          "以下项目已按本人授权临时代填，当前无需补答。", ""])
        questions.extend("- "+f["id"]+" "+f["label"] for key,f in fields.items() if key in provisional)
    publish(user/"reviews/待确认属性.md","\n".join(questions))
    report = ["# 属性赋值对照", "", "本表由赋值记录生成。各项取值见 [values.json](../attributes/values.json)。标注「临时代填」的项目将在新版问卷作答后替换。",
              "未定项的原答线索和选项见[待确认属性](待确认属性.md)。", "",
              "| 编号 | 属性 | 当前值 | 采用依据 |", "|---|---|---|---|"]
    for key, field in fields.items():
        val=values[key]
        display=("未知" if val is None else "是" if val is True else "否" if val is False
                 else "、".join(val) or "已明确为空" if isinstance(val,list) else str(val))
        basis="待确认"
        if key in evidence:
            src, reason, refs=evidence[key]
            if key in provisional:
                display += "（临时代填）"
            basis=reason+" [原始记录 "+", ".join(json.loads(refs))+"](../"+src+")"
        report.append("| "+" | ".join(str(item).replace("|","&#124;").replace("\n"," ") for item in (field["id"],field["label"],display,basis))+" |")
    publish(user/"reviews/赋值对照.md","\n".join(report)+"\n")

    assessed = db.execute("SELECT 1 FROM batches WHERE origin='questionnaire' LIMIT 1").fetchone()
    summary = ["# 用户索引", "", "已完成旧版问卷，未确认的属性保留未知。" if assessed else "尚未登记已完成的评测。最终答复提醒本人完成评测，当前答复基于有限资料，仅供研究参考。",""]
    if provisional:
        ids = "、".join(f["id"] for key,f in fields.items() if key in provisional)
        summary.append("等新版问卷再核："+ids+" 是临时代填；个性化建议、仓位提醒和实绩统计均只使用有依据的值。这些项目当前无需追问。")
    for key in ("firsthand_industries","core_capital_horizon_months","primary_investment_goal","preferred_investment_vehicles","risk_capacity","max_single_position_pct"):
        val = values.get(key)
        if val is not None and key not in provisional:
            unit = {"core_capital_horizon_months":" 个月","max_single_position_pct":"%"}.get(key,"") if type(val) in (int,float) else ""
            display = "、".join(val) if isinstance(val,list) else ("C"+str(val) if key=="risk_capacity" else str(val))
            summary.append(f"- {fields[key]['label']}：{display[:100]}{unit}")
    instructions=(user/"preferences/instructions.md").read_text().splitlines()
    prefix="\n".join(summary)+"\n\n## 长期要求\n"
    for line in instructions:
        if line.startswith("- ") and len(prefix)+len(line)+len(MAP)+4<=1000:
            prefix+=line+"\n"
    publish(user/"user-index.md",prefix+"\n"+MAP)


def apply(user, db, fields, packet):
    # Only the local owner/importer invokes this writer. No Bot API calls it.
    ref=packet["source_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}",ref) or packet["origin"] not in ("questionnaire","owner","review","provisional","operator"):
        raise ValueError("来源无效")
    stamp=packet["effective_at"]
    if datetime.fromisoformat(stamp.replace("Z","+00:00")).tzinfo is None:
        raise ValueError("来源时间缺少时区")
    content=dump(packet)
    digest=sha256(content.encode()).hexdigest()
    previous=db.execute("SELECT sha256 FROM batches WHERE source_id=?",(ref,)).fetchone()
    if previous:
        if previous[0]!=digest:
            raise ValueError("来源编号已被另一版本使用")
        return
    rows=[]
    for key, item in packet["decisions"].items():
        if key not in fields or not valid_value(fields[key],item["value"]):
            raise ValueError(f"属性或取值无效：{key}")
        refs=item["refs"]
        if not refs or any(k not in packet["evidence"] for k in refs) or not item["reason"].strip():
            raise ValueError(f"缺少证据：{key}")
        prior = db.execute("SELECT d.new_value,b.origin FROM decisions d JOIN batches b USING(source_id) "
                           "WHERE d.attribute=? AND d.decision='applied' ORDER BY d.seq DESC LIMIT 1",(key,)).fetchone()
        old=json.loads(prior[0]) if prior else None
        if old!=item["old"] or type(old) is not type(item["old"]):
            raise ValueError(f"原值已变化：{key}")
        if packet["origin"]=="provisional" and (old is not None or item["value"] is None or item["decision"]!="applied"):
            raise ValueError("临时代填只适用于空缺项且必须给出字典内的值")
        if packet["origin"]=="questionnaire" and old is not None and prior[1]!="provisional":
            raise ValueError("重复评测须提交复核")
        decision=item["decision"]
        if decision not in ("applied","pending") or (decision=="pending" and item["value"] is not None):
            raise ValueError(f"无效决定：{key}")
        rows.append((ref,key,fields[key]["version"],dump(old).strip(),dump(item["value"]).strip(),decision,dump(refs).strip(),item["reason"]))
    proposal = packet.get("proposal_id")
    if packet["origin"]=="review" and not proposal:
        raise ValueError("独立审核写入需要有效的已审提案")
    if proposal:
        found = db.execute("SELECT attribute,status,base_revision,suggested_value FROM proposals WHERE id=?",(proposal,)).fetchone()
        if not found or len(rows)!=1 or found[0]!=rows[0][1] or found[1] not in ("pending","supported","needs_evidence"):
            raise ValueError("提案不存在、已处理或属性不符")
        revision = db.execute("SELECT COALESCE(MAX(seq),0) FROM decisions WHERE attribute=? AND decision='applied'",(found[0],)).fetchone()[0]
        if revision!=found[2] or dump(json.loads(rows[0][4]))!=dump(json.loads(found[3])) or rows[0][5]!="applied":
            raise ValueError("提案已过期或建议值与申请合并值不同")
    rel="sources/"+ref+".json"
    with db:
        if proposal:
            db.execute("UPDATE proposals SET status='merged' WHERE id=?",(proposal,))
        publish(user/rel,content)
        db.execute("INSERT INTO batches VALUES (?,?,?,?,?,?)",(ref,rel,digest,stamp,datetime.now(timezone.utc).isoformat(),packet["origin"]))
        db.executemany("INSERT INTO decisions(source_id,attribute,definition_version,old_value,new_value,decision,evidence,reason) VALUES(?,?,?,?,?,?,?,?)",rows)


# Only first-person, explicit standing preferences are eligible for unattended publication.
# Factual holdings, observed behavior and risk limits require their own independent evidence.
SELF_REPORTED_PREFERENCES = {
    "preferred_investment_vehicles","preferred_return_drivers","primary_investment_goal",
    "performance_benchmark","monitoring_availability","intended_holding_period","stated_exit_basis",
}


def merge_supported(user, db, fields, proposal_id):
    cols = "attribute,expected_value,suggested_value,quote,source_message,source_task,reviewer,review_reason,created_at,status"
    row = db.execute("SELECT "+cols+" FROM proposals WHERE id=?",(proposal_id,)).fetchone()
    if not row:
        raise ValueError("提案不存在")
    key, old, value, quote, message, task, reviewer, reason, stamp, status = row
    if status=="merged":
        return True
    if status!="supported" or key not in SELF_REPORTED_PREFERENCES or not reviewer:
        return False
    if not re.search(r"我|本人",quote) or not re.search(r"以后|今后|长期|从现在起|默认|一贯",quote):
        return False
    packet=dict(source_id="review-"+proposal_id,origin="review",effective_at=stamp,proposal_id=proposal_id,
                evidence={message:{"quote":quote,"task":task,"reviewer":reviewer}},
                decisions={key:dict(old=json.loads(old),value=json.loads(value),decision="applied",refs=[message],reason=reason)})
    apply(user,db,fields,packet)
    return True


def reindex(user):
    with closing(sqlite3.connect(user/"index/wiki-search.sqlite")) as db, db:
        db.execute("DELETE FROM sections")
        for page in sorted((user/"wiki").rglob("*.md")):
            if page.is_symlink() or not page.resolve().is_relative_to((user/"wiki").resolve()):
                continue
            for paragraph in page.read_text().split("\n\n"):
                if paragraph.strip():
                    db.execute("INSERT INTO sections VALUES(?,?,?)",(str(page.relative_to(user)),page.stem,paragraph.strip()))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data",type=Path,default=ROOT/"data")
    ap.add_argument("action",choices=["init","apply","reindex","merge-supported"])
    ap.add_argument("--proposal",help="已审提案编号")
    args=ap.parse_args()
    os.umask(0o077)
    data=args.data.resolve()
    user=data/"user"
    fields=definitions()
    with locked(data):
        initialize(user)
        with closing(sqlite3.connect(user/REVIEW_DB)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            if args.action=="apply":
                apply(user,db,fields,json.load(sys.stdin))
            if args.action=="merge-supported":
                print(json.dumps({"merged":merge_supported(user,db,fields,args.proposal)}))
            if args.action=="reindex":
                reindex(user)
            snapshot(user,db,fields)


if __name__=="__main__":
    main()

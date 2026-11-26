"""Publish the CEO's locally validated review and rebuild its readable projections."""
from contextlib import closing
from datetime import datetime, timedelta
from hashlib import sha256
import json
import re
import sqlite3
import sys
from pathlib import Path

from user_archive import (REVIEW_DB, TOPICS, apply, definitions, dump, evidence_rank, initialize,
                          locked, publish, reindex, snapshot, valid_value)


def replace_section(path, tag, body):
    before = path.read_text() if path.exists() else ""
    start, end = f"<!-- {tag} -->", f"<!-- /{tag} -->"
    pattern = re.compile(re.escape(start) + ".*?" + re.escape(end), re.S)
    block = start + "\n" + body.strip() + "\n" + end if body.strip() else ""
    after = pattern.sub(lambda _: block, before) if pattern.search(before) else (before.rstrip() + "\n\n" + block if block else before)
    publish(path, after.strip() + "\n" if after.strip() else "")


def evidence_ok(item, evidence):
    return bool(item["refs"]) and all(ref in evidence for ref in item["refs"])


def persist(data, job):
    fields = definitions()
    user = data / "user"
    ref, stamp, kind = job["id"], job["at"], job["kind"]
    if not re.fullmatch(r"(intake|daily)-[a-zA-Z0-9-]{1,80}", ref) or kind not in ("intake", "daily"):
        raise ValueError("档案作业编号无效")
    initialize(user)
    state = data / "user-archive-state"
    path = state / (ref + ".json")
    with closing(sqlite3.connect(user / REVIEW_DB)) as db:
        if path.exists():
            job = json.loads(path.read_text())
        else:
            out, evidence = job["review"], job["evidence"]
            by_id = {f["id"]: f for f in fields.values()}
            rows = out["attributes"]
            if len({r["id"] for r in rows}) != len(rows) or (kind == "intake" and {r["id"] for r in rows} != set(by_id)):
                raise ValueError("属性清单不完整")
            decisions, declarations, report = {}, {}, []
            for row in rows:
                f = by_id[row["id"]]
                key, value, refs, reason = f["key"], row["value"], row["refs"], row["reason"]
                if not valid_value(f, value):
                    value = None
                    reason += "；值域或单位未通过属性字典核验，请补充。"
                if not evidence_ok(row, evidence):
                    raise ValueError("属性来源或值域不符 " + f["id"])
                prior = db.execute("SELECT d.new_value,b.origin,b.effective_at FROM decisions d JOIN batches b USING(source_id) WHERE d.attribute=? AND d.decision='applied' ORDER BY d.seq DESC LIMIT 1", (key,)).fetchone()
                old = json.loads(prior[0]) if prior else None
                supported = value is not None
                origin = "questionnaire" if kind=="intake" else ("observed" if row.get("verifiedBehavior") is True else "dialogue")
                source_label = {"questionnaire":"P2 评测问卷","observed":"P0 言行交叉核实","dialogue":"P1 对话自述"}[origin]
                if kind == "intake":
                    pair = [f["id"] + "-1", f["id"] + "-2"]
                    supported &= all(k in refs and evidence[k]["selected"] != "记不清、暂不适用或不便回答" for k in pair)
                    if f["id"] == "A13" or f["id"] in ("A32","A33","A34","A35","A36","A37"):
                        # These fields require dated records or enough individual observations.
                        supported &= any(evidence[k].get("note","").strip() or k.startswith("M") for k in refs)
                else:
                    personal = {evidence[k].get("message", k) for k in refs if evidence[k].get("role") == "user"}
                    records = {k for k in refs if evidence[k].get("role") == "trade"}
                    if origin=="observed":
                        supported &= len(personal) + len(records) >= 2
                    else:
                        supported &= bool(personal) and row.get("explicitFact") is True
                    if f["id"] == "A13":
                        supported = False  # imported, dated institutional assessment needed
                    elif f["id"] in {"A32","A33","A34","A35","A36","A37"}:
                        supported &= len(records) >= 3 and origin=="observed"
                if prior and prior[2] > stamp and evidence_rank(prior[1]) <= evidence_rank(origin):
                    supported = False
                    reason += "；档案已有更晚的同级或更高级记录，请按时间复核。"
                if prior and evidence_rank(prior[1]) < evidence_rank(origin):
                    supported = False
                    reason += f"；保留既有 P{evidence_rank(prior[1])} 依据，" + ("本次描述相符。" if old==value else "分歧留待核实。")
                reason = source_label + "，" + reason
                if not supported and value is not None and "复核" not in reason:
                    reason += "；本次证据未达到该维度的写入条件，请补充独立记录。"
                bucket = declarations if origin=="dialogue" else decisions
                bucket[key] = dict(old=old,value=value if supported else None,decision="applied" if supported else "pending",refs=refs,reason=reason)
                report.append(dict(id=f["id"],label=f["label"],value=value if supported else None,reason=reason,refs=refs,status="已采纳" if supported else "沿用原依据" if prior and value==old and old is not None else "待核实"))
            job["packet"] = dict(source_id=ref, origin="questionnaire" if kind=="intake" else "observed", effective_at=stamp,
                                 evidence=evidence, decisions=decisions, interview=job.get("document"), preset=job.get("preset"), review=out)
            if declarations:
                job["declarations"]=dict(source_id=ref+"-facts",origin="dialogue",effective_at=stamp,
                                         decisions=declarations,evidence=evidence,preset=job.get("preset"))
            job["report"] = report
            publish(path, dump(job))  # recover a partial publication using exactly the same decisions
        packet, out = job["packet"], job["review"]
        apply(user, db, fields, packet)
        if job.get("declarations"): apply(user,db,fields,job["declarations"])
        category = "P2 评测问卷" if kind == "intake" else "每日整理，逐项见原始记录"
        citation = f"（{category}，{stamp[:10]}，[来源](../sources/{ref}.json)）"
        if kind == "intake":
            prefs = [r for r in out["preferences"] if "P01-2" in r["refs"] and job["evidence"]["P01-2"]["selected"] not in ("暂不设长期要求","记不清、暂不适用或不便回答")]
            replace_section(user/"preferences/instructions.md","ceo-interview", "\n".join("- "+r["text"]+citation for r in prefs))
            accepted = [r["id"] for r in job["report"] if r["status"]=="已采纳"]
            publish(state/"interview-summary.md", f"{stamp[:10]} 总经理复核了完整访谈（P2 评测问卷）。本次采纳 {len(accepted)} 项。逐项依据见 [赋值对照](reviews/赋值对照.md)，差异见 [待确认属性](reviews/待确认属性.md)。")
        snapshot(user,db,fields)
        recent_path = state/"ceo-recent.json"
        recent = json.loads(recent_path.read_text()) if recent_path.exists() else {}
        for old_ref, group in recent.items():
            for i,r in enumerate(group["items"]):
                if kind=="daily" and old_ref+":"+str(i) in out.get("resolved",[]) and group["at"]<=stamp:
                    r["resolved"]=True
        recent[ref] = {"at":stamp, "items":out["recent"]}
        latest = max(datetime.fromisoformat(x["at"].replace("Z","+00:00")) for x in recent.values())
        recent = {k:v for k,v in recent.items() if datetime.fromisoformat(v["at"].replace("Z","+00:00")) >= latest-timedelta(days=7) and (kind!="intake" or not k.startswith("intake-") or k==ref)}
        publish(recent_path,dump(recent))
        lines = []
        for k,v in sorted(recent.items(), key=lambda x:x[1]["at"], reverse=True):
            for r in v["items"]:
                if r.get("resolved"): continue
                source_kind="P2 评测问卷" if k.startswith("intake-") else "每日言行整理"
                line=f"- {r['text']}（{source_kind}，{v['at'][:10]}，{k}，{', '.join(r['refs'])}）"
                if sum(map(len,lines))+len(line) <= 2200: lines.append(line)
        replace_section(user/"recent-memory.md","ceo-recent","\n".join(lines))
        for item in out["longTerm"]:
            title = item["title"].strip()
            if item["category"] not in TOPICS or not re.fullmatch(r"[\w（）() ·-]{1,48}",title): raise ValueError("主题页名称无效")
            page = user/"wiki"/item["category"]/(title+".md")
            if not page.exists(): publish(page,"# "+title+"\n")
            token=sha256((ref+title+str(item["refs"])).encode()).hexdigest()[:24]
            replace_section(page,token,item["text"]+f"（{category}，{stamp[:10]}，[来源](../../sources/{ref}.json)，{', '.join(item['refs'])}）")
        if out["longTerm"]: reindex(user)
        if kind=="intake":
            current={"version":4,"updated":stamp,"revision":ref,"overview":out["overview"],"findings":job["report"],
                     "document":job["document"],"preferences":prefs,"recent":out["recent"]}
            publish(user/"reviews/interview-result.json",dump(current))
        latest_report=user/"reviews/interview-result.json"
        if latest_report.exists():
            result=json.loads(latest_report.read_text())
            gaps = [f"- {r['id']} {r['label']}：{r['reason']}" for r in result["findings"] if r["status"]=="待核实"]
            replace_section(user/"reviews/待确认属性.md","ceo-interview","\n".join(["## 最近访谈需补证",*gaps]) if gaps else "")
        return {"source":ref,"fields":len(job["report"])}


def confirmed_note(data, note):
    user = data/"user"
    slug = note["id"]
    if not re.fullmatch(r"[a-f0-9]{8}",slug):
        raise ValueError("确认编号无效")
    places = {"recent":"recent-memory.md","preferences":"preferences/instructions.md",
              "thesis":"wiki/投资观点/本人确认.md","research":"wiki/研究委托/本人确认.md",
              "watch":"wiki/关注的证券/本人确认.md","review":"wiki/投资复盘/本人确认.md"}
    dest = places[note["destination"]]
    path = user/dest
    source = f"dialogue-{slug}.json"
    publish(user/"sources"/source, dump(note))
    import os
    link=os.path.relpath(user/"sources"/source,path.parent)
    replace_section(path,"ceo-"+slug,f"- {note['text']}（{note['at'][:10]}，P1 本人对话二次确认，{note['reason']}，[原话]({link})）")
    with closing(sqlite3.connect(user/REVIEW_DB)) as db:
        snapshot(user,db,definitions())
        if dest.startswith("wiki/"): reindex(user)
    return {"source":source}


if __name__ == "__main__":
    import os
    os.umask(0o077)
    data=Path(sys.argv[1]).resolve()
    with locked(data):
        job=json.load(sys.stdin)
        result=confirmed_note(data,job) if sys.argv[2:]==["confirmed-note"] else persist(data,job)
        print(json.dumps(result,ensure_ascii=False))

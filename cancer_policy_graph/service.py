from __future__ import annotations
import json
import uuid
from pathlib import Path
from typing import Any, Mapping
from cancer_policy_graph.runtime import DomainError, ProcessingContext, SQLiteLedger, fingerprint, normalize_text
from cancer_policy_graph.documents.catalog import build_processor as catalog_factory
from cancer_policy_graph.parsing.sections import build_processor as sections_factory
from cancer_policy_graph.terminology.alignment import build_processor as alignment_factory
from cancer_policy_graph.claims.model import build_processor as model_factory
from cancer_policy_graph.graph.relations import build_processor as relations_factory
from cancer_policy_graph.versions.policy_diff import build_processor as policy_diff_factory
from cancer_policy_graph.adjudication.conflicts import build_processor as conflicts_factory
from cancer_policy_graph.exports.evidence_package import build_processor as evidence_package_factory

PROCESSOR_FACTORIES = [catalog_factory, sections_factory, alignment_factory, model_factory, relations_factory, policy_diff_factory, conflicts_factory, evidence_package_factory]

class ApplicationService:
    def __init__(self, database: str | Path):
        self.ledger=SQLiteLedger(database)
        self.processors=[factory() for factory in PROCESSOR_FACTORIES]

    def validate_input(self, record: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(record, Mapping): raise DomainError("record must be object")
        result=dict(record)
        result["case_id"]=normalize_text(result.get("case_id"),"case_id",96)
        if not result["case_id"]: raise DomainError("case_id is required")
        result.setdefault("subject_id",result["case_id"])
        result.setdefault("category","screening")
        result.setdefault("region","synthetic-region")
        result.setdefault("event_date","2026-11-11")
        result.setdefault("status","new")
        result.setdefault("count",1)
        result.setdefault("total",1)
        result.setdefault("attributes",{"source":"synthetic"})
        result.setdefault("tags",["offline","fixture"])
        result.setdefault("source_system","local-fixture")
        result.setdefault("revision",0)
        return result

    def execute(self, record: Mapping[str, Any], request_key: str | None=None) -> dict[str, Any]:
        normalized=self.validate_input(record)
        normalized=self.architecture_preflight(normalized)
        key=request_key or fingerprint(normalized)
        recalled=self.ledger.recalled(key)
        if recalled is not None: return recalled | {"replayed":True}
        ctx=ProcessingContext(uuid.uuid4().hex,normalized["case_id"],normalized)
        ctx.emit("received","run_started",project='cancer_policy_graph')
        try:
            for processor in self.architecture_plan(ctx):
                processor.process(ctx)
                self.ledger.save(ctx)
        except Exception as exc:
            self.ledger.dead_letter(ctx,ctx.state,str(exc),normalized)
            raise
        self.architecture_finalize(ctx)
        ctx.advance("completed")
        self.ledger.save(ctx)
        response={"project":'cancer_policy_graph',"run_id":ctx.run_id,"case_id":ctx.case_id,"state":ctx.state,
                  "revision":ctx.revision,"flags":ctx.flags,"metrics":ctx.metrics,"evidence_count":len(ctx.evidence),
                  "event_count":len(ctx.events),"payload":ctx.payload,"replayed":False}
        self.ledger.remember(key,ctx.run_id,response)
        return response

    def architecture_preflight(self, record):
        record=dict(record)
        record["evidence_graph"]={"nodes":{},"edges":[],"conflicts":[]}
        return record

    def architecture_plan(self, ctx):
        graph=ctx.payload["evidence_graph"]
        plan=[]
        for processor in self.processors:
            graph["nodes"][processor.stage]={"kind":"stage","status":"planned"}
            if plan: graph["edges"].append({"from":plan[-1].stage,"to":processor.stage,"type":"derives"})
            plan.append(processor)
        return plan

    def architecture_finalize(self, ctx):
        graph=ctx.payload["evidence_graph"]
        for flag in ctx.flags: graph["conflicts"].append({"flag":flag,"decision":"human-review"})
        for node in graph["nodes"].values(): node["status"]="materialized"
        ctx.metrics["graph_nodes"]=len(graph["nodes"]); ctx.metrics["graph_edges"]=len(graph["edges"])
        ctx.emit("evidence_graph","graph_exported",nodes=len(graph["nodes"]),edges=len(graph["edges"]))

    def execute_many(self, records: list[Mapping[str, Any]]) -> dict[str, Any]:
        outputs=[]; failures=[]
        for index, record in enumerate(records):
            try: outputs.append(self.execute(record,request_key=f"batch:{index}:{fingerprint(record)}"))
            except Exception as exc: failures.append({"index":index,"error":str(exc)})
        return {"accepted":outputs,"failures":failures,"accepted_count":len(outputs),"failure_count":len(failures)}

def run_fixture(fixture: str | Path, database: str | Path) -> dict[str, Any]:
    data=json.loads(Path(fixture).read_text(encoding="utf-8"))
    service=ApplicationService(database)
    if isinstance(data,list): return service.execute_many(data)
    return service.execute(data)

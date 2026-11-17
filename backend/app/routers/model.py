"""分析模型 DAG 拓扑接口：返回节点、连线图结构，并按用户组给出可部署版本与部署详情。"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services.model import ModelService

router = APIRouter(prefix="/api/model", tags=["分析模型"])
service = ModelService()
LIST_FIELDS = ["模型编号", "模型名称", "模型类型", "训练数据集", "特征字段", "目标字段", "评估指标", "模型状态"]
STATUSES = ["草稿", "已训练", "评估中", "已部署", "已下线"]


def csv_cell(value: Any) -> str:
    text = str(value) if value is not None else ""
    if text and text[0] in "=+-@":
        text = "'" + text
    return '"' + text.replace('"', '""') + '"'


def current_group(group: str | None, 用户组: str | None) -> str:
    """兼容 group 与中文「用户组」两种查询参数。"""
    return (用户组 or group or "").strip()


@router.get("")
def get_graph() -> dict[str, Any]:
    """返回节点与边组成的 DAG 图数据。"""
    return service.get_graph()


@router.get("/export")
def export_entries() -> StreamingResponse:
    nodes, edges = service.raw_data()
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(["type", "id", "name", "from", "to", "label", "status"])
    for node in nodes:
        writer.writerow(["node", node.get("id",""), csv_cell(node.get("name","")), "", "", "", node.get("status","")])
    for edge in edges:
        writer.writerow(["edge", "", "", edge.get("from",""), edge.get("to",""), edge.get("label",""), ""])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=model.csv"})


@router.get("/deployable")
def list_deployable(
    group: str | None = Query(default=None, description="当前用户组名称"),
    用户组: str | None = Query(default=None, description="当前用户组名称（中文参数）"),
) -> dict[str, Any]:
    """按用户组授权的模型部署版本：只返回当前用户组可部署、且特征快照范围已脱敏的版本。"""
    group_name = current_group(group, 用户组)
    return {"items": service.deployable_versions(group_name), "用户组": group_name}


@router.get("/{entry_id}")
def get_entry(entry_id: int) -> dict:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"模型配置 {entry_id} 不存在")
    return entry


@router.get("/{entry_id}/deployment")
def get_deployment(
    entry_id: int,
    group: str | None = Query(default=None, description="当前用户组名称"),
    用户组: str | None = Query(default=None, description="当前用户组名称（中文参数）"),
) -> dict:
    """部署详情：说明授权来源和特征快照范围；越权查看被拒绝（403）。"""
    group_name = current_group(group, 用户组)
    detail, error = service.deployment_detail(entry_id, group_name)
    if error == "not_found":
        raise HTTPException(status_code=404, detail=f"模型配置 {entry_id} 不存在")
    if error == "forbidden":
        raise HTTPException(
            status_code=403,
            detail=f"越权查看被拒绝：用户组「{group_name}」无权读取模型 {entry_id} 的部署详情与特征快照",
        )
    return detail


@router.post("")
def create_entry(payload: EntryPayload) -> ActionResult:
    entry_or_none, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="模型配置已登记", entry=entry_or_none)


@router.post("/{entry_id}/actions")
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    entry_or_none, message = service.run_action(entry_id, payload.action, group=payload.group)
    if entry_or_none is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry_or_none)

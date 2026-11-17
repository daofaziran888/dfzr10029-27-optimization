"""分析模型 DAG 图服务：生成节点、边示例结构与流转规则。

部署与评估动作会顺着既有取数调用关系，跨模块读取模型版本授权记录：
- 部署模型前按当前用户组校验模型版本归属与特征快照可见范围，越权部署被拒绝；
- 启动评估会把核对结果写回模型版本授权记录，并保留对应模型版本。
"""
from __future__ import annotations

from typing import Any

from app.services.model_version_auth import ModelVersionAuthService
from app.store import store

MODULE = "model"
REQUIRED_FIELDS = ["模型编号", "模型名称", "模型类型"]
STATUS_ORDER = ["草稿", "已训练", "评估中", "已部署", "已下线"]
ACTION_RULES = {"提交训练": "已训练", "启动评估": "评估中", "部署模型": "已部署"}
NEGATIVE_ACTIONS = []

auth_service = ModelVersionAuthService()


def csv_cell(value: Any) -> str:
    text = str(value) if value is not None else ""
    if text and text[0] in "=+-@":
        text = "'" + text
    return '"' + text.replace('"', '""') + '"'


class ModelService:
    def get_graph(self) -> dict[str, Any]:
        rows = store.rows(MODULE)
        nodes: list[dict] = []
        edges: list[dict] = []
        for i, row in enumerate(rows):
            nodes.append({"id": int(row.get("id", i+1)), "name": str(row.get(list(row.keys())[1] if len(row)>1 else "name", "")), "status": str(row.get("status", STATUS_ORDER[0])),
                          **{k: row[k] for k in row if k not in ("id","status","pending","abnormal")}})
        for i in range(len(nodes)-1):
            edges.append({"from": nodes[i]["id"], "to": nodes[i+1]["id"], "label": "依赖"})
        return {"nodes": nodes, "edges": edges}

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [f for f in REQUIRED_FIELDS if not str(values.get(f) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(r.get("id",0)) for r in rows), default=0) + 1}
        entry.update({f: values.get(f) for f in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str, group: str | None = None) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"模型配置 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于分析模型可执行范围"
        deploy_detail: dict[str, Any] | None = None
        if action == "部署模型":
            ok, message, deploy_detail = auth_service.check_deploy(entry, group)
            if not ok:
                return None, message
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        message = f"模型配置已{action}"
        if action == "启动评估":
            # 模型评估接口：把核对结果写回模型版本授权记录，保留对应模型版本。
            updated = auth_service.verify_model(entry)
            if updated:
                summary = "、".join(f"{row.get('授权编号')}={row.get('核对结果')}" for row in updated)
                message = f"模型配置已启动评估，授权核对结果已写入：{summary}"
            else:
                message = "模型配置已启动评估，暂无关联的模型版本授权记录"
        if action == "部署模型" and deploy_detail is not None:
            message = (
                f"模型配置已部署模型，授权来源：{deploy_detail['授权来源']}，"
                f"特征快照范围：{deploy_detail['特征快照范围']}"
            )
        return entry, message

    def deployable_versions(self, group: str) -> list[dict[str, Any]]:
        """模型页只展示当前用户组可部署的版本。"""
        return auth_service.deployable_versions(group)

    def deployment_detail(self, entry_id: int, group: str) -> tuple[dict[str, Any] | None, str]:
        """部署详情：说明授权来源和特征快照范围；越权查看被拒绝。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, "not_found"
        detail = auth_service.deployment_detail(entry, group)
        if detail is None:
            return None, "forbidden"
        return detail, ""

    def raw_data(self) -> tuple[list[dict], list[dict]]:
        g = self.get_graph()
        return g["nodes"], g["edges"]

"""模型版本授权记录业务规则：按用户组控制模型版本的部署授权与特征快照可见范围。

加工口径（读取当前数据后按用户组授权模型版本部署）：
- 顺着既有取数调用关系，跨模块读取模型版本（model）、用户组（user_group）
  与训练特征快照版本源记录（snapshot），定位授权差异；
- 特征快照读取权归训练数据集所属用户组；模型创建组与数据集归属组不一致时，
  统一按数据集归属裁定，保证冲突后仍有唯一核对结果；
- 提交授权记录时同（模型编号、模型版本、授权用户组）只保留一份有效版本，
  旧版本自动置为已失效；
- 模型评估（启动评估）会把核对结果写回授权记录，并保留对应模型版本输入。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "model_version_auth"
LIST_FIELDS = ["授权编号", "模型编号", "模型版本", "授权用户组", "授权来源", "特征快照范围", "核对结果", "记录状态"]
REQUIRED_FIELDS = ["授权编号", "模型编号", "模型版本", "授权用户组"]
STATUS_ORDER = ["待核对", "生效中", "已回收"]
ACTION_RULES = {"核对授权": "生效中", "回收授权": "已回收"}
NEGATIVE_ACTIONS = ["回收授权"]
# 已失效：被同键新记录取代的历史版本；已回收：显式收回的授权。
INACTIVE_STATUSES = ("已失效", "已回收")
MASKED_SCOPE = "无权读取特征快照"
MASKED_DATASET = "无权读取"


def _model_rows() -> list[dict[str, Any]]:
    return store.rows("model")


def _group_rows() -> list[dict[str, Any]]:
    return store.rows("user_group")


def _snapshot_rows() -> list[dict[str, Any]]:
    return store.rows("snapshot")


def find_model(model_code: str) -> dict[str, Any] | None:
    for row in _model_rows():
        if str(row.get("模型编号", "")) == model_code:
            return row
    return None


def find_group(group_name: str) -> dict[str, Any] | None:
    for row in _group_rows():
        if group_name and group_name in (str(row.get("组名称", "")), str(row.get("组编号", ""))):
            return row
    return None


def feature_snapshots(model_row: dict[str, Any]) -> list[dict[str, Any]]:
    """训练特征快照版本源记录：按模型的训练数据集回查快照模块。"""
    dataset = str(model_row.get("训练数据集", "") or "")
    if not dataset:
        return []
    return [row for row in _snapshot_rows() if str(row.get("数据集名称", "")) == dataset]


class ModelVersionAuthService:
    def resolve(self, model_row: dict[str, Any], group_name: str) -> dict[str, Any]:
        """唯一核对口径：模型版本归属与用户组可见范围一起校验。

        返回授权来源、特征快照范围与核对结果；特征快照读取权只给数据集归属组，
        其他组可引用同一模型版本，但看不到特征数据来自哪个训练集。
        """
        snapshots = feature_snapshots(model_row)
        owner_groups = {str(s.get("所属用户组", "")) for s in snapshots if s.get("所属用户组")}
        created_group = str(model_row.get("创建用户组", "") or "")
        group_row = find_group(group_name)
        if group_name and group_name == created_group:
            source = "模型创建组授权"
        elif group_name in owner_groups:
            source = "数据集归属授权"
        else:
            source = "组间共享授权"
        can_read = bool(group_name) and group_name in owner_groups
        scope = "、".join(str(s.get("快照编号", "")) for s in snapshots) if can_read and snapshots else MASKED_SCOPE
        if group_row is not None and str(group_row.get("status", "")) == "已删除":
            result = "越权拒绝"
        elif not owner_groups or created_group in owner_groups:
            result = "核对一致"
        else:
            result = "冲突-按数据集归属授权"
        return {
            "授权来源": source,
            "特征快照范围": scope,
            "核对结果": result,
            "可读取快照": can_read,
            "快照来源": snapshots if can_read else [],
        }

    def _valid_record(self, model_code: str, group_name: str) -> dict[str, Any] | None:
        """同一（模型、用户组）只取一份有效授权记录；提交时已保证唯一，这里取最新兜底。"""
        matched = [
            row for row in store.rows(MODULE)
            if str(row.get("模型编号", "")) == model_code
            and str(row.get("授权用户组", "")) == group_name
            and row.get("status") not in INACTIVE_STATUSES
        ]
        return matched[-1] if matched else None

    def deployable_versions(self, group_name: str) -> list[dict[str, Any]]:
        """最终产物：按用户组授权的模型部署版本；特征快照范围按归属脱敏。"""
        items: list[dict[str, Any]] = []
        if not group_name:
            return items
        for record in store.rows(MODULE):
            if record.get("status") != STATUS_ORDER[1]:
                continue
            if str(record.get("授权用户组", "")) != group_name:
                continue
            model = find_model(str(record.get("模型编号", "")))
            if model is None:
                continue
            resolved = self.resolve(model, group_name)
            if resolved["核对结果"] == "越权拒绝":
                continue
            items.append({
                "授权编号": record.get("授权编号"),
                "模型id": model.get("id"),
                "模型编号": record.get("模型编号"),
                "模型版本": record.get("模型版本"),
                "模型名称": model.get("模型名称"),
                "模型类型": model.get("模型类型"),
                "训练数据集": model.get("训练数据集") if resolved["可读取快照"] else MASKED_DATASET,
                "授权来源": resolved["授权来源"],
                "特征快照范围": resolved["特征快照范围"],
                "核对结果": resolved["核对结果"],
                "授权状态": record.get("status"),
            })
        return items

    def deployment_detail(self, model_row: dict[str, Any], group_name: str) -> dict[str, Any] | None:
        """部署详情：说明授权来源和特征快照范围，并共享授权记录来源记录；越权查看返回 None。"""
        if not group_name:
            return None
        model_code = str(model_row.get("模型编号", ""))
        record = self._valid_record(model_code, group_name)
        if record is None or record.get("status") != STATUS_ORDER[1]:
            return None
        resolved = self.resolve(model_row, group_name)
        if resolved["核对结果"] == "越权拒绝":
            return None
        group_row = find_group(group_name)
        return {
            "模型编号": model_code,
            "模型名称": model_row.get("模型名称"),
            "模型版本": record.get("模型版本"),
            "授权编号": record.get("授权编号"),
            "授权用户组": group_name,
            "授权来源": resolved["授权来源"],
            "特征快照范围": resolved["特征快照范围"],
            "训练数据集": model_row.get("训练数据集") if resolved["可读取快照"] else MASKED_DATASET,
            "核对结果": resolved["核对结果"],
            "来源记录": {
                "模型来源": {
                    "模型编号": model_code,
                    "模型名称": model_row.get("模型名称"),
                    "创建用户组": model_row.get("创建用户组", ""),
                },
                "快照来源": [
                    {"快照编号": s.get("快照编号"), "数据集名称": s.get("数据集名称"), "快照时间": s.get("快照时间")}
                    for s in resolved["快照来源"]
                ],
                "用户组来源": {
                    "组编号": (group_row or {}).get("组编号", ""),
                    "组名称": (group_row or {}).get("组名称", group_name),
                },
                "授权记录来源": {
                    "授权编号": record.get("授权编号"),
                    "模型版本": record.get("模型版本"),
                    "记录状态": record.get("记录状态", record.get("status")),
                },
            },
        }

    def check_deploy(self, model_row: dict[str, Any], group_name: str | None) -> tuple[bool, str, dict[str, Any] | None]:
        """部署前校验：模型版本归属和用户组可见范围一起通过才允许部署。"""
        if not group_name:
            return False, "部署模型需要先选择当前用户组", None
        detail = self.deployment_detail(model_row, group_name)
        if detail is None:
            model_code = str(model_row.get("模型编号", ""))
            return False, f"越权部署被拒绝：用户组「{group_name}」未获得模型 {model_code} 生效中的版本授权", None
        return True, "", detail

    def verify_model(self, model_row: dict[str, Any]) -> list[dict[str, Any]]:
        """模型评估接口写回核对结果：只更新有效授权记录，保留对应模型版本输入。"""
        model_code = str(model_row.get("模型编号", ""))
        updated: list[dict[str, Any]] = []
        for record in store.rows(MODULE):
            if str(record.get("模型编号", "")) != model_code:
                continue
            if record.get("status") in INACTIVE_STATUSES:
                continue
            resolved = self.resolve(model_row, str(record.get("授权用户组", "")))
            record["授权来源"] = resolved["授权来源"]
            record["特征快照范围"] = resolved["特征快照范围"]
            record["核对结果"] = resolved["核对结果"]
            record["abnormal"] = resolved["核对结果"] == "冲突-按数据集归属授权"
            updated.append(record)
        return updated

    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("授权编号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        # 读取当前数据，按用户组授权口径加工授权来源、特征快照范围与核对结果；
        # 模型版本等版本输入按提交内容保留。
        model = find_model(str(entry.get("模型编号", ""))) or {}
        resolved = self.resolve(model, str(entry.get("授权用户组", "")))
        entry["授权来源"] = resolved["授权来源"]
        entry["特征快照范围"] = resolved["特征快照范围"]
        entry["核对结果"] = resolved["核对结果"]
        entry["status"] = STATUS_ORDER[0]
        entry["记录状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = resolved["核对结果"] != "核对一致"
        # 提交时只生成一份有效版本：同键旧记录统一置为已失效。
        for old in rows:
            if (
                str(old.get("模型编号", "")) == str(entry.get("模型编号", ""))
                and str(old.get("模型版本", "")) == str(entry.get("模型版本", ""))
                and str(old.get("授权用户组", "")) == str(entry.get("授权用户组", ""))
                and old.get("status") not in INACTIVE_STATUSES
            ):
                old["status"] = "已失效"
                old["记录状态"] = "已失效"
                old["pending"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"模型版本授权记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于模型版本授权可执行范围"
        if action == "核对授权":
            # 核对时按当前数据重算唯一核对结果；越权记录不允许转为生效。
            model = find_model(str(entry.get("模型编号", ""))) or {}
            resolved = self.resolve(model, str(entry.get("授权用户组", "")))
            entry["授权来源"] = resolved["授权来源"]
            entry["特征快照范围"] = resolved["特征快照范围"]
            entry["核对结果"] = resolved["核对结果"]
            entry["abnormal"] = resolved["核对结果"] != "核对一致"
            if resolved["核对结果"] == "越权拒绝":
                return None, f"核对未通过：用户组「{entry.get('授权用户组')}」越权拒绝，授权记录保持待核对"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["记录状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        if action in NEGATIVE_ACTIONS:
            entry["abnormal"] = True
        return entry, f"模型版本授权记录已{action}"

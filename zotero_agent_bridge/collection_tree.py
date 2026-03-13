from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import BridgeError

_UNSET = object()


@dataclass(frozen=True, slots=True)
class DesiredCollection:
    slot: str
    name: str
    parent_slot: str | None
    existing_key: str | None = None


DEFAULT_COLLECTION_PLAN: tuple[DesiredCollection, ...] = (
    DesiredCollection("inbox", "00_待整理", None, "HL2J63GW"),
    DesiredCollection("topics_root", "10_研究主题", None, "37ANA6WH"),
    DesiredCollection("paper_types_root", "20_论文类型", None),
    DesiredCollection("special_shelves_root", "30_专题书架", None),
    DesiredCollection("tools_root", "40_工具与标准", None, "UGM8HKPE"),
    DesiredCollection("archive_root", "90_归档", None),
    DesiredCollection("space_architecture", "11_空间网络与体系结构", "topics_root"),
    DesiredCollection("reliability_coding", "12_可靠传输与编码", "topics_root"),
    DesiredCollection("routing_transport", "13_路由与传输控制", "topics_root"),
    DesiredCollection("physical_link", "14_物理层与链路", "topics_root"),
    DesiredCollection("semantic_comm", "15_语义通信", "topics_root", "BGMP5ZS2"),
    DesiredCollection("ai_root", "16_AI与智能优化", "topics_root", "7H8VSG3J"),
    DesiredCollection("remote_sensing", "遥感卫星", "space_architecture", "R9JKSHZ5"),
    DesiredCollection("fec", "FEC", "reliability_coding", "9ZTT5NXY"),
    DesiredCollection("harq", "HARQ", "reliability_coding", "IZZ84DM3"),
    DesiredCollection("congestion_control", "拥塞控制", "routing_transport", "MDSFUHPI"),
    DesiredCollection("routing_networking", "路由与组网", "routing_transport"),
    DesiredCollection("ccsds_dtn", "CCSDS与DTN协议", "routing_transport"),
    DesiredCollection("channel_modeling", "信道建模", "physical_link", "8WK2R8EB"),
    DesiredCollection("laser_optical", "激光与光通信", "physical_link", "DJQ7VVI8"),
    DesiredCollection("frame_structure", "星地帧结构", "physical_link", "54XWKYG5"),
    DesiredCollection("deep_learning", "深度学习", "ai_root", "N4JZLXND"),
    DesiredCollection("reinforcement_learning", "强化学习", "ai_root", "66CJ9XTF"),
    DesiredCollection("llm", "LLM", "ai_root"),
    DesiredCollection("classic_papers", "经典", "paper_types_root", "LQRRRFMS"),
    DesiredCollection("surveys", "综述", "paper_types_root", "XLHQC9PW"),
    DesiredCollection("theses", "学位论文", "paper_types_root"),
    DesiredCollection("current_projects", "当前课题", "special_shelves_root"),
    DesiredCollection("group_internal", "组内与同门", "special_shelves_root", "539GTEZA"),
    DesiredCollection("conference_tracking", "会议追踪", "special_shelves_root"),
    DesiredCollection("model_focus", "模型专题", "special_shelves_root"),
    DesiredCollection("deepseek", "DeepSeek", "model_focus", "XP83YX6Q"),
    DesiredCollection("neurips_2025", "NeurIPS2025bestpaper", "conference_tracking", "C23WAPA4"),
    DesiredCollection("ccsds_standards", "CCSDS标准", "tools_root", "6XFKDIQM"),
    DesiredCollection("exata", "Exata", "tools_root", "ZRHJDMFQ"),
    DesiredCollection("other_manuals", "其他手册", "tools_root"),
)


class CollectionTreeManager:
    def __init__(self, local_client, writer) -> None:
        self.local_client = local_client
        self.writer = writer
        self.collections_by_key: dict[str, dict[str, Any]] = {}
        self.key_by_parent_and_name: dict[tuple[str | None, str], str] = {}

    def refresh(self) -> None:
        collections = self.local_client.list_collections()
        self.collections_by_key = {collection["collection_key"]: collection for collection in collections}
        self.key_by_parent_and_name = {
            (collection["parent_key"] or None, collection["name"]): collection["collection_key"]
            for collection in collections
        }

    def ensure_collection(self, name: str, parent_key: str | None = None) -> str:
        existing_key = self.key_by_parent_and_name.get((parent_key, name))
        if existing_key:
            return existing_key
        payload: dict[str, Any] = {"name": name}
        if parent_key is not None:
            payload["parent_key"] = parent_key
        result = self.writer.execute("create_collection", payload)
        self.local_client.invalidate_collection_cache()
        self.refresh()
        return str(result["collection_key"])

    def update_collection(
        self,
        collection_key: str,
        *,
        name: str | None = None,
        parent_key: str | None | object = _UNSET,
    ) -> str:
        current = self.collections_by_key.get(collection_key)
        if not current:
            raise BridgeError(404, "collection_not_found", f"Collection {collection_key} was not found")

        desired_name = current["name"] if name is None else name
        desired_parent_key = current["parent_key"] if parent_key is _UNSET else parent_key
        sibling_key = self.key_by_parent_and_name.get((desired_parent_key, desired_name))
        if sibling_key and sibling_key != collection_key:
            raise BridgeError(
                409,
                "collection_conflict",
                "Target collection path already exists",
                {
                    "collection_key": collection_key,
                    "existing_key": sibling_key,
                    "parent_key": desired_parent_key,
                    "name": desired_name,
                },
            )

        payload: dict[str, Any] = {
            "collection_key": collection_key,
            "version": current["version"],
        }
        if name is not None and name != current["name"]:
            payload["name"] = name
        if parent_key is not _UNSET and desired_parent_key != current["parent_key"]:
            payload["parent_key"] = desired_parent_key
        if len(payload) == 2:
            return collection_key

        self.writer.execute("update_collection", payload)
        self.local_client.invalidate_collection_cache()
        self.refresh()
        return collection_key

    def upsert_slot(self, desired: DesiredCollection, slot_keys: dict[str, str]) -> str:
        parent_key = slot_keys.get(desired.parent_slot) if desired.parent_slot else None
        if desired.existing_key and desired.existing_key in self.collections_by_key:
            self.update_collection(desired.existing_key, name=desired.name, parent_key=parent_key)
            return desired.existing_key
        return self.ensure_collection(desired.name, parent_key=parent_key)

    def build_paths(self) -> dict[str, str]:
        def build_path(collection_key: str) -> str:
            collection = self.collections_by_key[collection_key]
            parts = [collection["name"]]
            parent_key = collection["parent_key"]
            while parent_key:
                parent = self.collections_by_key[parent_key]
                parts.append(parent["name"])
                parent_key = parent["parent_key"]
            return "/".join(reversed(parts))

        return {collection_key: build_path(collection_key) for collection_key in self.collections_by_key}


def apply_default_collection_tree(local_client, writer) -> dict[str, Any]:
    manager = CollectionTreeManager(local_client, writer)
    manager.refresh()

    slot_keys: dict[str, str] = {}
    for desired in DEFAULT_COLLECTION_PLAN:
        slot_keys[desired.slot] = manager.upsert_slot(desired, slot_keys)

    manager.refresh()
    collection_paths = manager.build_paths()
    return {
        "collection_keys": slot_keys,
        "collection_paths": {slot: collection_paths[key] for slot, key in slot_keys.items()},
        "total_collections": len(manager.collections_by_key),
    }

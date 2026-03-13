from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .collection_tree import apply_default_collection_tree
from .models import UpdateItemRequest

ROOT_SLOT_NAMES = ("topics_root", "paper_types_root", "special_shelves_root", "tools_root")
OPTIONAL_TARGET_PATHS = {
    "network_coding": "10_研究主题/12_可靠传输与编码/FEC/网络编码",
    "satellite_harq": "10_研究主题/12_可靠传输与编码/HARQ/卫星场景HARQ",
    "model_librarys": "40_工具与标准/Exata/ModelLibrarys",
}
SURVEY_KEYWORDS = (
    "survey",
    "review",
    "tutorial",
    "overview",
    "comprehensive survey",
    "state of the art",
    "综述",
    "教程",
)
THESIS_KEYWORDS = (
    "thesis",
    "dissertation",
    "学位论文",
    "博士论文",
    "硕士论文",
)
MANUAL_KEYWORDS = (
    "manual",
    "handbook",
    "user guide",
    "quick reference",
    "速查",
    "手册",
    "指南",
    "入门",
    "introduction to",
)
EXATA_KEYWORDS = (
    "exata",
    "omnet",
    "ns 3",
    "opnet",
    "simulation tool",
    "simulator",
    "仿真工具",
)
MODEL_LIBRARY_KEYWORDS = ("model library", "modellibrary", "model librarys", "modellibrarys")
CCSDS_STANDARD_KEYWORDS = (
    "blue book",
    "green book",
    "magenta book",
    "recommended standard",
    "standard",
    "recommendation",
    "protocol specification",
    "标准",
    "建议书",
    "规范",
)
CCSDS_DTN_KEYWORDS = (
    "ccsds",
    "dtn",
    "delay tolerant",
    "bundle protocol",
    "bpv7",
    "ltn",
)
REMOTE_SENSING_KEYWORDS = (
    "remote sensing",
    "earth observation",
    "hyperspectral",
    "sar",
    "synthetic aperture radar",
    "遥感",
)
SEMANTIC_COMM_KEYWORDS = (
    "semantic communication",
    "semantic communications",
    "semantic coding",
    "task adaptive semantic",
    "scene graph",
    "visual semantics",
    "语义通信",
    "语义编码",
)
LLM_KEYWORDS = (
    "large language model",
    "llm",
    "gpt",
    "chatgpt",
    "deepseek",
    "qwen",
    "llama",
)
REINFORCEMENT_LEARNING_KEYWORDS = (
    "reinforcement learning",
    "policy optimization",
    "policy gradient",
    "actor critic",
    "q learning",
    "ppo",
    "强化学习",
)
DEEP_LEARNING_KEYWORDS = (
    "deep learning",
    "neural network",
    "convolutional neural",
    "cnn",
    "transformer",
    "dropout",
    "imagenet",
    "深度学习",
)
HARQ_KEYWORDS = (
    "harq",
    "hybrid automatic repeat request",
    "incremental redundancy",
    "hybrid automatic repeat",
)
SATELLITE_KEYWORDS = (
    "satellite",
    "leo",
    "non terrestrial",
    "ntn",
    "satcom",
    "space ground",
    "spaceborne",
    "卫星",
    "星地",
)
NETWORK_CODING_KEYWORDS = (
    "network coding",
    "network coded",
    "coded arq",
    "instantly decodable",
    "random linear network coding",
    "rlnc",
    "网络编码",
)
FEC_KEYWORDS = (
    "forward error correction",
    "fec",
    "streaming code",
    "erasure code",
    "lt code",
    "turbo code",
    "ldpc",
    "polar code",
    "bch",
    "reed solomon",
    "纠删码",
)
CONGESTION_CONTROL_KEYWORDS = (
    "congestion control",
    "performance enhancing proxy",
    "pep",
    "bbr",
    "cubic",
    "tcp proxy",
    "拥塞控制",
)
ROUTING_NETWORKING_KEYWORDS = (
    "routing",
    "network architecture",
    "satellite network",
    "constellation",
    "inter satellite",
    "non terrestrial network",
    "planetary scale",
    "组网",
    "路由",
)
CHANNEL_MODELING_KEYWORDS = (
    "channel model",
    "channel modeling",
    "fading",
    "path loss",
    "doppler",
    "attenuation",
    "turbulence",
    "pointing error",
    "osnr",
    "信道",
    "衰落",
    "湍流",
)
LASER_OPTICAL_KEYWORDS = (
    "laser communication",
    "laser communications",
    "optical communication",
    "free space optical",
    "fso",
    "lcrd",
    "tbird",
    "激光",
    "光通信",
    "光链路",
)
FRAME_STRUCTURE_KEYWORDS = (
    "frame structure",
    "physical frame",
    "slot structure",
    "superframe",
    "帧结构",
    "物理帧",
)


@dataclass(slots=True)
class ClassificationDecision:
    target_names: list[str]
    reasons: dict[str, list[str]]


def normalize_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = text.replace("-", " ").replace("_", " ").replace("/", " ")
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff+ ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _match_keyword(text: str, keyword: str) -> bool:
    normalized = normalize_text(keyword)
    if not normalized:
        return False
    if re.fullmatch(r"[0-9a-z+ ]+", normalized):
        pattern = rf"(?<![0-9a-z+]){re.escape(normalized)}(?![0-9a-z+])"
        return re.search(pattern, text) is not None
    return normalized in text


def keyword_hits(text: str, keywords: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for keyword in keywords:
        if _match_keyword(text, keyword) and keyword not in hits:
            hits.append(keyword)
    return hits


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def build_collection_paths(collections: list[dict[str, Any]]) -> dict[str, str]:
    by_key = {collection["collection_key"]: collection for collection in collections}
    paths: dict[str, str] = {}

    def resolve_path(collection_key: str) -> str:
        if collection_key in paths:
            return paths[collection_key]
        collection = by_key[collection_key]
        parent_key = collection.get("parent_key")
        if parent_key:
            path = f"{resolve_path(parent_key)}/{collection['name']}"
        else:
            path = str(collection["name"])
        paths[collection_key] = path
        return path

    for key in by_key:
        resolve_path(key)
    return paths


def resolve_target_keys(slot_keys: dict[str, str], collection_paths: dict[str, str]) -> dict[str, str]:
    resolved = dict(slot_keys)
    path_to_key = {path: key for key, path in collection_paths.items()}
    for alias, path in OPTIONAL_TARGET_PATHS.items():
        target_key = path_to_key.get(path)
        if target_key:
            resolved[alias] = target_key
    return resolved


def is_pending_candidate(existing_keys: list[str], slot_keys: dict[str, str]) -> bool:
    existing = set(existing_keys)
    if not existing:
        return True
    if slot_keys["inbox"] in existing:
        return True
    root_keys = {slot_keys[name] for name in ROOT_SLOT_NAMES if name in slot_keys}
    return existing.issubset(root_keys)


def build_classification_text(bundle: dict[str, Any]) -> str:
    fields = bundle.get("fields") or {}
    parts = [
        bundle.get("title") or "",
        fields.get("abstractNote") or "",
        fields.get("publicationTitle") or "",
        fields.get("conferenceName") or "",
        fields.get("proceedingsTitle") or "",
        fields.get("extra") or "",
        " ".join(str(tag) for tag in bundle.get("tags", [])),
    ]
    return normalize_text(" ".join(part for part in parts if part))


def classify_bundle(bundle: dict[str, Any], target_keys: dict[str, str]) -> ClassificationDecision:
    text = build_classification_text(bundle)
    title = normalize_text(bundle.get("title"))
    item_type = normalize_text(bundle.get("item_type") or bundle.get("fields", {}).get("itemType") or "")
    reasons: dict[str, list[str]] = {}

    def add_target(name: str, hits: list[str]) -> None:
        if not hits or name not in target_keys:
            return
        current = reasons.setdefault(name, [])
        current.extend(hit for hit in hits if hit not in current)

    thesis_hits = keyword_hits(text, THESIS_KEYWORDS)
    if item_type in {"thesis", "dissertation"}:
        thesis_hits = dedupe_keep_order(thesis_hits + [item_type])
    add_target("theses", thesis_hits)

    manual_hits = keyword_hits(title, MANUAL_KEYWORDS)
    survey_hits = keyword_hits(title, SURVEY_KEYWORDS)
    if survey_hits and not manual_hits:
        add_target("surveys", survey_hits)

    model_library_hits = keyword_hits(text, MODEL_LIBRARY_KEYWORDS)
    add_target("model_librarys", model_library_hits)

    exata_hits = keyword_hits(text, EXATA_KEYWORDS)
    if exata_hits:
        add_target("exata", exata_hits)

    ccsds_hits = keyword_hits(text, CCSDS_DTN_KEYWORDS)
    ccsds_standard_hits = keyword_hits(title, CCSDS_STANDARD_KEYWORDS)
    if ccsds_hits and ccsds_standard_hits:
        add_target("ccsds_standards", dedupe_keep_order(ccsds_hits + ccsds_standard_hits))
    elif ccsds_hits:
        add_target("ccsds_dtn", ccsds_hits)

    add_target("remote_sensing", keyword_hits(text, REMOTE_SENSING_KEYWORDS))
    add_target("semantic_comm", keyword_hits(text, SEMANTIC_COMM_KEYWORDS))

    llm_hits = keyword_hits(text, LLM_KEYWORDS)
    rl_hits = keyword_hits(text, REINFORCEMENT_LEARNING_KEYWORDS)
    dl_hits = keyword_hits(text, DEEP_LEARNING_KEYWORDS)
    add_target("llm", llm_hits)
    add_target("reinforcement_learning", rl_hits)
    if dl_hits and not llm_hits:
        add_target("deep_learning", dl_hits)

    harq_hits = keyword_hits(text, HARQ_KEYWORDS)
    satellite_hits = keyword_hits(text, SATELLITE_KEYWORDS)
    if harq_hits and satellite_hits and "satellite_harq" in target_keys:
        add_target("satellite_harq", dedupe_keep_order(harq_hits + satellite_hits))
    elif harq_hits:
        add_target("harq", harq_hits)

    network_coding_hits = keyword_hits(text, NETWORK_CODING_KEYWORDS)
    if network_coding_hits and "network_coding" in target_keys:
        add_target("network_coding", network_coding_hits)
    elif network_coding_hits:
        add_target("fec", network_coding_hits)

    add_target("fec", keyword_hits(text, FEC_KEYWORDS))
    add_target("congestion_control", keyword_hits(text, CONGESTION_CONTROL_KEYWORDS))
    add_target("routing_networking", keyword_hits(text, ROUTING_NETWORKING_KEYWORDS))
    add_target("channel_modeling", keyword_hits(text, CHANNEL_MODELING_KEYWORDS))
    add_target("laser_optical", keyword_hits(text, LASER_OPTICAL_KEYWORDS))
    add_target("frame_structure", keyword_hits(text, FRAME_STRUCTURE_KEYWORDS))

    if manual_hits and not reasons:
        add_target("other_manuals", manual_hits)
    elif manual_hits and "other_manuals" in target_keys and any(
        target in reasons for target in ("exata", "model_librarys", "ccsds_standards")
    ):
        add_target("other_manuals", manual_hits)

    if "satellite_harq" in reasons and "harq" in target_keys and "harq" not in reasons:
        if any(_match_keyword(title, keyword) for keyword in HARQ_KEYWORDS):
            add_target("harq", ["harq"])

    ordered_targets = [
        name
        for name in (
            "surveys",
            "theses",
            "ccsds_standards",
            "other_manuals",
            "model_librarys",
            "exata",
            "remote_sensing",
            "semantic_comm",
            "llm",
            "reinforcement_learning",
            "deep_learning",
            "satellite_harq",
            "harq",
            "network_coding",
            "fec",
            "congestion_control",
            "ccsds_dtn",
            "routing_networking",
            "channel_modeling",
            "laser_optical",
            "frame_structure",
        )
        if name in reasons
    ]
    return ClassificationDecision(target_names=ordered_targets, reasons=reasons)


def merge_collection_keys(existing_keys: list[str], target_keys: list[str], *, inbox_key: str) -> list[str]:
    final_keys = list(existing_keys)
    if target_keys:
        final_keys.extend(target_keys)
        final_keys = dedupe_keep_order(final_keys)
        if inbox_key in final_keys and any(key != inbox_key for key in target_keys):
            final_keys = [key for key in final_keys if key != inbox_key]
        return final_keys
    if final_keys:
        return final_keys
    return [inbox_key]


def is_collectable_parent_item(bundle: dict[str, Any]) -> bool:
    item_type = str(bundle.get("item_type") or "").casefold()
    if item_type in {"attachment", "note"}:
        return False
    fields = bundle.get("fields") or {}
    return not fields.get("parentItem")


def classify_library(
    service: Any,
    *,
    apply: bool = False,
    limit: int | None = None,
    start: int = 0,
    collection_key: str | None = None,
) -> dict[str, Any]:
    tree_result = apply_default_collection_tree(service.local_client, service.writer)
    collections = service.local_client.list_collections()
    collection_paths = build_collection_paths(collections)
    target_keys = resolve_target_keys(tree_result["collection_keys"], collection_paths)
    items: list[dict[str, Any]] = []
    scanned = 0
    candidates = 0
    changed = 0
    updated = 0
    batch_size = 100
    cursor = start

    while True:
        batch = service.local_client.list_top_level_items(start=cursor, limit=batch_size)
        if not batch:
            break
        for item in batch:
            if limit is not None and scanned >= limit:
                break
            raw_collections = list(item["data"].get("collections", []))
            if collection_key and collection_key not in raw_collections:
                continue

            scanned += 1
            bundle = service.local_client.build_bundle(item["key"])
            if not is_collectable_parent_item(bundle):
                continue
            existing_keys = [collection["key"] for collection in bundle.get("collections", [])]
            if not is_pending_candidate(existing_keys, tree_result["collection_keys"]):
                continue

            candidates += 1
            decision = classify_bundle(bundle, target_keys)
            suggested_keys = [target_keys[name] for name in decision.target_names]
            final_keys = merge_collection_keys(existing_keys, suggested_keys, inbox_key=target_keys["inbox"])
            changed_now = final_keys != existing_keys
            if changed_now:
                changed += 1
                if apply:
                    service.update_item(
                        bundle["item_key"],
                        UpdateItemRequest(version=int(bundle["version"]), collections=final_keys),
                    )
                    updated += 1

            items.append(
                {
                    "item_key": bundle["item_key"],
                    "title": bundle.get("title") or "",
                    "existing_collections": [collection_paths.get(key, key) for key in existing_keys],
                    "suggested_collections": [collection_paths.get(key, key) for key in suggested_keys],
                    "final_collections": [collection_paths.get(key, key) for key in final_keys],
                    "reasons": decision.reasons,
                    "changed": changed_now,
                    "applied": apply and changed_now,
                }
            )

        if limit is not None and scanned >= limit:
            break
        if len(batch) < batch_size:
            break
        cursor += batch_size

    return {
        "tree": tree_result,
        "stats": {
            "scanned": scanned,
            "candidates": candidates,
            "changed": changed,
            "updated": updated,
            "apply": apply,
            "start": start,
        },
        "target_keys": target_keys,
        "items": items,
    }

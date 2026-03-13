from __future__ import annotations

from typing import Any

import requests

from .utils import normalize_doi


CSL_TYPE_MAP = {
    "article-journal": "journalArticle",
    "article-magazine": "magazineArticle",
    "article-newspaper": "newspaperArticle",
    "paper-conference": "conferencePaper",
    "chapter": "bookSection",
    "book": "book",
    "report": "report",
    "thesis": "thesis",
    "webpage": "webpage",
}


def _date_from_csl(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    date_parts = value.get("date-parts") or []
    if not date_parts:
        return None
    first = date_parts[0]
    if not first:
        return None
    return "-".join(str(part) for part in first)


def _creators_from_csl(csl: dict[str, Any]) -> list[dict[str, str]]:
    creators: list[dict[str, str]] = []
    for creator in csl.get("author", []) or []:
        if creator.get("family"):
            creators.append(
                {
                    "creatorType": "author",
                    "firstName": creator.get("given", ""),
                    "lastName": creator.get("family", ""),
                }
            )
        elif creator.get("literal"):
            creators.append({"creatorType": "author", "name": creator["literal"]})
    return creators


def doi_to_item_payload(doi: str, csl: dict[str, Any]) -> dict[str, Any]:
    item_type = CSL_TYPE_MAP.get(csl.get("type"), "journalArticle")
    fields: dict[str, Any] = {
        "title": csl.get("title") or "",
        "DOI": doi,
        "url": csl.get("URL") or f"https://doi.org/{doi}",
    }
    container_title = csl.get("container-title")
    if isinstance(container_title, list) and container_title:
        fields["publicationTitle"] = container_title[0]
    elif isinstance(container_title, str):
        fields["publicationTitle"] = container_title
    if csl.get("abstract"):
        fields["abstractNote"] = csl["abstract"]
    if csl.get("volume"):
        fields["volume"] = csl["volume"]
    if csl.get("issue"):
        fields["issue"] = csl["issue"]
    if csl.get("page"):
        fields["pages"] = csl["page"]
    if csl.get("language"):
        fields["language"] = csl["language"]
    if csl.get("publisher"):
        fields["publisher"] = csl["publisher"]
    if csl.get("publisher-place"):
        fields["place"] = csl["publisher-place"]
    issued = _date_from_csl(csl.get("issued")) or _date_from_csl(csl.get("published-print"))
    if issued:
        fields["date"] = issued
    return {
        "item_type": item_type,
        "fields": {key: value for key, value in fields.items() if value not in (None, "")},
        "creators": _creators_from_csl(csl),
        "tags": [],
        "collections": [],
    }


def fetch_doi_metadata(doi: str, user_agent: str) -> dict[str, Any]:
    normalized = normalize_doi(doi)
    if not normalized:
        raise ValueError(f"Invalid DOI: {doi}")
    response = requests.get(
        f"https://doi.org/{normalized}",
        headers={
            "Accept": "application/vnd.citationstyles.csl+json",
            "User-Agent": user_agent,
        },
        timeout=20,
    )
    response.raise_for_status()
    return doi_to_item_payload(normalized, response.json())

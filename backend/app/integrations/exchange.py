from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from app.core.arm112 import FIELD_LABELS

EXCHANGE_VERSION = "1.0"

#: Значения, которые в XML передаются как логические.
_TRUE_VALUES = {"true", "1", "да", "yes"}


def card_to_dict(card: Any, *, with_expected: bool = False) -> dict[str, Any]:
    """Карточка → словарь формата обмена."""
    data: dict[str, Any] = {
        "card_no": card.card_no,
        "title": card.title,
        "origin": card.origin.value,
        "difficulty": card.difficulty.value,
        "fields": dict(card.payload or {}),
        "notification_list": list(card.notification_list or []),
        "caller_profile": dict(card.caller_profile or {}),
    }
    if with_expected:
        data["expected_fields"] = dict(card.expected_payload or {})
    return data


def cards_to_xml(cards: list[Any], *, with_expected: bool = False) -> str:
    root = ET.Element("incident-cards", {"version": EXCHANGE_VERSION, "count": str(len(cards))})
    for card in cards:
        data = card_to_dict(card, with_expected=with_expected)
        card_node = ET.SubElement(
            root,
            "card",
            {
                "no": data["card_no"],
                "origin": data["origin"],
                "difficulty": data["difficulty"],
            },
        )
        ET.SubElement(card_node, "title").text = data["title"]

        fields_node = ET.SubElement(card_node, "fields")
        _write_fields(fields_node, data["fields"])
        if with_expected:
            expected_node = ET.SubElement(card_node, "expected-fields")
            _write_fields(expected_node, data["expected_fields"])

        notification_node = ET.SubElement(card_node, "notification")
        for service in data["notification_list"]:
            ET.SubElement(
                notification_node,
                "service",
                {
                    "code": str(service.get("code", "")),
                    "name": str(service.get("name", "")),
                    "primary": "true" if service.get("is_primary") else "false",
                },
            )

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def cards_from_xml(payload: str) -> list[dict[str, Any]]:
    """XML → список словарей для пакетного импорта карточек."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"Некорректный XML: {exc}") from exc

    if root.tag != "incident-cards":
        raise ValueError("Ожидается корневой элемент <incident-cards>")

    cards: list[dict[str, Any]] = []
    for card_node in root.findall("card"):
        title_node = card_node.find("title")
        cards.append(
            {
                "card_no": card_node.get("no"),
                "title": (title_node.text if title_node is not None else None) or "Импортированная карточка",
                "origin": card_node.get("origin") or "manual",
                "difficulty": card_node.get("difficulty") or "basic",
                "fields": _read_fields(card_node.find("fields")),
                "expected_fields": _read_fields(card_node.find("expected-fields")),
                "extra_services": [
                    service.get("code", "")
                    for service in card_node.findall("notification/service")
                    if service.get("code")
                ],
            }
        )
    if not cards:
        raise ValueError("В файле нет ни одной карточки")
    return cards


# ------------------------------------------------------------------ приватное
def _write_fields(parent: ET.Element, fields: dict[str, Any]) -> None:
    for code, value in fields.items():
        attrs = {"code": code, "label": FIELD_LABELS.get(code, code)}
        if isinstance(value, list | tuple):
            list_node = ET.SubElement(parent, "field", {**attrs, "type": "list"})
            for item in value:
                ET.SubElement(list_node, "item").text = str(item)
        elif isinstance(value, bool):
            node = ET.SubElement(parent, "field", {**attrs, "type": "boolean"})
            node.text = "true" if value else "false"
        else:
            node = ET.SubElement(parent, "field", attrs)
            node.text = "" if value is None else str(value)


def _read_fields(parent: ET.Element | None) -> dict[str, Any]:
    if parent is None:
        return {}
    fields: dict[str, Any] = {}
    for node in parent.findall("field"):
        code = node.get("code")
        if not code:
            continue
        kind = node.get("type")
        if kind == "list":
            fields[code] = [item.text or "" for item in node.findall("item")]
        elif kind == "boolean":
            fields[code] = (node.text or "").strip().lower() in _TRUE_VALUES
        else:
            fields[code] = node.text or ""
    return fields

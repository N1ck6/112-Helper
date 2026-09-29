from __future__ import annotations

import pytest

from app.core import address
from app.integrations.ml_client import StubMLClient

EXPECTED = {
    "address_region": "г. Москва",
    "address_district": "ЦАО",
    "address_area": "Тверской",
    "address_street": "улица Академика Королёва",
    "address_house": "3",
}


@pytest.mark.parametrize(
    ("field", "actual", "expected"),
    [
        ("address_street", "ул. Академика Королёва", "улица Академика Королёва"),
        ("address_street", "Академика Королева", "улица Академика Королёва"),
        ("address_street", "Королёва Академика ул", "улица Академика Королёва"),
        ("address_street", "пр-т Мичуринский", "Мичуринский проспект"),
        ("address_street", "Измайловский б-р", "Измайловский бульвар"),
        ("address_district", "Центральный административный округ", "ЦАО"),
        ("address_district", "Центральный АО", "ЦАО"),
        ("address_district", "Северо-Западный административный округ", "СЗАО"),
        ("address_district", "сзао", "СЗАО"),
        ("address_area", "р-н Щукино", "Щукино"),
        ("address_area", "район Тверской", "Тверской"),
        ("address_region", "Москва", "г. Москва"),
        ("address_house", "д. 3", "3"),
        ("address_house", "дом 3", "3"),
        ("address_house", "12 корп. 1", "12к1"),
        ("address_flat", "кв. 15", "15"),
        ("address_floor", "5 этаж", "5"),
    ],
)
def test_same_address_written_differently(field: str, actual: str, expected: str) -> None:
    assert address.same(field, actual, expected)


@pytest.mark.parametrize(
    ("field", "actual", "expected"),
    [
        ("address_street", "улица Академика Курчатова", "улица Академика Королёва"),
        ("address_street", "Мичуринский переулок", "Мичуринский проспект"),
        ("address_district", "ЮЗАО", "ЦАО"),
        ("address_district", "Южный административный округ", "Юго-Западный административный округ"),
        ("address_house", "д. 13", "3"),
        ("address_house", "", "3"),
    ],
)
def test_different_address_is_not_accepted(field: str, actual: str, expected: str) -> None:
    assert not address.same(field, actual, expected)


async def test_correct_address_in_other_spelling_is_not_an_error() -> None:
    submitted = {
        "address_region": "Москва",
        "address_district": "Центральный административный округ",
        "address_area": "р-н Тверской",
        "address_street": "ул. Академика Королёва",
        "address_house": "д. 3",
    }
    result = await StubMLClient().evaluate_attempt(
        {
            "submitted_payload": submitted,
            "expected_fields": EXPECTED,
            "required_fields": [],
            "actions": [],
            "expected_actions": [],
            "duration_seconds": 10,
            "norm_seconds": 30,
        }
    )
    codes = {error["code"] for error in result["errors"]}
    assert "address_mismatch" not in codes
    assert result["accuracy_score"] == 100.0


async def test_wrong_house_is_still_critical() -> None:
    submitted = dict(EXPECTED, address_house="д. 13")
    result = await StubMLClient().evaluate_attempt(
        {
            "submitted_payload": submitted,
            "expected_fields": EXPECTED,
            "required_fields": [],
            "actions": [],
            "expected_actions": [],
            "duration_seconds": 10,
            "norm_seconds": 30,
        }
    )
    mismatches = [e for e in result["errors"] if e["code"] == "address_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0]["severity"] == "critical"


async def test_selected_services_are_checked() -> None:
    expected = {"notification_services": ["101", "103"]}
    payload = {
        "expected_fields": expected,
        "required_fields": [],
        "actions": [],
        "expected_actions": [],
        "duration_seconds": 10,
        "norm_seconds": 30,
    }
    right = await StubMLClient().evaluate_attempt(
        {**payload, "submitted_payload": {"notification_services": ["Служба 101 (МЧС)", "Служба 103 (СМП)"]}}
    )
    assert not [e for e in right["errors"] if e["code"].startswith("service_")]

    wrong = await StubMLClient().evaluate_attempt(
        {**payload, "submitted_payload": {"notification_services": ["Служба 101 (МЧС)", "Служба 102 (ОМВД)"]}}
    )
    codes = {e["code"]: e for e in wrong["errors"]}
    assert codes["service_missing"]["severity"] == "major"
    assert codes["service_extra"]["severity"] == "minor"


async def test_fields_absent_in_reference_are_not_required() -> None:
    expected = {"address_text": "МКАД между 74 и 68 км", "description": "Горит уличное освещение."}
    result = await StubMLClient().evaluate_attempt(
        {
            "submitted_payload": {
                "address_text": "МКАД 70 км",
                "description": "Горит уличное освещение",
                "incident_class": "Неисправность освещения",
                "survey_signs": ["МКАД"],
            },
            "expected_fields": expected,
            "actions": [],
            "expected_actions": [],
            "duration_seconds": 10,
            "norm_seconds": 30,
        }
    )
    empty = {e["field_code"] for e in result["errors"] if e["code"] == "field_empty"}
    assert "address_house" not in empty
    assert "applicant_name" not in empty

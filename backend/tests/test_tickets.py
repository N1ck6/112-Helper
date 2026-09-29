from __future__ import annotations

import sqlalchemy as sa

from app.db.session import SessionFactory
from app.models.card import IncidentCard
from app.models.enums import CardStatus, ScenarioStatus
from app.models.scenario import Scenario
from app.models.user import User
from app.services.tickets import TicketImportService, address_of, expected_of, load_cases, title_of


def test_all_customer_tickets_are_in_the_data_file() -> None:
    cases = load_cases()
    assert len(cases) == 96
    assert {case.ticket for case in cases} == set(range(1, 33))
    assert all(case.description and case.address for case in cases)


def test_reference_takes_only_what_the_ticket_says() -> None:
    case = next(c for c in load_cases() if c.key == "2-1")
    expected = expected_of(case)
    assert expected["applicant_name"] == "Ким Олег Юрьевич"
    assert expected["aon_phone"] == "+7 (916) 126-34-71"
    assert expected["address_street"] == "ул. Берзарина"
    assert expected["address_house"] == "21"
    assert expected["address_entrance"] == "3"
    assert expected["has_victims"] is False
    assert "Ким" not in expected["description"]
    assert "incident_class" not in expected
    assert "notification_services" not in expected


def test_landmark_address_is_not_forced_into_street_and_house() -> None:
    fields = address_of("МКАД между 74 и 68 км")
    assert "address_house" not in fields
    assert fields["address_text"] == "МКАД между 74 и 68 км"


def test_title_does_not_reveal_incident_type() -> None:
    case = next(c for c in load_cases() if c.key == "32-3")
    assert case.incident_type and case.incident_type not in title_of(case)


async def test_tickets_become_ready_cards_once() -> None:
    cases = load_cases()[:6]
    async with SessionFactory() as session:
        teacher = (await session.execute(sa.select(User).where(User.username == "teacher"))).scalar_one()
        service = TicketImportService(session)
        first = await service.import_all(teacher, cases)
        second = await service.import_all(teacher, cases)
        assert first["imported"] == 6
        assert second == {"imported": 0, "skipped": 6}

        scenarios = (
            await session.execute(sa.select(Scenario).where(Scenario.title.like("Билет 1,%")))
        ).scalars().all()
        assert len(scenarios) == 3
        assert all(s.status is ScenarioStatus.APPROVED for s in scenarios)
        cards = (
            await session.execute(sa.select(IncidentCard).where(IncidentCard.title.like("Билет 1,%")))
        ).scalars().all()
        assert len(cards) == 3
        assert all(card.status is CardStatus.READY and card.expected_payload for card in cards)
        await session.rollback()

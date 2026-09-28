from __future__ import annotations

from app.core.config import settings
from app.models.enums import DifficultyLevel

#: Границы веса для каждого уровня: 1–3 — базовый, 4–7 — средний, 8–10 — сложный.
LEVEL_RANGES: dict[DifficultyLevel, tuple[int, int]] = {
    DifficultyLevel.BASIC: (1, 3),
    DifficultyLevel.MEDIUM: (4, 7),
    DifficultyLevel.HARD: (8, 10),
}

#: Вес по умолчанию для уровня — середина диапазона.
LEVEL_DEFAULT_WEIGHT: dict[DifficultyLevel, int] = {
    DifficultyLevel.BASIC: 2,
    DifficultyLevel.MEDIUM: 5,
    DifficultyLevel.HARD: 9,
}


def clamp_weight(value: object) -> int:
    minimum = settings.DIFFICULTY_WEIGHT_MIN
    maximum = settings.DIFFICULTY_WEIGHT_MAX
    try:
        weight = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return LEVEL_DEFAULT_WEIGHT[DifficultyLevel.BASIC]
    return max(minimum, min(maximum, weight))


def level_of(weight: object) -> DifficultyLevel:
    """Уровень, которому соответствует вес."""
    value = clamp_weight(weight)
    for level, (low, high) in LEVEL_RANGES.items():
        if low <= value <= high:
            return level
    return DifficultyLevel.HARD


def weight_of(level: DifficultyLevel | str | None) -> int:
    """Вес по умолчанию для уровня. Используется при переходе со старых данных."""
    if level is None:
        return LEVEL_DEFAULT_WEIGHT[DifficultyLevel.BASIC]
    try:
        resolved = DifficultyLevel(str(level))
    except ValueError:
        return LEVEL_DEFAULT_WEIGHT[DifficultyLevel.BASIC]
    return LEVEL_DEFAULT_WEIGHT[resolved]


def resolve(
    weight: object = None, level: DifficultyLevel | str | None = None
) -> tuple[int, DifficultyLevel]:
    if weight is not None:
        resolved_weight = clamp_weight(weight)
        return resolved_weight, level_of(resolved_weight)
    if level is not None:
        resolved_weight = weight_of(level)
        return resolved_weight, level_of(resolved_weight)
    default = LEVEL_DEFAULT_WEIGHT[DifficultyLevel.BASIC]
    return default, DifficultyLevel.BASIC


def adapt(current_weight: object, score: float | None) -> tuple[int, str]:
    weight = clamp_weight(current_weight)
    if score is None:
        return weight, "оценки нет — уровень сохранён"

    if score >= settings.ADAPTIVE_RAISE_SCORE:
        new_weight = clamp_weight(weight + settings.ADAPTIVE_STEP)
        if new_weight == weight:
            return weight, f"{score:.0f} баллов, но уровень уже максимальный"
        return new_weight, f"{score:.0f} баллов — сложность повышена до {new_weight}"

    if score <= settings.ADAPTIVE_LOWER_SCORE:
        new_weight = clamp_weight(weight - settings.ADAPTIVE_STEP)
        if new_weight == weight:
            return weight, f"{score:.0f} баллов, но уровень уже минимальный"
        return new_weight, f"{score:.0f} баллов — сложность понижена до {new_weight}"

    return weight, f"{score:.0f} баллов — уровень сохранён"

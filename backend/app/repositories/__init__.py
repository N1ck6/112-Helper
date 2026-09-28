"""Слой доступа к данным."""

from app.repositories.base import BaseRepository
from app.repositories.content import (
    CardRepository,
    CardTemplateRepository,
    CategoryRepository,
    GenerationRequestRepository,
    MaterialRepository,
    ReferenceRepository,
    ScenarioRepository,
    TimeNormRepository,
)
from app.repositories.grading import (
    ErrorRepository,
    EvaluationRepository,
    HistoryRepository,
    MLResultRepository,
    RecommendationRepository,
)
from app.repositories.system import (
    AuditRepository,
    BackupRepository,
    CallRepository,
    CertificateRepository,
    OutboxRepository,
    ReportRepository,
    ServiceStateRepository,
    SettingRepository,
    SystemLogRepository,
    TelephonyConfigRepository,
)
from app.repositories.training import (
    ActionRepository,
    AnswerRepository,
    AssignmentRepository,
    AttemptRepository,
    LessonRepository,
    ParticipantRepository,
)
from app.repositories.users import (
    GroupRepository,
    PermissionRepository,
    RoleRepository,
    UserRepository,
)

__all__ = [
    "BaseRepository",
    "UserRepository", "RoleRepository", "PermissionRepository", "GroupRepository",
    "CategoryRepository", "TimeNormRepository", "ScenarioRepository", "ReferenceRepository",
    "MaterialRepository", "GenerationRequestRepository", "CardTemplateRepository", "CardRepository",
    "AssignmentRepository", "LessonRepository", "ParticipantRepository", "AttemptRepository",
    "ActionRepository", "AnswerRepository",
    "EvaluationRepository", "ErrorRepository", "MLResultRepository", "RecommendationRepository",
    "HistoryRepository",
    "AuditRepository", "SystemLogRepository", "SettingRepository", "ServiceStateRepository",
    "BackupRepository", "ReportRepository", "CertificateRepository", "TelephonyConfigRepository",
    "CallRepository", "OutboxRepository",
]

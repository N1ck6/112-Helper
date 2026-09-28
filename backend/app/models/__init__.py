from app.db.base import Base
from app.models.audit import AuditLog, SystemLog
from app.models.card import CardTemplate, IncidentCard
from app.models.catalog import DutyService, IncidentCategory, IncidentType, TimeNorm
from app.models.grading import (
    ErrorRecord,
    Evaluation,
    MLResult,
    Recommendation,
    TrainingHistory,
)
from app.models.report import Certificate, Report
from app.models.scenario import (
    GenerationRequest,
    Scenario,
    ScenarioReference,
    TrainingMaterial,
)
from app.models.system import (
    BackupRecord,
    CallRecord,
    OutboxMessage,
    ServiceState,
    SystemSetting,
    TelephonyConfig,
)
from app.models.training import (
    Assignment,
    CardAnswer,
    CardAttempt,
    CardProcessing,
    Lesson,
    LessonParticipant,
    ResponseStatusEntry,
    StudentAction,
    Workplace,
)
from app.models.user import (
    Permission,
    Role,
    StudyGroup,
    User,
    group_members,
    role_permissions,
    user_roles,
)

__all__ = [
    "Base",
    # пользователи и доступ
    "User", "Role", "Permission", "StudyGroup",
    "user_roles", "role_permissions", "group_members",
    # классификатор и нормативы
    "IncidentCategory", "IncidentType", "TimeNorm", "DutyService",
    # контент
    "Scenario", "ScenarioReference", "TrainingMaterial", "GenerationRequest",
    "CardTemplate", "IncidentCard",
    # учебный процесс
    "Workplace", "Assignment", "Lesson", "LessonParticipant", "CardAttempt", "StudentAction",
    "CardAnswer", "ResponseStatusEntry", "CardProcessing",
    # оценки и аналитика
    "Evaluation", "ErrorRecord", "MLResult", "Recommendation", "TrainingHistory",
    # отчётность
    "Report", "Certificate",
    # журналы
    "AuditLog", "SystemLog",
    # системные
    "SystemSetting", "ServiceState", "BackupRecord", "TelephonyConfig", "CallRecord",
    "OutboxMessage",
]

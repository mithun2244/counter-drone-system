from typing import Literal

from cuas.schemas.base import Message, SimTime


class OperatorLabel(Message):
    """The operator confirms or dismisses an alert. Answered by an ``EvidenceRecord`` carrying
    the same ``request_id``."""

    alert_id: str
    label: Literal["confirm", "dismiss"]
    t: SimTime
    request_id: str


class ExportRequest(Message):
    """The operator asks for an alert's hand-off package. Answered like ``OperatorLabel``."""

    alert_id: str
    t: SimTime
    request_id: str

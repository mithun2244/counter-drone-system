from cuas.schemas.base import Message


class RejectedMessage(Message):
    """``raw`` is text because a rejected message may not parse at all."""

    reason: str
    raw: str

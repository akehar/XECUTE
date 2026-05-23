from enum import Enum


class Mode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"
    LIVE_WITH_SHADOW = "LIVE_WITH_SHADOW"


class SignalSource(str, Enum):
    DISCORD = "discord"
    SCANNER = "scanner"


class SignalAction(str, Enum):
    BTO = "BTO"
    STC = "STC"
    BTO_ADD = "BTO_ADD"
    STO = "STO"
    BTC = "BTC"


class OptionRight(str, Enum):
    CALL = "C"
    PUT = "P"


class SignalStatus(str, Enum):
    RECEIVED = "received"
    PARSED = "parsed"
    REJECTED_BY_PARSER = "rejected_by_parser"
    REJECTED_BY_ANALYSIS = "rejected_by_analysis"
    REJECTED_BY_RISK = "rejected_by_risk"
    QUEUED = "queued"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class FlowVerdict(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    INCONCLUSIVE = "inconclusive"

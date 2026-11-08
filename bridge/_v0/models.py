# models.py — 数据结构
from dataclasses import dataclass


@dataclass
class Contact:
    user_id: int
    nickname: str = ""
    remark: str = ""
    pinyin: str = ""
    pinyin_initials: str = ""


@dataclass
class Candidate:
    token: str
    user_id: int
    display: str
    score: int
    reason: str

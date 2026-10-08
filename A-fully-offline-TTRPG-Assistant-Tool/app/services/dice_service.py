"""骰子系统（纯标准库，可独立运行）。

支持语法：
    d20                      -> 一颗 20 面骰
    2d6+3                    -> 两颗 d6 加上 +3 调整值
    4d6kh3                   -> 四颗 d6 取高三颗（常用于 D&D 属性生成）
    2d20kl1                  -> 两颗 d20 取低一颗（劣势）
    d20 adv / d20 dis        -> 优势 / 劣势（等价于 2d20kh1 / 2d20kl1）
    3d10-1d4+2               -> 混合表达式（支持 + - 连接）

设计要点：
    - 表达式解析与随机源分离，传入 rng 即可做确定性测试；
    - 期望值对普通骰坛给出解析解，对 kh/kl 使用确定性蒙特卡洛（内置固定种子，结果稳定）；
    - 历史记录常驻内存并可选落盘，便于 UI 与后续统计。
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from typing import Any, Iterable, Literal, Sequence

__all__ = [
    "DiceService",
    "DiceTerm",
    "RollResult",
    "ExpressionError",
]

Advantage = Literal["none", "advantage", "disadvantage"]

TOKEN_RE = re.compile(
    r"(?P<sign>[+-]?)"
    r"(?:(?P<count>\d*)d(?P<sides>\d+)(?P<keep>k[hl]\d+)?"
    r"|(?P<flat>\d+))",
    re.IGNORECASE,
)
ADV_KEYWORDS = {
    "advantage": "advantage", "adv": "advantage", "优势": "advantage",
    "disadvantage": "disadvantage", "dis": "disadvantage", "劣势": "disadvantage",
}
MAX_DICE_PER_GROUP = 100
MAX_GROUPS = 32


class ExpressionError(ValueError):
    """骰子表达式非法。"""


@dataclass
class DiceTerm:
    """一次掷骰中的「一个骰组」。"""

    count: int
    sides: int
    keep_mode: str | None = None   # 'kh' | 'kl' | None
    keep_n: int | None = None
    sign: int = 1
    rolls: list[int] = field(default_factory=list)
    kept: list[int] = field(default_factory=list)
    dropped: list[int] = field(default_factory=list)

    @property
    def subtotal(self) -> int:
        return self.sign * sum(self.kept)

    @property
    def expected(self) -> float:
        return self.sign * expected_group(self.count, self.sides, self.keep_mode, self.keep_n)

    def to_dict(self) -> dict:
        return {
            "notation": f"{self.count}d{self.sides}" + (f"{self.keep_mode}{self.keep_n}" if self.keep_mode else ""),
            "count": self.count,
            "sides": self.sides,
            "sign": self.sign,
            "rolls": self.rolls,
            "kept": self.kept,
            "dropped": self.dropped,
            "subtotal": self.subtotal,
            "expected": round(self.expected, 3),
        }


@dataclass
class RollResult:
    """一次完整投掷的结果快照，可直接 JSON 序列化写进历史。"""

    expression: str
    total: int
    terms: list[DiceTerm]
    modifier: int
    advantage: Advantage
    expected: float
    critical: str | None = None      # 'crit' | 'fumble' | None
    label: str = ""
    reason: str = ""
    seed: int | None = None
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "expression": self.expression,
            "notation": self.notation,
            "label": self.label,
            "reason": self.reason,
            "total": self.total,
            "modifier": self.modifier,
            "advantage": self.advantage,
            "expected": round(self.expected, 3),
            "critical": self.critical,
            "terms": [t.to_dict() for t in self.terms],
            "timestamp": self.timestamp,
            "seed": self.seed,
        }

    @property
    def notation(self) -> str:
        parts = [f"{'-' if t.sign < 0 else '+'}{t.count}d{t.sides}"
                 + (f"{t.keep_mode}{t.keep_n}" if t.keep_mode else "")
                 for t in self.terms]
        mod = f"{self.modifier:+d}" if self.modifier else ""
        return " ".join(parts).lstrip("+") + mod

    def __str__(self) -> str:  # pragma: no cover - 调试辅助
        detail = " ".join(f"[{','.join(map(str, t.rolls))}]" for t in self.terms)
        return f"{self.expression} => {self.total}  {detail} mod={self.modifier:+d}"


# ---------------------------------------------------------------- 期望值计算
def expected_group(count: int, sides: int, keep_mode: str | None, keep_n: int | None) -> float:
    if not keep_mode or not keep_n or keep_n >= count:
        return count * (sides + 1) / 2
    if count == 2 and keep_n == 1:
        n = sides
        if keep_mode == "kh":
            return sum(k * (2 * k - 1) for k in range(1, n + 1)) / (n * n)
        return sum(k * (2 * (n - k) + 1) for k in range(1, n + 1)) / (n * n)
    return _expected_keep_sim(count, sides, keep_n, keep_mode == "kh")


@lru_cache(maxsize=4096)
def _expected_keep_sim(count: int, sides: int, keep_n: int, highest: bool, samples: int = 40000) -> float:
    """kh/kl 的期望值使用固定种子的蒙特卡洛估计 —— 同一参数永远返回同一数值。"""
    rng = random.Random(20240921)
    acc = 0
    for _ in range(samples):
        rs = sorted((rng.randint(1, sides) for _ in range(count)), reverse=highest)
        acc += sum(rs[:keep_n])
    return acc / samples


# ---------------------------------------------------------------- 主体服务
class DiceService:
    """掷骰、期望值、历史记录。

    零 IO 依赖：外部通过 ``history_file`` 或注入 sink 决定是否持久化。
    """

    SUPPORTED_SIDES = (4, 6, 8, 10, 12, 20, 100)

    def __init__(self, *, seed: int | None = None, history_limit: int = 500,
                 event_bus=None, persist_path=None) -> None:
        self._default_seed = seed
        self.history_limit = history_limit
        self.bus = event_bus
        self.persist_path = persist_path
        self._history: list[RollResult] = []

    # ------------------------------------------------------------ 表达式解析
    def parse(self, expression: str, advantage: Advantage | None = None) -> list[tuple]:
        """把表达式解析为 [(sign, count, sides, keep_mode, keep_n) 或 ('flat', sign, value)]。"""
        raw = expression.strip().lower()
        for kw, mode in ADV_KEYWORDS.items():
            if kw in raw:
                raw = raw.replace(kw, "")
                advantage = advantage or mode  # type: ignore[assignment]

        cleaned = re.sub(r"\s+", "", raw)
        if not cleaned:
            raise ExpressionError("骰子表达式为空")

        parsed: list[tuple] = []
        pos = 0
        groups = 0
        while pos < len(cleaned):
            m = TOKEN_RE.match(cleaned, pos)
            if not m or m.end() == pos:
                raise ExpressionError(f"无法解析的片段：{cleaned[pos:]!r}")
            sign = -1 if m.group("sign") == "-" else 1
            if m.group("flat") is not None:
                parsed.append(("flat", sign, int(m.group("flat"))))
            else:
                count = int(m.group("count") or 1)
                sides = int(m.group("sides"))
                if sides < 2:
                    raise ExpressionError(f"骰子面数必须 >= 2，收到 d{sides}")
                if count < 1 or count > MAX_DICE_PER_GROUP:
                    raise ExpressionError(f"骰子数量需在 1~{MAX_DICE_PER_GROUP} 之间，收到 {count}")
                keep_mode = keep_n = None
                if m.group("keep"):
                    keep_mode = m.group("keep")[:2].lower()
                    keep_n = int(m.group("keep")[2:])
                    if keep_n < 1 or keep_n > count:
                        raise ExpressionError(f"保留数量需在 1~{count} 之间，收到 {keep_n}")
                groups += 1
                if groups > MAX_GROUPS:
                    raise ExpressionError(f"表达式最多包含 {MAX_GROUPS} 个骰组")
                parsed.append(("dice", sign, count, sides, keep_mode, keep_n))
            pos = m.end()

        if advantage in ("advantage", "disadvantage") and parsed:
            parsed.append(("option", advantage))
        return parsed

    # ------------------------------------------------------------ 投掷
    def roll(self, expression: str, *, advantage: Advantage | None = None,
             seed: int | None = None, label: str = "", reason: str = "") -> RollResult:
        parsed = self.parse(expression, advantage)
        rng = random.Random(seed if seed is not None else
                            self._default_seed if self._default_seed is not None else None)
        used_seed = seed if seed is not None else self._default_seed

        advantage_mode: Advantage = "none"
        for item in parsed:
            if item[0] == "option":
                advantage_mode = item[1]

        terms: list[DiceTerm] = []
        modifier = 0
        for item in parsed:
            if item[0] == "flat":
                modifier += item[1] * item[2]
            elif item[0] == "dice":
                _, sign, count, sides, keep_mode, keep_n = item
                if advantage_mode != "none" and not terms and sides == 20 and count == 1:
                    count, keep_mode, keep_n = 2, ("kh" if advantage_mode == "advantage" else "kl"), 1
                elif advantage_mode != "none" and not terms:
                    keep_mode, keep_n = ("kh" if advantage_mode == "advantage" else "kl"), 1
                    count = count * 2
                term = DiceTerm(count=count, sides=sides, keep_mode=keep_mode,
                                keep_n=keep_n, sign=sign)
                self._cast(term, rng)
                terms.append(term)

        total = sum(t.subtotal for t in terms) + modifier
        expected = sum(t.expected for t in terms) + modifier
        critical = self._detect_critical([t for t in terms if t.sides == 20])

        result = RollResult(
            expression=expression.strip(),
            total=total,
            terms=terms,
            modifier=modifier,
            advantage=advantage_mode,
            expected=expected,
            critical=critical,
            label=label,
            reason=reason,
            seed=used_seed,
            timestamp=_now(),
        )
        self._record(result)
        return result

    @staticmethod
    def _cast(term: DiceTerm, rng: random.Random) -> None:
        term.rolls = [rng.randint(1, term.sides) for _ in range(term.count)]
        if term.keep_mode and term.keep_n and term.keep_n < term.count:
            order = sorted(term.rolls, reverse=(term.keep_mode == "kh"))
            term.kept = order[: term.keep_n]
            rest = list(term.rolls)
            for v in term.kept:
                rest.remove(v)
            term.dropped = rest
        else:
            term.kept = list(term.rolls)
            term.dropped = []

    @staticmethod
    def _detect_critical(d20_terms: Sequence[DiceTerm]) -> str | None:
        kept = [v for t in d20_terms for v in t.kept]
        if not kept:
            return None
        if all(v == 20 for v in kept) and len(kept) >= 1 and len(d20_terms) == 1:
            return "crit"
        if all(v == 1 for v in kept) and len(d20_terms) == 1:
            return "fumble"
        return None

    # ------------------------------------------------------------ 便捷投掷
    def roll_simple(self, sides: int, count: int = 1, modifier: int = 0, **kw) -> RollResult:
        sides = int(sides)
        if sides not in self.SUPPORTED_SIDES:
            raise ExpressionError(f"不支持的面数 d{sides}，可选：{self.SUPPORTED_SIDES}")
        expr = f"{count}d{sides}" + (f"{modifier:+d}" if modifier else "")
        return self.roll(expr, **kw)

    def expected_of(self, expression: str, advantage: Advantage | None = None) -> float:
        parsed = self.parse(expression, advantage)
        adv = next((i[1] for i in parsed if i[0] == "option"), "none")
        total = 0.0
        for item in parsed:
            if item[0] == "flat":
                total += item[1] * item[2]
            elif item[0] == "dice":
                _, sign, count, sides, keep_mode, keep_n = item
                if adv != "none":
                    count = max(count * 2, 2)
                    keep_mode = "kh" if adv == "advantage" else "kl"
                    keep_n = keep_n or 1
                    adv = "none"
                total += sign * expected_group(count, sides, keep_mode, keep_n)
        return total

    def probability_at_least(self, expression: str, dc: int) -> float:
        """返回总值 >= dc 的概率。用 DP 卷积精确求解，规模过大时给出估算提示。"""
        parsed = self.parse(expression)
        dist = {0: 1.0}
        for item in parsed:
            if item[0] == "flat":
                dist = {k + item[1] * item[2]: v for k, v in dist.items()}
            elif item[0] == "dice":
                _, sign, count, sides, keep_mode, keep_n = item
                single = {i: 1.0 / sides for i in range(1, sides + 1)}
                group = {0: 1.0}
                for _ in range(count):
                    group = _convolve(group, single)
                if keep_mode and keep_n and keep_n < count:
                    group = _keep_transform(count, sides, keep_mode, keep_n)
                group = {sign * k: v for k, v in group.items()}
                dist = _convolve(dist, group)
                if len(dist) > 200000:
                    raise ExpressionError("分布规模过大，无法精确计算概率")
        return round(sum(v for k, v in dist.items() if k >= dc) * 100, 2)

    # ------------------------------------------------------------ 历史记录
    def _record(self, result: RollResult) -> None:
        self._history.append(result)
        if len(self._history) > self.history_limit:
            self._history = self._history[-self.history_limit:]
        if self.persist_path:
            try:
                from pathlib import Path
                import json
                p = Path(self.persist_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
            except Exception:
                pass
        if self.bus:
            self.bus.emit("dice/rolled", result.to_dict())

    def history(self, limit: int | None = None) -> list[dict]:
        items = self._history if limit is None else self._history[-limit:]
        return [r.to_dict() for r in items]

    def clear_history(self) -> None:
        self._history.clear()
        if self.bus:
            self.bus.emit("dice/cleared", {})

    def stats(self) -> dict:
        if not self._history:
            return {"count": 0}
        totals = [r.total for r in self._history]
        return {
            "count": len(totals),
            "avg": round(sum(totals) / len(totals), 2),
            "max": max(totals),
            "min": min(totals),
            "crit_count": sum(1 for r in self._history if r.critical == "crit"),
        }


# ---------------------------------------------------------------- 分布工具
def _convolve(a: dict[int, float], b: dict[int, float]) -> dict[int, float]:
    out: dict[int, float] = {}
    for ka, va in a.items():
        for kb, vb in b.items():
            out[ka + kb] = out.get(ka + kb, 0.0) + va * vb
    return out


@lru_cache(maxsize=512)
def _keep_transform(count: int, sides: int, keep_mode: str, keep_n: int) -> dict[int, float]:
    """kh/kl 组的分布：穷举所有组合（组合数受 MAX_DICE_PER_GROUP 保护）。"""
    from itertools import product
    out: dict[int, float] = {}
    total = sides ** count
    for combo in product(range(1, sides + 1), repeat=count):
        ordered = sorted(combo, reverse=(keep_mode == "kh"))
        out[sum(ordered[:keep_n])] = out.get(sum(ordered[:keep_n]), 0.0) + 1
    return {k: v / total for k, v in out.items()}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 命令行 demo
if __name__ == "__main__":  # python app/services/dice_service.py
    import json
    import sys

    svc = DiceService()
    exprs = sys.argv[1:] or ["d20", "2d6+3", "1d20+5", "4d6kh3", "d20 adv", "2d20kl1", "3d10-1d4+2"]
    for e in exprs:
        r = svc.roll(e, reason="demo")
        print(f"{e:<14} 合计={r.total:<4} 明细={r.notation:<20} 期望={r.expected:.2f} "
              f"{'[暴击]' if r.critical == 'crit' else ''}")
    print("\n历史记录（JSON 片段）:")
    print(json.dumps(svc.history(3), ensure_ascii=False, indent=2))
    print("\nP(d20+5 >= 15) =", svc.probability_at_least("d20+5", 15), "%")

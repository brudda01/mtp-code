"""Checked experiment recipes. Unknown or unimplemented settings are errors.

Rates and dividend parameters are per round. ``iid_permanent`` is the simple
research foundation; ``legacy_ar1`` retains the original demonstration process.
No configuration expression is evaluated as Python.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from pathlib import Path
import re
from urllib.parse import urlparse
import warnings

import yaml


class ConfigError(ValueError):
    """Invalid or unsupported experiment configuration."""


@dataclass(frozen=True)
class CashDistribution:
    mu: float
    sigma: float

    def sample(self, rng):
        value = float(rng.lognormal(self.mu, self.sigma))
        if not math.isfinite(value) or value <= 0:
            raise ConfigError("cash_dist produced a non-finite or zero endowment")
        return value

    def expression(self):
        return f"lognormal({self.mu}, {self.sigma})"


@dataclass(frozen=True)
class TimeConfig:
    round_unit: str = "trading_session"
    periods_per_year: int | None = 252


@dataclass(frozen=True)
class MarketConfig:
    mechanism: str = "call_auction"
    tick: float = 0.1
    price_band: float = 0.2
    transaction_tax: float = 0.0


@dataclass(frozen=True)
class DividendConfig:
    mean: float = 0.02
    relative_noise: float | None = 0.2
    rho: float | None = None
    sigma: float | None = None


@dataclass(frozen=True)
class AssetConfig:
    model: str = "iid_permanent"
    ticker: str = "KGP"
    initial_price: float = 100.0
    risk_free: float = 0.0002
    dividend: DividendConfig = field(default_factory=DividendConfig)


@dataclass(frozen=True)
class ObservationConfig:
    price_history_len: int = 20
    bbs_sample: int = 0


@dataclass(frozen=True)
class ExecutionConfig:
    max_workers: int = 8


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "mock"
    model: str = "mock"
    temperature: float = 0.7
    reflect_every: int = 0
    max_tokens: int = 300
    base_url: str | None = None
    condition: str = "A"
    memory_window: int = 10
    timeout_seconds: float = 30.0
    input_usd_per_million: float | None = None
    output_usd_per_million: float | None = None
    reasoning_effort: str | None = None
    send_temperature: bool = True
    transport_retries: int = 0
    retry_http_503: bool = False


@dataclass(frozen=True)
class LLMLimits:
    max_requests: int = 10000
    max_reserved_tokens: int = 20000000
    max_cost_usd: float | None = None
    requests_per_minute: int | None = None
    input_tokens_per_minute: int | None = None
    stop_on_api_error: bool = False


@dataclass(frozen=True)
class AgentGroupConfig:
    type: str
    count: int = 1
    cash: float = 10000.0
    shares: int = 100
    initial_cost: float | None = None
    cash_dist: CashDistribution | None = None
    params: dict = field(default_factory=dict)
    llm: LLMConfig | None = None
    persona_source: str | None = None


@dataclass(frozen=True)
class NewsEffect:
    dbar_mult: float = 1.0
    duration: int | None = None


@dataclass(frozen=True)
class NewsEvent:
    round: int
    headline: str | None = None
    effect: NewsEffect | None = None
    announce: bool = True


@dataclass(frozen=True)
class RunConfig:
    agents: list[AgentGroupConfig]
    name: str = "run"
    seed: int = 42
    rounds: int = 100
    market: MarketConfig = field(default_factory=MarketConfig)
    asset: AssetConfig = field(default_factory=AssetConfig)
    time: TimeConfig = field(default_factory=TimeConfig)
    observation: ObservationConfig = field(default_factory=ObservationConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    news: list[NewsEvent] = field(default_factory=list)
    reveal_fundamental: bool = False
    llm_limits: LLMLimits = field(default_factory=LLMLimits)

    def to_dict(self):
        data = asdict(self)
        for group, raw in zip(self.agents, data["agents"]):
            if group.cash_dist is not None:
                raw["cash_dist"] = group.cash_dist.expression()
                raw.pop("cash")

        def compact(value):
            if isinstance(value, dict):
                return {k: compact(v) for k, v in value.items() if v is not None}
            if isinstance(value, list):
                return [compact(v) for v in value]
            return value

        result = compact(data)
        result["time"]["periods_per_year"] = self.time.periods_per_year
        return result


def _object(value, path, allowed):
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be a mapping")
    unknown = set(value) - set(allowed)
    if unknown:
        raise ConfigError(f"{path}: unsupported setting(s): {', '.join(sorted(map(str, unknown)))}")
    return value


def _number(value, path, *, minimum=None, maximum=None, strict_min=False,
            strict_max=False):
    if type(value) not in (int, float):
        raise ConfigError(f"{path} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ConfigError(f"{path} is too large") from exc
    if not math.isfinite(number):
        raise ConfigError(f"{path} must be finite")
    if minimum is not None and (number <= minimum if strict_min else number < minimum):
        raise ConfigError(f"{path} must be {'greater than' if strict_min else 'at least'} {minimum}")
    if maximum is not None and (number >= maximum if strict_max else number > maximum):
        raise ConfigError(f"{path} must be {'less than' if strict_max else 'at most'} {maximum}")
    return number


def _integer(value, path, minimum=0):
    if type(value) is not int or value < minimum:
        raise ConfigError(f"{path} must be an integer >= {minimum}")
    return value


def _text(value, path):
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path} must be a nonempty string")
    return value


def _choice(value, path, choices):
    if value not in choices:
        raise ConfigError(f"{path} must be one of {', '.join(choices)}")
    return value


def _llm(data, path):
    raw = _object(data, path, LLMConfig.__dataclass_fields__)
    provider = _choice(raw.get("provider", "mock"), path + ".provider",
                       ("mock", "openai_compatible"))
    model = _text(raw.get("model", "mock" if provider == "mock" else None), path + ".model")
    base_url = raw.get("base_url")
    if base_url is not None:
        parsed = urlparse(_text(base_url, path + ".base_url"))
        if (parsed.scheme not in ("http", "https") or not parsed.netloc or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ConfigError(path + ".base_url must be HTTP(S), without credentials/query/fragment")
    condition = _choice(raw.get("condition", "C" if raw.get("reflect_every", 0) else "A"),
                        path + ".condition", ("A", "B", "C"))
    reflect = _integer(raw.get("reflect_every", 10 if condition == "C" else 0), path + ".reflect_every")
    window = _integer(raw.get("memory_window", 10), path + ".memory_window", 1)
    if condition != "C" and reflect:
        raise ConfigError(path + ": reflection requires condition C")
    if condition == "C" and (reflect == 0 or window < reflect):
        raise ConfigError(path + ": C requires 0 < reflect_every <= memory_window")
    prices = [None if raw.get(key) is None else _number(raw[key], path + "." + key, minimum=0)
              for key in ("input_usd_per_million", "output_usd_per_million")]
    if provider != "mock" and None in prices:
        raise ConfigError(path + ": live providers require explicit input/output prices (0 for a free local endpoint)")
    if provider == "mock" and any(p not in (None, 0.0) for p in prices):
        raise ConfigError(path + ": mock clients have zero monetary cost")
    send_temperature = raw.get("send_temperature", True)
    if type(send_temperature) is not bool:
        raise ConfigError(path + ".send_temperature must be true or false")
    transport_retries = _integer(raw.get("transport_retries", 0), path + ".transport_retries")
    if transport_retries > 1:
        raise ConfigError(path + ".transport_retries supports only 0 or 1")
    retry_http_503 = raw.get("retry_http_503", False)
    if type(retry_http_503) is not bool or (retry_http_503 and transport_retries != 1):
        raise ConfigError(path + ".retry_http_503 must be boolean and requires transport_retries: 1")
    return LLMConfig(
        provider=provider, model=model,
        temperature=_number(raw.get("temperature", 0.7), path + ".temperature", minimum=0, maximum=2),
        reflect_every=reflect, max_tokens=_integer(raw.get("max_tokens", 300), path + ".max_tokens", 1),
        base_url=base_url, condition=condition, memory_window=window,
        timeout_seconds=_number(raw.get("timeout_seconds", 30), path + ".timeout_seconds", minimum=0, strict_min=True),
        input_usd_per_million=prices[0], output_usd_per_million=prices[1],
        reasoning_effort=None if raw.get("reasoning_effort") is None else _choice(
            raw["reasoning_effort"], path + ".reasoning_effort", ("none", "minimal", "low", "medium", "high")),
        send_temperature=send_temperature, transport_retries=transport_retries, retry_http_503=retry_http_503)


def _distribution(value, path):
    if not isinstance(value, str):
        raise ConfigError(path + " must be lognormal(mu, sigma)")
    match = re.fullmatch(r"lognormal\(\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*\)", value)
    if not match:
        raise ConfigError(path + " must be lognormal(mu, sigma)")
    try:
        mu, sigma = map(float, match.groups())
    except ValueError as exc:
        raise ConfigError(path + " contains an invalid number") from exc
    return CashDistribution(_number(mu, path + ".mu"),
                            _number(sigma, path + ".sigma", minimum=0))


PARAMETERS = {
    "zero_intelligence": {"activity_prob"},
    "fundamentalist": {"delta", "aggressiveness", "dividend_window"},
    "momentum": {"window", "aggressiveness"},
    "market_maker": {"spread", "inventory_limit", "quote_size", "inventory_target", "inventory_skew"},
    "llm": set(),
}


def _group(data, index, history_len):
    path = f"agents[{index}]"
    raw = _object(data, path, AgentGroupConfig.__dataclass_fields__)
    kind = _choice(raw.get("type"), path + ".type", tuple(PARAMETERS))
    params = dict(_object(raw.get("params", {}), path + ".params", PARAMETERS[kind]))
    for key, value in params.items():
        location = path + ".params." + key
        if key in ("window", "dividend_window", "quote_size", "inventory_limit"):
            params[key] = _integer(value, location, 1)
        elif key in ("spread", "delta", "inventory_skew"):
            params[key] = _number(value, location, minimum=0, maximum=1,
                                  strict_min=key == "spread", strict_max=True)
        elif key == "activity_prob":
            params[key] = _number(value, location, minimum=0, maximum=1)
        elif key == "inventory_target":
            params[key] = _integer(value, location)
        else:
            params[key] = _number(value, location, minimum=0)
    if kind == "momentum" and params.get("window", 5) >= history_len:
        raise ConfigError(path + ": momentum window must be less than observation.price_history_len")
    shares = _integer(raw.get("shares", 100), path + ".shares")
    if kind == "market_maker":
        limit = params.get("inventory_limit", 200)
        if shares > limit or params.get("inventory_target", limit // 2) > limit:
            raise ConfigError(path + ": market-maker shares/target exceed inventory_limit")
    cash_dist = None
    if "cash_dist" in raw:
        if "cash" in raw:
            raise ConfigError(path + ": specify either cash or cash_dist")
        cash_dist = _distribution(raw["cash_dist"], path + ".cash_dist")
    if kind != "llm" and ("llm" in raw or "persona_source" in raw):
        raise ConfigError(path + ": llm/persona_source settings require type: llm")
    persona_source = None
    if kind == "llm":
        persona_source = _choice(raw.get("persona_source", "library"), path + ".persona_source", ("library",))
    return AgentGroupConfig(
        kind, _integer(raw.get("count", 1), path + ".count"),
        _number(raw.get("cash", 10000), path + ".cash", minimum=0), shares,
        None if raw.get("initial_cost") is None else _number(raw["initial_cost"], path + ".initial_cost", minimum=0),
        cash_dist, params, _llm(raw.get("llm", {}), path + ".llm") if kind == "llm" else None,
        persona_source)


def parse_config(data):
    raw = _object(data, "config", RunConfig.__dataclass_fields__)
    name = _text(raw.get("name", "run"), "name")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name):
        raise ConfigError("name must be a short filename-safe label")
    seed = _integer(raw.get("seed", 42), "seed")
    rounds = _integer(raw.get("rounds", 100), "rounds", 1)
    m = _object(raw.get("market", {}), "market", MarketConfig.__dataclass_fields__)
    market = MarketConfig(
        _choice(m.get("mechanism", "call_auction"), "market.mechanism", ("call_auction",)),
        _number(m.get("tick", 0.1), "market.tick", minimum=0, strict_min=True),
        _number(m.get("price_band", 0.2), "market.price_band", minimum=0, maximum=1, strict_max=True),
        _number(m.get("transaction_tax", 0), "market.transaction_tax", minimum=0, maximum=1, strict_max=True))
    a = _object(raw.get("asset", {}), "asset", AssetConfig.__dataclass_fields__)
    d = a.get("dividend", {})
    if not isinstance(d, dict):
        raise ConfigError("asset.dividend must be a mapping")
    inferred = "legacy_ar1" if set(d) & {"rho", "sigma"} else "iid_permanent"
    model = _choice(a.get("model", inferred), "asset.model", ("iid_permanent", "legacy_ar1"))
    if "model" not in a and inferred == "legacy_ar1":
        warnings.warn("asset.model omitted: interpreting rho/sigma as legacy_ar1", UserWarning)
    if model == "iid_permanent":
        d = _object(d, "asset.dividend", ("mean", "relative_noise"))
        dividend = DividendConfig(
            _number(d.get("mean", 0.02), "asset.dividend.mean", minimum=0, strict_min=True),
            _number(d.get("relative_noise", 0.2), "asset.dividend.relative_noise", minimum=0, maximum=1))
    else:
        d = _object(d, "asset.dividend", ("mean", "rho", "sigma"))
        dividend = DividendConfig(
            _number(d.get("mean", 1), "asset.dividend.mean", minimum=0, strict_min=True), None,
            _number(d.get("rho", 0.6), "asset.dividend.rho", minimum=-1, maximum=1, strict_min=True, strict_max=True),
            _number(d.get("sigma", 0.3), "asset.dividend.sigma", minimum=0))
    asset = AssetConfig(
        model, _text(a.get("ticker", "KGP"), "asset.ticker"),
        _number(a.get("initial_price", 100), "asset.initial_price", minimum=0, strict_min=True),
        _number(a.get("risk_free", 0.01 if model == "legacy_ar1" else 0.0002),
                "asset.risk_free", minimum=0, strict_min=True), dividend)
    if asset.initial_price < market.tick or not math.isclose(
            asset.initial_price / market.tick, round(asset.initial_price / market.tick), rel_tol=0, abs_tol=1e-9):
        raise ConfigError("asset.initial_price must be a positive multiple of market.tick")
    if not math.isfinite(dividend.mean / asset.risk_free):
        raise ConfigError("dividend mean / risk_free must be finite")
    t = _object(raw.get("time", {}), "time", TimeConfig.__dataclass_fields__)
    time_cfg = TimeConfig(
        _text(t.get("round_unit", "laboratory_period" if model == "legacy_ar1" else "trading_session"), "time.round_unit"),
        None if t.get("periods_per_year", None if model == "legacy_ar1" else 252) is None
        else _integer(t.get("periods_per_year", 252), "time.periods_per_year", 1))
    o = _object(raw.get("observation", {}), "observation", ObservationConfig.__dataclass_fields__)
    observation = ObservationConfig(_integer(o.get("price_history_len", 20), "observation.price_history_len", 1))
    if o.get("bbs_sample", 0) != 0 or type(o.get("bbs_sample", 0)) is not int:
        raise ConfigError("observation.bbs_sample: only 0 is implemented")
    execution = _object(raw.get("execution", {}), "execution", ExecutionConfig.__dataclass_fields__)
    execution = ExecutionConfig(_integer(execution.get("max_workers", 8), "execution.max_workers", 1))
    if not isinstance(raw.get("agents"), list):
        raise ConfigError("agents must be a list")
    groups = [_group(g, i, observation.price_history_len) for i, g in enumerate(raw["agents"])]
    if sum(g.count for g in groups) == 0:
        raise ConfigError("agents must include at least one active trader")
    if not isinstance(raw.get("news", []), list):
        raise ConfigError("news must be a list")
    news = []
    for i, item in enumerate(raw.get("news", [])):
        path = f"news[{i}]"
        event = _object(item, path, NewsEvent.__dataclass_fields__)
        rnd = _integer(event.get("round"), path + ".round", 1)
        if rnd > rounds:
            raise ConfigError(path + ".round exceeds the run length")
        effect = None
        if event.get("effect") is not None:
            e = _object(event["effect"], path + ".effect", NewsEffect.__dataclass_fields__)
            duration = None if e.get("duration") is None else _integer(e["duration"], path + ".effect.duration", 1)
            if model == "iid_permanent" and duration is not None:
                raise ConfigError(path + ": iid_permanent supports permanent shocks only; omit duration")
            effect = NewsEffect(_number(e.get("dbar_mult", 1), path + ".effect.dbar_mult", minimum=0, strict_min=True), duration)
        announce = event.get("announce", True)
        if type(announce) is not bool:
            raise ConfigError(path + ".announce must be true or false")
        headline = event.get("headline")
        if announce or headline is not None:
            headline = _text(headline, path + ".headline")
        news.append(NewsEvent(rnd, headline, effect, announce))
    reveal = raw.get("reveal_fundamental", False)
    if type(reveal) is not bool:
        raise ConfigError("reveal_fundamental must be true or false")
    limits = _object(raw.get("llm_limits", {}), "llm_limits", LLMLimits.__dataclass_fields__)
    stop_on_api_error = limits.get("stop_on_api_error", False)
    if type(stop_on_api_error) is not bool:
        raise ConfigError("llm_limits.stop_on_api_error must be true or false")
    limits = LLMLimits(
        _integer(limits.get("max_requests", 10000), "llm_limits.max_requests"),
        _integer(limits.get("max_reserved_tokens", 20000000), "llm_limits.max_reserved_tokens"),
        None if limits.get("max_cost_usd") is None else _number(limits["max_cost_usd"], "llm_limits.max_cost_usd", minimum=0),
        None if limits.get("requests_per_minute") is None else _integer(limits["requests_per_minute"], "llm_limits.requests_per_minute", 1),
        None if limits.get("input_tokens_per_minute") is None else _integer(limits["input_tokens_per_minute"], "llm_limits.input_tokens_per_minute", 1),
        stop_on_api_error)
    if any(g.llm and g.llm.provider != "mock" for g in groups) and limits.max_cost_usd is None:
        raise ConfigError("live providers require llm_limits.max_cost_usd")
    return RunConfig(groups, name, seed, rounds, market, asset, time_cfg, observation,
                     execution, news, reveal, limits)


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ConfigError("configuration keys must be strings")
        if key in result:
            raise ConfigError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_config(path):
    try:
        with Path(path).open(encoding="utf-8") as source:
            return parse_config(yaml.load(source, Loader=_UniqueLoader))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc

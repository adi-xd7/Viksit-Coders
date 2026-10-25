"""FR2.2 / FR3.2: an advocate's estimate is its range per country and sector, so code must not lose
it for a harmless notation (a fall written as negative numbers, bounds in reverse order), and an
estimate that really does not reproduce gets one repair instead of being dropped silently.

The model is scripted (tests/fake_llm.py): isolated tests only."""

from __future__ import annotations

import pytest

from conftest import SYNTH_PACK
from fake_llm import ScriptedBackend, default_handlers
from ragnarok.agents import schemas as S
from ragnarok.agents.estimates import normalise_bounds
from ragnarok.config import Settings
from ragnarok.ingest.pipeline import ingest_pack
from ragnarok.retrieval.service import RetrievalService
from ragnarok.store.db import Store
from ragnarok.trial.machine import Trial
from test_trial import AS_OF, QUESTION


@pytest.fixture()
def settings(tmp_path):
    return Settings(_env_file=None, cases_dir=tmp_path / "cases", gemini_api_key="test-key")


@pytest.fixture()
def world(tmp_path, settings, embedder):
    store = Store(tmp_path / "t.db")
    ingest_pack(SYNTH_PACK, store, settings)
    yield store, RetrievalService(store, settings, embedder)
    store.close()


def run(world, settings, overrides):
    store, svc = world
    b = ScriptedBackend(overrides)
    t = Trial(QUESTION, AS_OF, store, settings, backend=b, service=svc)
    return t, t.run(), b


def test_normalise_bounds():
    assert normalise_bounds(-156.5, -216.2)[:2] == (156.5, 216.2)
    assert normalise_bounds(-216.2, -156.5)[:2] == (156.5, 216.2)
    assert normalise_bounds(216.2, 156.5)[:2] == (156.5, 216.2)
    assert normalise_bounds(10.0, 20.0) == (10.0, 20.0, None)
    assert normalise_bounds(-5.0, 20.0) == (-5.0, 20.0, None)  # a range across zero is meaningful: left as is
    assert normalise_bounds(None, 3.0) == (None, 3.0, None)


def brief_with(transform):
    base = default_handlers()[("thor", "AdvocateBrief")]

    def h(user, n):
        b = base(user, n)
        claims = list(b.claims)
        e = claims[1].estimate
        lo, hi = transform(e.low, e.high, n)
        claims[1] = claims[1].model_copy(update={"estimate": e.model_copy(update={"low": lo, "high": hi})})
        return S.AdvocateBrief(claims=claims)
    return h


@pytest.mark.parametrize("transform", [lambda lo, hi, n: (-lo, -hi), lambda lo, hi, n: (hi, lo)],
                         ids=["negative", "reversed"])
def test_signed_or_reversed_estimate_is_kept_as_magnitudes(world, settings, transform):
    t, r, b = run(world, settings, {("thor", "AdvocateBrief"): brief_with(transform)})
    est = next(c.exposure for c in r.submissions["thor"].claims if c.exposure)
    assert 0 <= est.low <= est.high and "[code:" in est.uncertainty_note
    assert [c["schema"] for c in b.calls if c["agent"] == "thor"].count("AdvocateBrief") == 1  # fixed in code, no repair
    row = next(x for x in r.odin.ranges if x.agent.value == "odin") if r.odin.ranges else None
    assert row is None or row.low <= row.high


def test_estimate_that_does_not_reproduce_gets_one_repair(world, settings):
    def wrong_then_right(lo, hi, n):
        return (lo + 7.0, hi) if n == 0 else (lo, hi)  # first answer: a low bound that matches no calc record
    t, r, b = run(world, settings, {("thor", "AdvocateBrief"): brief_with(wrong_then_right)})
    briefs = [c for c in b.calls if c["agent"] == "thor" and c["schema"] == "AdvocateBrief"]
    assert len(briefs) == 2 and "<repair_request>" in briefs[1]["user"] and "does not equal the result" in briefs[1]["user"]
    assert any(c.exposure for c in r.submissions["thor"].claims)  # the repaired estimate survives


def test_odin_negative_range_is_kept(world, settings):
    base = default_handlers()[("odin", "OdinJudgment")]

    def odin(user, n):
        j = base(user, n)
        j.ranges = [x.model_copy(update={"low": -x.high, "high": -x.low}) if x.low is not None else x for x in j.ranges]
        return j
    t, r, b = run(world, settings, {("odin", "OdinJudgment"): odin})
    assert r.odin.ranges and all(0 <= x.low <= x.high for x in r.odin.ranges)
    assert any("negative changes" in g for g in r.odin.guards)

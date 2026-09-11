"""demo_case.py — load the committed synthetic demo patient into a typed `PatientCase`.

`data/demo_patient.json` is the SSoT for every number the demonstration shows, and
`tests/test_demo_fixture.py` regenerates each of them from the seeds it declares. This module
only reads it. It computes no clinical value of its own, so a figure on stage traces to a
committed byte rather than to whatever this loader happened to do.

THE PATIENT IS SYNTHETIC. Every concentration in the file came from simulating the published
population model against itself with a seeded RNG, and nothing about the model's accuracy may
be derived from it. The file says so at its top and this module does not soften it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, cast, get_args

from agent_pk.agent.case import CarePlan, PatientCase
from agent_pk.pk.model import DoseEvent, Observation, PkInputError
from agent_pk.pk.priors import Covariates, Formulation

#: The fixture's schema version this loader understands. Checked, not merely declared: an
#: unchecked version field is decoration, and a future format would be parsed as though it
#: were this one and surface as whatever downstream error the wrong shape happened to produce.
SUPPORTED_FIXTURE_SCHEMA_VERSION: Final[int] = 1

#: Seeds for the two stochastic steps of an evaluation. Fixed here so a demonstration is
#: byte-reproducible; they are NOT the fixture's own generation seeds, which belong to the
#: data and live in the file.
DEMO_PREDICTION_SEED: Final[int] = 20260912
DEMO_OFFER_SEED: Final[int] = 20260913


def default_fixture_path() -> Path:
    """Where the committed demo patient lives.

    Returns:
        The path, resolved from this module's own location rather than from the working
        directory, so the loader behaves the same however the server was started.
    """
    return Path(__file__).resolve().parents[3] / "data" / "demo_patient.json"


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    """Fetch a required key, or raise naming where it was missing.

    A `.get(key, default)` on a load-bearing key fails OPEN: the demo would run on a silently
    substituted value and look fine.

    Args:
        mapping: The object to read.
        key: The required key.
        where: Path of the parent, for the message.

    Returns:
        The value.

    Raises:
        PkInputError: If the key is absent.
    """
    if key not in mapping:
        raise PkInputError(f"demo fixture is missing {where}.{key}")
    return mapping[key]


def _formulation(value: object) -> Formulation:
    """Validate the fixture's formulation string against the type's own members.

    `Formulation` is a `Literal`, so it cannot be called as a constructor and an unchecked
    string would flow straight through to a prior built for a product this is not.

    Args:
        value: The raw value from the fixture.

    Returns:
        The value, narrowed.

    Raises:
        PkInputError: If it is not one of the declared formulations.
    """
    permitted = get_args(Formulation)
    if value not in permitted:
        raise PkInputError(
            f"demo fixture declares formulation {value!r}; permitted: {permitted!r}"
        )
    return cast(Formulation, value)


def load_demo_case(path: Path | None = None) -> PatientCase:
    """Read the committed fixture and build the evaluation's inputs from it.

    Args:
        path: Override for the fixture location. Defaults to the committed file.

    Returns:
        The `PatientCase` the demonstration runs on.

    Raises:
        PkInputError: If the file is missing a required field, or declares a schema version
            this loader does not implement.
        OSError: If the file cannot be read.
        UnicodeDecodeError: If it is not valid UTF-8. Named separately because it subclasses
            `ValueError`, not `OSError`, and an `except OSError` would let it through.
        json.JSONDecodeError: If it is not valid JSON.
    """
    fixture_path = path or default_fixture_path()
    data: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))

    declared = _require(data, "schema_version", "fixture")
    if declared != SUPPORTED_FIXTURE_SCHEMA_VERSION:
        raise PkInputError(
            f"demo fixture declares schema_version {declared!r}; this loader implements "
            f"{SUPPORTED_FIXTURE_SCHEMA_VERSION!r} and will not guess at the difference"
        )

    regeneration = _require(data, "regeneration", "fixture")
    covariates_raw = _require(data, "covariates", "fixture")
    band = _require(data, "band", "fixture")
    care_plan_raw = _require(data, "care_plan", "fixture")

    dose_mg = float(_require(regeneration, "dose_mg", "regeneration"))
    days = int(_require(regeneration, "days", "regeneration"))
    interval_h = float(_require(regeneration, "dosing_interval_h", "regeneration"))
    doses = tuple(
        DoseEvent(time_h=index * interval_h, amount_mg=dose_mg, status="taken")
        for index in range(days)
    )

    troughs = tuple(
        Observation(
            time_h=float(_require(row, "time_h", "troughs[]")),
            concentration_ng_per_ml=float(
                _require(row, "concentration_ng_per_ml", "troughs[]")
            ),
        )
        for row in _require(data, "troughs", "fixture")
    )
    curve_samples = tuple(
        Observation(
            time_h=float(_require(row, "time_h", "measured_curve[]")),
            concentration_ng_per_ml=float(
                _require(row, "concentration_ng_per_ml", "measured_curve[]")
            ),
        )
        for row in _require(data, "measured_curve", "fixture")
    )

    covariates = Covariates(
        weight_kg=float(_require(covariates_raw, "weight_kg", "covariates")),
        haematocrit=float(_require(covariates_raw, "haematocrit", "covariates")),
        cyp3a5_expresser=bool(
            _require(covariates_raw, "cyp3a5_expresser", "covariates")
        ),
        formulation=_formulation(_require(covariates_raw, "formulation", "covariates")),
    )

    plan = CarePlan(
        lower_bound_ng_per_ml=float(_require(band, "lower_ng_per_ml", "band")),
        upper_bound_ng_per_ml=float(_require(band, "upper_ng_per_ml", "band")),
        plan_text_from_clinician=str(
            _require(care_plan_raw, "plan_text_from_clinician", "care_plan")
        ),
        band_citation=str(_require(band, "citation", "band")),
    )

    return PatientCase(
        covariates=covariates,
        doses=doses,
        troughs=troughs,
        curve_samples=curve_samples,
        plan=plan,
        target_time_h=float(_require(data, "prediction_target_time_h", "fixture")),
        next_dose_time_h=float(
            _require(regeneration, "curve_dose_time_h", "regeneration")
        ),
        prediction_seed=DEMO_PREDICTION_SEED,
        offer_seed=DEMO_OFFER_SEED,
    )


def load_demo_reference_instant(path: Path | None = None) -> str:
    """The ISO-8601 UTC instant that `time_h = 0` maps to, for rendering local times.

    Kept OUT of `PatientCase` on purpose: the numeric core carries no wall-clock time, and
    putting a datetime on the case would move timezone handling into the decision path.

    Args:
        path: Override for the fixture location.

    Returns:
        The instant, exactly as the fixture states it.

    Raises:
        PkInputError: If the field is absent.
    """
    fixture_path = path or default_fixture_path()
    data: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
    return str(_require(data, "reference_instant_utc", "fixture"))


def load_troughs_only_case(path: Path | None = None) -> PatientCase:
    """The same patient BEFORE the sampling occasion — troughs only, no curve.

    This is the state the demonstration opens in, and the one the escalation fires from: with
    troughs alone the fit cannot identify absorption, the published limited-sampling equation
    cannot be run against it, and the prediction interval reaches a plan boundary. Accepting
    the offer is what adds the curve.

    Args:
        path: Override for the fixture location.

    Returns:
        The case with `curve_samples` empty.
    """
    full = load_demo_case(path)
    return PatientCase(
        covariates=full.covariates,
        doses=full.doses,
        troughs=full.troughs,
        curve_samples=(),
        plan=full.plan,
        target_time_h=full.target_time_h,
        next_dose_time_h=full.next_dose_time_h,
        prediction_seed=full.prediction_seed,
        offer_seed=full.offer_seed,
        offer_simulations=full.offer_simulations,
    )

"""Two-channel permission boundary for Agent PK.

The clinician channel supports recommendations under 21 U.S.C. 360j(o)(1)(E) and shows their
complete basis. The patient channel displays the patient's own data and their own clinician's
own findings under (o)(1)(D), and interprets nothing.

See `docs/GUARDRAILS.md` for the mapping, the four criteria, and why the general-wellness route
was rejected for the patient channel.
"""

from __future__ import annotations

from agent_pk.channel.views import (
    PATIENT_MESSAGE_BODY,
    PATIENT_VIEW_FIELDS,
    Attribution,
    ChannelBoundaryError,
    ClinicalAction,
    ClinicianView,
    ConcurrentObservation,
    EvidenceNote,
    ParameterEstimate,
    PatientMessage,
    PatientView,
    SampleAppointment,
    general_evaluation_notice,
    to_patient_view,
)

__all__ = [
    "PATIENT_MESSAGE_BODY",
    "PATIENT_VIEW_FIELDS",
    "Attribution",
    "ChannelBoundaryError",
    "ClinicalAction",
    "ClinicianView",
    "ConcurrentObservation",
    "EvidenceNote",
    "ParameterEstimate",
    "PatientMessage",
    "PatientView",
    "SampleAppointment",
    "general_evaluation_notice",
    "to_patient_view",
]

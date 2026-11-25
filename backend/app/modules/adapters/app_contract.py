from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...schemas import CaseActionData, InteractionRequest, PersonInput, Relationship


class AppPreregisterData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_id: str = Field(min_length=1)
    relationship: Relationship
    patient: PersonInput | None = Field(
        default=None, description="Obligatorio para otra persona. Se omite en trámites propios.",
    )


class AppStudyData(CaseActionData):
    study_id: str = Field(min_length=1)


class AppClinicData(CaseActionData):
    clinic_id: str = Field(min_length=1)


class AppSlotData(CaseActionData):
    slot_id: str = Field(min_length=1)


class AppAction(InteractionRequest):
    identifier_type: Literal["account"]
    kind: Literal["action"]


class AppExistingCase(AppAction):
    action: Literal["continue_case", "confirm_case"]
    data: CaseActionData


class AppSelectStudy(AppAction):
    action: Literal["select_study"]
    data: AppStudyData


class AppSelectClinic(AppAction):
    action: Literal["select_clinic"]
    data: AppClinicData


class AppSelectSlot(AppAction):
    action: Literal["select_slot"]
    data: AppSlotData


class AppPreregister(AppAction):
    action: Literal["preregister"]
    data: AppPreregisterData


AppInteraction = Annotated[
    AppExistingCase | AppSelectStudy | AppSelectClinic | AppSelectSlot | AppPreregister,
    Field(discriminator="action"),
]

from pydantic import BaseModel, ConfigDict, Field


class AnswerIn(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=255)
    patterns: list[str] = Field(min_length=1)
    answer: str = Field(min_length=1, max_length=2000)


class AnswerOut(AnswerIn):
    model_config = ConfigDict(from_attributes=True)

    id: int

import io
from pydantic import BaseModel, Field, TypeAdapter
from typing import Literal, List, Union, cast

# small strings:
# >>> timeit.timeit(stmt='adapter.dump_json(s)', setup='from pydantic import TypeAdapter; adapter = TypeAdapter(str); s="some test string" * 10')
# 0.5624214999988908
# >>> timeit.timeit(stmt='json.dumps(s).encode("utf-8")', setup='import json; s="some test string" * 10')
# 0.46921870000005583
#
# note - if we know the value is ascii, 10x speedup:
# >>> timeit.timeit(stmt='s.encode("ascii")', setup='import json; s="some test string" * 10')
# 0.041761100001167506
#
# long strings:
# >>> timeit.timeit(stmt='adapter.dump_json(s)', setup='from pydantic import TypeAdapter; adapter = TypeAdapter(str); s="some test string" * 1000')
# 5.546335699997144
# >>> timeit.timeit(stmt='json.dumps(s).encode("utf-8")', setup='import json; s="some test string" * 1000')
# 21.25628290000168

str_adapter = cast(TypeAdapter[str], TypeAdapter(str))


class JournalEntryItemTextualPartParagraph(BaseModel):
    type: Literal["paragraph"] = Field(description="A single paragraph of text")
    value: str = Field(description="The contents of the paragraph")

    def model_dump_for_integrity(self, out: io.BytesIO) -> None:
        out.write(b'{"type": "paragraph", "value": ')
        out.write(str_adapter.dump_json(self.value))
        out.write(b"}")


class JournalEntryItemTextualPartJourney(BaseModel):
    type: Literal["journey"] = Field(description="A link to a journey")
    uid: str = Field(description="The UID of the journey that was linked")

    def model_dump_for_integrity(self, out: io.BytesIO) -> None:
        out.write(b'{"type": "journey", "uid": "')
        out.write(self.uid.encode("ascii"))
        out.write(b'"}')


JournalEntryItemTextualPart = Union[
    JournalEntryItemTextualPartJourney, JournalEntryItemTextualPartParagraph
]


class JournalEntryItemDataDataTextual(BaseModel):
    parts: List[JournalEntryItemTextualPart] = Field(
        description="The parts of the textual data"
    )

    type: Literal["textual"] = Field(description="The type of data described")

    def model_dump_for_integrity(self, out: io.BytesIO) -> None:
        out.write(b'{"parts": [')
        if self.parts:
            self.parts[0].model_dump_for_integrity(out)
            for idx in range(1, len(self.parts)):
                out.write(b", ")
                self.parts[idx].model_dump_for_integrity(out)
        out.write(b'], "type": "textual"}')

    def __str__(self):
        return f"JournalEntryItemDataDataTextual(OMITTED FOR PRIVACY)"

    def repr(self):
        return str(self)


class JournalEntryItemUIConceptualUserJourney(BaseModel):
    journey_uid: str = Field(description="The UID of the journey")
    type: Literal["user_journey"] = Field(
        description="we were trying to have the user take a journey"
    )
    user_journey_uid: str = Field(
        description="The UID of the record tracking the user took the journey"
    )

    def model_dump_for_integrity(self, out: io.BytesIO) -> None:
        out.write(b'{"journey_uid": "')
        out.write(self.journey_uid.encode("ascii"))
        out.write(b'", "type": "user_journey", "user_journey_uid": "')
        out.write(self.user_journey_uid.encode("ascii"))
        out.write(b'"}')


class JournalEntryItemUIConceptualUpgrade(BaseModel):
    type: Literal["upgrade"] = Field(
        description="we were trying to have the user upgrade to oseh+"
    )

    def model_dump_for_integrity(self, out: io.BytesIO) -> None:
        out.write(b'{"type": "upgrade"}')


JournalEntryItemUIConceptual = Union[
    JournalEntryItemUIConceptualUserJourney, JournalEntryItemUIConceptualUpgrade
]


class JournalEntryItemUIFlow(BaseModel):
    slug: str = Field(description="the slug of the client flow they took")

    def model_dump_for_integrity(self, out: io.BytesIO) -> None:
        out.write(b'{"slug": ')
        out.write(str_adapter.dump_json(self.slug))
        out.write(b"}")


class JournalEntryItemDataDataUI(BaseModel):
    conceptually: JournalEntryItemUIConceptual = Field(
        description="What this UI event was trying to accomplish"
    )
    flow: JournalEntryItemUIFlow = Field(
        description="The flow we triggered on the users screen queue"
    )
    type: Literal["ui"] = Field(description="The type of data described")

    def model_dump_for_integrity(self, out: io.BytesIO) -> None:
        out.write(b'{"conceptually": ')
        self.conceptually.model_dump_for_integrity(out)
        out.write(b', "flow": ')
        self.flow.model_dump_for_integrity(out)
        out.write(b', "type": "ui"}')


JournalEntryItemDataData = Union[
    JournalEntryItemDataDataTextual, JournalEntryItemDataDataUI
]


class JournalEntryItemData(BaseModel):
    """The data for a journal entry item that we consider particularly sensitive.
    This should only ever be transferred encrypted with a journal master key
    (for internal communication) or journal client key (for providing it to the
    user who wrote it)
    """

    data: JournalEntryItemDataData = Field(
        description="describes how to render this item"
    )

    display_author: Literal["self", "other"] = Field(
        description="who to display as the author of this item; self means the user, other means the system"
    )

    type: Literal["chat", "reflection-question", "reflection-response", "ui"] = Field(
        description="The type of thing that occurred"
    )

    def model_dump_for_integrity(self, out: io.BytesIO) -> None:
        out.write(b'{"data": ')
        self.data.model_dump_for_integrity(out)
        out.write(b', "display_author": "')
        out.write(self.display_author.encode("ascii"))
        out.write(b'", "type": "')
        out.write(self.type.encode("ascii"))
        out.write(b'"}')

    def __str__(self):
        return f"JournalEntryItemData(OMITTED FOR PRIVACY)"

    def repr(self):
        return str(self)

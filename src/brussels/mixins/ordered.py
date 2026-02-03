from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, mapped_column


@declarative_mixin
class OrderedMixin(MappedAsDataclass):
    position: Mapped[int] = mapped_column(Integer, nullable=False, index=True, init=False)

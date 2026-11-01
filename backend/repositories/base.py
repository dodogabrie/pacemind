"""Base repository with common CRUD operations."""

from typing import TypeVar, Generic, Type, Optional, List
from database import db

T = TypeVar('T', bound=db.Model)


class BaseRepository(Generic[T]):
    """Base repository providing standard CRUD operations.

    Subclasses must set the `model` class attribute.
    Uses flush() for individual operations — call commit() explicitly
    to define transaction boundaries.
    """

    model: Type[T]

    def get_by_id(self, id: int) -> Optional[T]:
        return db.session.get(self.model, id)

    def get_all(self) -> List[T]:
        return self.model.query.all()

    def find_by(self, **kwargs) -> List[T]:
        return self.model.query.filter_by(**kwargs).all()

    def find_one_by(self, **kwargs) -> Optional[T]:
        return self.model.query.filter_by(**kwargs).first()

    def create(self, entity: T) -> T:
        db.session.add(entity)
        db.session.flush()
        return entity

    def save(self, entity: T) -> T:
        """Add entity to session (for new or detached entities)."""
        db.session.add(entity)
        db.session.flush()
        return entity

    def delete(self, entity: T) -> None:
        db.session.delete(entity)
        db.session.flush()

    def count(self, **kwargs) -> int:
        return self.model.query.filter_by(**kwargs).count()

    def commit(self) -> None:
        db.session.commit()

    def rollback(self) -> None:
        db.session.rollback()

    def flush(self) -> None:
        db.session.flush()

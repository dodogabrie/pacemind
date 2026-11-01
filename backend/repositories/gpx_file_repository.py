"""GPX file repository."""

from typing import Optional, List
from models import GPXFile
from repositories.base import BaseRepository


class GPXFileRepository(BaseRepository[GPXFile]):
    model = GPXFile

    def get_user_files(self, user_id: int) -> List[GPXFile]:
        """Get all GPX files for user, newest first."""
        return GPXFile.query.filter_by(user_id=user_id) \
            .order_by(GPXFile.upload_date.desc()).all()

    def get_user_file(self, gpx_id: int, user_id: int) -> Optional[GPXFile]:
        """Get a specific GPX file belonging to user."""
        return self.find_one_by(id=gpx_id, user_id=user_id)

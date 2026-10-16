"""Use the same prepared object bytes for the viewer and the World Builder."""
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from core.asset_delivery import model_path


class PreparedObjectFiles(StaticFiles):
    def lookup_path(self, path):
        source, stat = super().lookup_path(path)
        if stat is not None and Path(source).suffix.lower() == '.glb':
            prepared = Path(model_path(source))
            return str(prepared), prepared.stat()
        return source, stat

from server.constants import BASE_STORAGE_PATH
from server.api import app, processor
import uvicorn

if __name__ == "__main__":
    (BASE_STORAGE_PATH / "templates").mkdir(exist_ok=True)
    (BASE_STORAGE_PATH / "temp_uploads").mkdir(exist_ok=True)
    (BASE_STORAGE_PATH / "rendered").mkdir(exist_ok=True)

    print("=" * 60)
    print("DOCX Template API v3.0 - Примечания (refactored)")
    print("=" * 60)
    print("Web интерфейс: http://localhost:8000")
    print("API документация: http://localhost:8000/docs")
    print("=" * 60)

    uvicorn.run(app, host="127.0.0.1", port=8000)

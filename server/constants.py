from pathlib import Path

ROOT_PATH = Path(__file__).parent.parent
BASE_STORAGE_PATH = Path("./docx_templates_storage")
BASE_STORAGE_PATH.mkdir(exist_ok=True)

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{%s}" % WORD_NS
VARIABLE_DEFINITION_DELIMITER = r"\\"

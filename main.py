from fastapi import FastAPI, UploadFile, Form, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from docxtpl import DocxTemplate
import json
import os
from uuid import uuid4

app = FastAPI(title="DOCX Template Generator")

# каталоги
os.makedirs("templates", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
os.makedirs("output", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Загрузка шаблона и JSON описания формы
@app.post("/upload-template/")
async def upload_template(
    docx_file: UploadFile = File(...),
    form_json: UploadFile = File(...)
):
    docx_path = f"templates/{docx_file.filename}"
    json_path = f"templates/{os.path.splitext(docx_file.filename)[0]}.json"
    with open(docx_path, "wb") as f:
        f.write(await docx_file.read())
    with open(json_path, "wb") as f:
        f.write(await form_json.read())
    return {"status": "ok", "template": docx_file.filename}

# Список доступных шаблонов
@app.get("/templates/")
def list_templates():
    templates = []
    for f in os.listdir("templates"):
        if f.endswith(".docx"):
            name = os.path.splitext(f)[0]
            json_path = f"templates/{name}.json"
            templates.append({
                "name": name,
                "has_form": os.path.exists(json_path)
            })
    return templates

# Получение JSON формы для шаблона
@app.get("/templates/{name}/form")
def get_form(name: str):
    path = f"templates/{name}.json"
    if not os.path.exists(path):
        return JSONResponse({"error": "Форма не найдена"}, status_code=404)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# Генерация DOCX по данным формы
@app.post("/generate/{name}")
async def generate_doc(name: str, data: str = Form(...)):
    data_dict = json.loads(data)
    template_path = f"templates/{name}.docx"
    output_path = f"output/{name}_{uuid4().hex}.docx"

    doc = DocxTemplate(template_path)
    doc.render(data_dict)
    doc.save(output_path)

    return FileResponse(output_path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        filename=os.path.basename(output_path))

# Главная страница
@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()

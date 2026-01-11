import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .constants import BASE_STORAGE_PATH, ROOT_PATH
from .processor import CommentsDocumentProcessor

app = FastAPI(title="DOCX Template API with Comments", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = BASE_STORAGE_PATH / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

templates_dir = ROOT_PATH / "server" / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

processor = CommentsDocumentProcessor()

# Список доступных парсеров (имя => класс). В будущем можно расширить динамической регистрацией плагинов.
from .parser import CommentsParser as CommentsParserClass
AVAILABLE_PARSERS = {
    'comments': CommentsParserClass
}

@app.get('/api/parsers')
async def get_parsers():
    return list(AVAILABLE_PARSERS.keys())

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": __import__('datetime').datetime.now().isoformat(),
        "collections_count": len(processor.storage.collections),
        "templates_count": len(processor.storage.templates),
        "version": "3.0.0 (comments-based)"
    }

@app.post("/api/collections")
async def create_collection(name: str = Form(...), description: str = Form("")):
    try:
        collection = processor.storage.create_collection(name, description)
        return JSONResponse(
            status_code=201,
            content=collection.to_dict()
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/collections")
async def get_collections():
    collections = list(processor.storage.collections.values())
    return [c.to_dict() for c in collections]

@app.post("/api/collections/templates")
async def upload_template(
    collection_id: str = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...)
):
    try:
        temp_dir = BASE_STORAGE_PATH / "temp_uploads"
        temp_dir.mkdir(exist_ok=True)
        temp_path = temp_dir / f"upload_{__import__('uuid').uuid4()}.docx"

        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        template = processor.register_template(
            collection_id=collection_id,
            template_name=name,
            docx_file_path=temp_path,
            original_filename=file.filename
        )

        temp_path.unlink()

        return JSONResponse(
            status_code=201,
            content=template.to_dict()
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/collections/{collection_id}/variables")
async def get_collection_variables(collection_id: str):
    collection = processor.storage.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    data = processor.storage.get_collection_variables(collection_id)
    try:
        print(f"API: get_collection_variables for {collection_id} -> {list(data.keys())}")
    except Exception:
        pass
    return data


@app.post("/api/collections/{collection_id}/variables")
async def set_collection_variable(
    collection_id: str,
    name: str = Form(...),
    type: str = Form('text'),
    value: str = Form(''),
    metadata: str = Form(None)
):
    collection = processor.storage.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    md = None
    if metadata:
        try:
            import json
            md = json.loads(metadata)
        except Exception:
            raise HTTPException(status_code=400, detail="metadata must be a valid JSON string")

    ok = processor.storage.create_or_update_collection_variable(collection_id, name, type, value, md)
    if not ok:
        raise HTTPException(status_code=400, detail="Could not save collection variable")

    try:
        print(f"API: saved collection variable {name} in collection {collection_id}")
    except Exception:
        pass

    return {name: {'type': type, 'value': value, 'metadata': md or {}}}


@app.delete("/api/collections/{collection_id}/variables/{var_name}")
async def delete_collection_variable(collection_id: str, var_name: str):
    collection = processor.storage.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    ok = processor.storage.delete_collection_variable(collection_id, var_name)
    if not ok:
        raise HTTPException(status_code=404, detail="Variable not found")
    return {"deleted": var_name}

@app.get("/api/collections/{collection_id}/templates")
async def get_collection_templates(collection_id: str):
    templates = processor.storage.get_collection_templates(collection_id)
    if not templates:
        return []
    return [t.to_dict() for t in templates]

@app.get("/api/templates/{template_id}")
async def get_template(template_id: str):
    template = processor.storage.templates.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    data = template.to_dict()

    # Подмешиваем определения переменных из коллекции
    try:
        coll_vars = processor.storage.get_collection_variables(template.collection_id) or {}

        # 1) Для переменных, которые в шаблоне хранят ссылку collection_var_name — подменяем type/metadata/value из коллекции
        for vname, vdata in data.get('variables', {}).items():
            coll_name = vdata.get('collection_var_name') or vname
            cv = coll_vars.get(coll_name)
            if cv:
                vdata['is_collection_var'] = True
                vdata['type'] = cv.get('type', 'text')  # Получаем type из коллекции
                vdata['metadata'] = cv.get('metadata', {})
                vdata['value'] = cv.get('value', '')
            else:
                vdata['is_collection_var'] = False

        # 2) Добавляем в ответ те переменные коллекции, которых нет в шаблоне
        for name, cv in coll_vars.items():
            if name not in data.get('variables', {}):
                data['variables'][name] = {
                    'name': name,
                    'collection_var_name': name,
                    'type': cv.get('type', 'text'),
                    'comment_id': '',
                    'comment_ids': [],
                    'context': '',
                    'contexts': [],
                    'occurrences': 0,
                    'locations': [],
                    'metadata': cv.get('metadata', {}),
                    'value': cv.get('value', ''),
                    'is_collection_var': True
                }
    except Exception:
        pass

    return data


@app.post('/api/templates/{template_id}/rescan')
async def rescan_template(template_id: str):
    try:
        template = processor.rescan_template(template_id)
        return template.to_dict()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/render/single/json")
async def render_single_document_json(data: dict):
    try:
        template_id = data.get('template_id')
        variables = data.get('variables', {})

        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")

        rendered_path = processor.render_document(template_id, variables)

        return FileResponse(
            rendered_path,
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            filename=rendered_path.name
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/render/preview")
async def render_preview(data: dict):
    """Рендерит документ и конвертирует его в PDF для предпросмотра"""
    try:
        template_id = data.get('template_id')
        variables = data.get('variables', {})

        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")

        # Рендерим документ
        rendered_docx = processor.render_document(template_id, variables)
        
        # Конвертируем в PDF
        pdf_path = processor.docx_to_pdf(rendered_docx)

        return FileResponse(
            pdf_path,
            media_type='application/pdf',
            filename=pdf_path.name
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get('/api/collections/{collection_id}/aggregate-variables')
async def aggregate_variables(collection_id: str, template_ids: str = None):
    """Возвращает агрегированные переменные по выбранным шаблонам в коллекции.
    Параметр template_ids — csv id'шников. Если не указан — по всем шаблонам коллекции.
    """
    collection = processor.storage.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail='Collection not found')

    if template_ids:
        ids = [t for t in template_ids.split(',') if t]
    else:
        ids = collection.templates

    agg = processor.aggregate_variables_for_templates(collection_id, ids)
    return {'variables': agg}


@app.post('/api/render/batch')
async def render_batch(data: dict):
    try:
        collection_id = data.get('collection_id')
        template_ids = data.get('template_ids', [])
        variables = data.get('variables', {})

        if not collection_id:
            raise HTTPException(status_code=400, detail='collection_id is required')
        if not template_ids:
            raise HTTPException(status_code=400, detail='template_ids is required')

        # validate templates belong to collection
        coll = processor.storage.get_collection(collection_id)
        if not coll:
            raise HTTPException(status_code=404, detail='Collection not found')
        for tid in template_ids:
            if tid not in coll.templates:
                raise HTTPException(status_code=400, detail=f'Template {tid} does not belong to collection')

        zip_path = processor.render_documents_batch(collection_id, template_ids, variables)

        return FileResponse(
            zip_path,
            media_type='application/zip',
            filename=zip_path.name
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

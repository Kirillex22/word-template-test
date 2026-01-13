# 📡 API Справочник - Полный список endpoints

Полная документация REST API системы управления шаблонами.

## 📑 Содержание

1. [Общая информация](#общая-информация)
2. [Collections Endpoints](#collections-endpoints)
3. [Templates Endpoints](#templates-endpoints)
4. [Render Endpoints](#render-endpoints)
5. [Примеры использования](#примеры-использования)
6. [Обработка ошибок](#обработка-ошибок)

---

## 📋 Общая информация

### Базовый URL

```
http://localhost:8000
```

### Authentication

⚠️ На текущий момент аутентификация отсутствует.

В будущих версиях:
- Bearer token в заголовке Authorization
- API keys для интеграции
- Role-based access control (RBAC)

### Content-Type

Все запросы и ответы используют `application/json`, кроме файловых операций:

```
POST /api/templates/upload    ← multipart/form-data
GET  /render/file.docx        ← application/octet-stream
```

### Status Codes

```
200 OK                  - Успешно
201 Created            - Ресурс создан
400 Bad Request        - Ошибка валидации
404 Not Found          - Ресурс не найден
500 Internal Server Error - Ошибка сервера
```

### CORS Headers

Сервер отправляет:
```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type
```

---

## 🗂️ Collections Endpoints

### 1. Создание коллекции

**Request:**
```
POST /api/collections
Content-Type: application/json

{
  "name": "Договоры 2026"
}
```

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Договоры 2026",
  "templates": [],
  "variables": [],
  "created_at": "2026-01-12T15:30:00.000Z"
}
```

**Ошибки:**
```
400 Bad Request
{
  "detail": "Название коллекции не может быть пустым"
}

400 Bad Request
{
  "detail": "Коллекция с таким именем уже существует"
}
```

---

### 2. Получение списка коллекций

**Request:**
```
GET /api/collections
```

**Response (200 OK):**
```json
{
  "collections": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "Договоры 2026",
      "templates": 3,
      "variables": 8,
      "created_at": "2026-01-12T15:30:00.000Z"
    },
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "name": "Служебные документы",
      "templates": 5,
      "variables": 12,
      "created_at": "2026-01-10T10:00:00.000Z"
    }
  ]
}
```

---

### 3. Получение коллекции

**Request:**
```
GET /api/collections/{collection_id}
```

**Path Parameters:**
- `collection_id` (string, required) - UUID коллекции

**Response (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Договоры 2026",
  "created_at": "2026-01-12T15:30:00.000Z",
  "templates": [
    {
      "id": "template-001",
      "name": "договор.docx",
      "variables": ["фамилия", "дата"]
    }
  ],
  "variables": [
    {
      "name": "фамилия",
      "type": "text",
      "occurrences": 2
    }
  ]
}
```

**Ошибки:**
```
404 Not Found
{
  "detail": "Коллекция не найдена"
}
```

---

### 4. Удаление коллекции

**Request:**
```
DELETE /api/collections/{collection_id}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "message": "Коллекция удалена"
}
```

---

## 📚 Templates Endpoints

### 5. Загрузка шаблона

**Request:**
```
POST /api/templates/upload
Content-Type: multipart/form-data

Form Data:
- collection_id: "550e8400-e29b-41d4-a716-446655440000"
- file: <binary DOCX file>
```

**Response (200 OK):**
```json
{
  "status": "success",
  "template": {
    "id": "template-001",
    "name": "договор.docx",
    "collection_id": "550e8400-e29b-41d4-a716-446655440000",
    "uploaded_at": "2026-01-12T15:30:00.000Z",
    "variables": [
      {
        "name": "фамилия_клиента",
        "type": "text",
        "occurrences": 1,
        "contexts": ["Клиент: [фамилия_клиента]"]
      },
      {
        "name": "дата_договора",
        "type": "date",
        "occurrences": 1
      },
      {
        "name": "согласие_1",
        "type": "checkbox",
        "occurrences": 1
      }
    ],
    "legacy_checkboxes_found": 5
  }
}
```

**Ошибки:**
```
400 Bad Request
{
  "detail": "Коллекция не найдена"
}

400 Bad Request
{
  "detail": "Файл должен быть DOCX"
}

400 Bad Request
{
  "detail": "Файл повреждена"
}

413 Payload Too Large
{
  "detail": "Файл слишком большой (максимум 50 MB)"
}
```

---

### 6. Список шаблонов в коллекции

**Request:**
```
GET /api/templates/{collection_id}
```

**Response (200 OK):**
```json
{
  "collection_id": "550e8400-e29b-41d4-a716-446655440000",
  "templates": [
    {
      "id": "template-001",
      "name": "договор.docx",
      "uploaded_at": "2026-01-12T15:30:00.000Z",
      "variables": 5,
      "pages": 2
    },
    {
      "id": "template-002",
      "name": "счет.docx",
      "uploaded_at": "2026-01-11T10:00:00.000Z",
      "variables": 8,
      "pages": 1
    }
  ]
}
```

---

### 7. Информация о шаблоне

**Request:**
```
GET /api/templates/{template_id}
```

**Response (200 OK):**
```json
{
  "id": "template-001",
  "name": "договор.docx",
  "collection_id": "550e8400-e29b-41d4-a716-446655440000",
  "uploaded_at": "2026-01-12T15:30:00.000Z",
  "file_size": 125000,
  "pages": 2,
  "variables": [
    {
      "name": "фамилия_клиента",
      "type": "text",
      "occurrences": 1,
      "locations": [{"page": 1, "position": 150}]
    }
  ]
}
```

---

### 8. Удаление шаблона

**Request:**
```
DELETE /api/templates/{template_id}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "message": "Шаблон удален"
}
```

---

## 🎨 Render Endpoints

### 9. Единичный рендеринг

**Request:**
```
POST /api/render
Content-Type: application/json

{
  "template_id": "template-001",
  "data": {
    "фамилия_клиента": "Петров",
    "дата_договора": "12.01.2026",
    "согласие_1": true
  }
}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "file_url": "/rendered/rendered_договор_20260112_143000.docx",
  "file_name": "rendered_договор_20260112_143000.docx",
  "generated_at": "2026-01-12T14:30:00.000Z",
  "processing_time": 3.5
}
```

**Ошибки:**
```
400 Bad Request
{
  "detail": "Переменная 'фамилия_клиента' не найдена"
}

400 Bad Request
{
  "detail": "Некорректный формат даты для 'дата_договора'"
}

404 Not Found
{
  "detail": "Шаблон не найден"
}
```

---

### 10. Предпросмотр PDF

**Request:**
```
POST /api/render/preview
Content-Type: application/json

{
  "template_id": "template-001",
  "data": {
    "фамилия_клиента": "Петров",
    "дата_договора": "12.01.2026"
  }
}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "file_url": "/rendered/preview_договор_20260112_143000.pdf",
  "file_name": "preview_договор_20260112_143000.pdf",
  "pages": 2,
  "generated_at": "2026-01-12T14:30:00.000Z",
  "processing_time": 5.2
}
```

---

### 11. Массовый рендеринг

**Request:**
```
POST /api/render/batch
Content-Type: application/json

{
  "template_id": "template-001",
  "data": [
    {
      "фамилия_клиента": "Петров",
      "дата_договора": "12.01.2026",
      "согласие_1": true
    },
    {
      "фамилия_клиента": "Сидоров",
      "дата_договора": "13.01.2026",
      "согласие_1": false
    },
    {
      "фамилия_клиента": "Иванов",
      "дата_договора": "14.01.2026",
      "согласие_1": true
    }
  ]
}
```

**Response (200 OK):**
```json
{
  "status": "success",
  "total": 3,
  "successful": 3,
  "failed": 0,
  "file_url": "/rendered/batch_rendered_20260112_143000.zip",
  "file_name": "batch_rendered_20260112_143000.zip",
  "archive_size": 375000,
  "generated_at": "2026-01-12T14:30:00.000Z",
  "processing_time": 10.5,
  "documents": [
    "rendered_doc_001.docx",
    "rendered_doc_002.docx",
    "rendered_doc_003.docx"
  ]
}
```

**Ошибки:**
```
400 Bad Request
{
  "status": "partial_failure",
  "total": 100,
  "successful": 99,
  "failed": 1,
  "errors": [
    {
      "row": 42,
      "error": "Неверный формат даты",
      "data": {"дата_договора": "invalid_date"}
    }
  ]
}
```

---

### 12. Получение файла

**Request:**
```
GET /rendered/{file_name}
```

**Response (200 OK):**
```
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="rendered_договор_20260112_143000.docx"

[binary file content]
```

---

## 💻 Примеры использования

### JavaScript (Fetch API)

**Создание коллекции:**
```javascript
const response = await fetch('http://localhost:8000/api/collections', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    name: 'Договоры 2026'
  })
});

const collection = await response.json();
console.log('Создана коллекция:', collection.id);
```

**Загрузка шаблона:**
```javascript
const formData = new FormData();
formData.append('collection_id', 'collection-id-here');
formData.append('file', fileInput.files[0]);

const response = await fetch('http://localhost:8000/api/templates/upload', {
  method: 'POST',
  body: formData
});

const result = await response.json();
console.log('Найденные переменные:', result.template.variables);
```

**Генерация документа:**
```javascript
const response = await fetch('http://localhost:8000/api/render', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    template_id: 'template-001',
    data: {
      фамилия_клиента: 'Петров',
      дата_договора: '12.01.2026'
    }
  })
});

const result = await response.json();
// Скачать документ
window.location.href = result.file_url;
```

**Массовая генерация:**
```javascript
const response = await fetch('http://localhost:8000/api/render/batch', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    template_id: 'template-001',
    data: [
      { фамилия_клиента: 'Петров', дата_договора: '12.01.2026' },
      { фамилия_клиента: 'Сидоров', дата_договора: '13.01.2026' }
    ]
  })
});

const result = await response.json();
// Скачать ZIP
window.location.href = result.file_url;
```

---

### Python (requests)

**Создание коллекции:**
```python
import requests

response = requests.post(
    'http://localhost:8000/api/collections',
    json={'name': 'Договоры 2026'}
)

collection = response.json()
collection_id = collection['id']
```

**Загрузка шаблона:**
```python
with open('договор.docx', 'rb') as f:
    files = {'file': f}
    data = {'collection_id': collection_id}
    response = requests.post(
        'http://localhost:8000/api/templates/upload',
        files=files,
        data=data
    )

template = response.json()['template']
template_id = template['id']
```

**Генерация документа:**
```python
response = requests.post(
    'http://localhost:8000/api/render',
    json={
        'template_id': template_id,
        'data': {
            'фамилия_клиента': 'Петров',
            'дата_договора': '12.01.2026'
        }
    }
)

result = response.json()
# Скачать файл
file_response = requests.get(result['file_url'])
with open('договор_петров.docx', 'wb') as f:
    f.write(file_response.content)
```

---

### cURL

**Создание коллекции:**
```bash
curl -X POST http://localhost:8000/api/collections \
  -H "Content-Type: application/json" \
  -d '{"name": "Договоры 2026"}'
```

**Загрузка шаблона:**
```bash
curl -X POST http://localhost:8000/api/templates/upload \
  -F "collection_id=550e8400-e29b-41d4-a716-446655440000" \
  -F "file=@договор.docx"
```

**Генерация документа:**
```bash
curl -X POST http://localhost:8000/api/render \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": "template-001",
    "data": {
      "фамилия_клиента": "Петров",
      "дата_договора": "12.01.2026"
    }
  }' \
  -o результат.docx
```

---

## ⚠️ Обработка ошибок

### Стандартный формат ошибки

```json
{
  "status": "error",
  "code": "VALIDATION_ERROR",
  "message": "Ошибка валидации",
  "details": {
    "field": "дата_договора",
    "error": "Неверный формат даты"
  }
}
```

### Коды ошибок

| Код | HTTP Status | Описание |
|-----|------------|---------|
| VALIDATION_ERROR | 400 | Ошибка валидации входных данных |
| NOT_FOUND | 404 | Ресурс не найден |
| DUPLICATE_ENTRY | 400 | Ресурс уже существует |
| FILE_ERROR | 400 | Ошибка при обработке файла |
| INVALID_FORMAT | 400 | Неверный формат данных |
| PROCESSING_ERROR | 500 | Ошибка при обработке |
| UNKNOWN_ERROR | 500 | Неизвестная ошибка |

### Рекомендации для обработки

```javascript
async function apiCall(url, options) {
  try {
    const response = await fetch(url, options);
    
    if (!response.ok) {
      const error = await response.json();
      
      switch(response.status) {
        case 400:
          console.error('Ошибка валидации:', error.message);
          // Показать ошибку пользователю
          break;
        case 404:
          console.error('Ресурс не найден');
          // Перенаправить или показать 404
          break;
        case 500:
          console.error('Ошибка сервера');
          // Попробовать позже
          break;
      }
      throw error;
    }
    
    return await response.json();
  } catch(error) {
    console.error('API Error:', error);
    throw error;
  }
}
```

---

## 📊 Типы данных

### VariableType

```
"text"      - текстовое поле
"date"      - дата
"checkbox"  - галочка (true/false)
```

### DateTime Format

```
ISO 8601: 2026-01-12T15:30:00.000Z
Отображение: 12.01.2026
```

### UUID Format

```
550e8400-e29b-41d4-a716-446655440000
(стандартный UUID v4)
```

---

**Дополнительно:**
- Руководство пользователя: [Руководство пользователя](./02_USER_GUIDE.md)
- Технические детали: [Технические детали](./06_TECHNICAL.md)
- Типы переменных: [Типы переменных](./04_VARIABLE_TYPES.md)

---

**Время чтения**: 25 минут  
**Уровень**: Средний-Продвинутый

import os
import shutil
import zipfile
import re
import json
import uuid
import hashlib
from datetime import datetime
from copy import deepcopy
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum

from lxml import etree
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# -------------------------------------------------------
# Конфигурация
# -------------------------------------------------------
BASE_STORAGE_PATH = Path("./docx_templates_storage")
BASE_STORAGE_PATH.mkdir(exist_ok=True)

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{%s}" % WORD_NS

# Регулярные выражения ДЛЯ РУССКОГО ТЕКСТА
# Замените эти строки:
CHECKBOX_RE = re.compile(r"\{\{\s*checkbox\s*:\s*(.*?)\s*\}\}")
TEXT_VARIABLE_RE = re.compile(r"\{\{\s*text\s*:\s*(.*?)\s*\}\}")

# На эти:
CHECKBOX_RE = re.compile(r'\{\{\s*checkbox\s*:\s*([^{}]+?)\s*\}\}')
TEXT_VARIABLE_RE = re.compile(r'\{\{\s*text\s*:\s*([^{}]+?)\s*\}\}')

# -------------------------------------------------------
# Модели данных
# -------------------------------------------------------
class VariableType(str, Enum):
    TEXT = "text"
    CHECKBOX = "checkbox"

@dataclass
class VariableMetadata:
    display_name: str = ""
    description: str = ""
    required: bool = False
    validation_regex: Optional[str] = None
    default_value: Any = ""
    ui_order: int = 0
    category: str = "general"

@dataclass
class TemplateVariable:
    name: str
    type: VariableType
    template_string: str
    context: List[str]
    occurrences: int = 1
    metadata: Optional[VariableMetadata] = None
    value: Any = ""
    
    def to_dict(self):
        data = asdict(self)
        data['type'] = self.type.value
        if self.metadata:
            data['metadata'] = asdict(self.metadata)
        return data

@dataclass
class DocumentTemplate:
    id: str
    name: str
    original_filename: str
    collection_id: str
    variables: Dict[str, TemplateVariable]
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    file_hash: str = ""
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self):
        data = asdict(self)
        data['variables'] = {k: v.to_dict() for k, v in self.variables.items()}
        return data

@dataclass
class Collection:
    id: str
    name: str
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
    templates: List[str] = None
    shared_variables_file: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at
        if self.templates is None:
            self.templates = []
    
    def to_dict(self):
        return asdict(self)

# -------------------------------------------------------
# Хранилище данных
# -------------------------------------------------------
class Storage:
    def __init__(self):
        self.collections: Dict[str, Collection] = {}
        self.templates: Dict[str, DocumentTemplate] = {}
        self._load_from_disk()
    
    def _load_from_disk(self):
        collections_file = BASE_STORAGE_PATH / "collections.json"
        if collections_file.exists():
            with open(collections_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for coll_id, coll_data in data.items():
                    self.collections[coll_id] = Collection(**coll_data)
        
        templates_file = BASE_STORAGE_PATH / "templates.json"
        if templates_file.exists():
            with open(templates_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for temp_id, temp_data in data.items():
                    # Восстанавливаем переменные
                    variables = {}
                    for var_name, var_data in temp_data.get('variables', {}).items():
                        var_type = VariableType(var_data['type'])
                        metadata = None
                        if var_data.get('metadata'):
                            metadata = VariableMetadata(**var_data['metadata'])
                        
                        variables[var_name] = TemplateVariable(
                            name=var_name,
                            type=var_type,
                            template_string=var_data['template_string'],
                            context=var_data['context'],
                            occurrences=var_data['occurrences'],
                            metadata=metadata,
                            value=var_data.get('value', '')
                        )
                    
                    temp_data['variables'] = variables
                    self.templates[temp_id] = DocumentTemplate(**temp_data)
    
    def _save_to_disk(self):
        collections_data = {k: asdict(v) for k, v in self.collections.items()}
        with open(BASE_STORAGE_PATH / "collections.json", 'w', encoding='utf-8') as f:
            json.dump(collections_data, f, ensure_ascii=False, indent=2)
        
        templates_data = {}
        for temp_id, template in self.templates.items():
            data = asdict(template)
            data['variables'] = {k: v.to_dict() for k, v in template.variables.items()}
            templates_data[temp_id] = data
        
        with open(BASE_STORAGE_PATH / "templates.json", 'w', encoding='utf-8') as f:
            json.dump(templates_data, f, ensure_ascii=False, indent=2)
    
    def create_collection(self, name: str, description: str = "") -> Collection:
        collection_id = str(uuid.uuid4())
        collection = Collection(
            id=collection_id,
            name=name,
            description=description,
            shared_variables_file=f"variables_{collection_id}.json"
        )
        self.collections[collection_id] = collection
        self._save_to_disk()
        return collection
    
    def get_collection(self, collection_id: str) -> Optional[Collection]:
        return self.collections.get(collection_id)
    
    def get_collection_templates(self, collection_id: str) -> List[DocumentTemplate]:
        collection = self.get_collection(collection_id)
        if not collection:
            return []
        return [self.templates[temp_id] for temp_id in collection.templates 
                if temp_id in self.templates]
    
    def add_template_to_collection(self, collection_id: str, template: DocumentTemplate) -> bool:
        collection = self.get_collection(collection_id)
        if not collection:
            return False
        
        if template.id not in collection.templates:
            collection.templates.append(template.id)
            collection.updated_at = datetime.now().isoformat()
            self.templates[template.id] = template
            self._save_to_disk()
            return True
        return False

    def load_shared_variables(self, collection_id: str) -> Dict[str, Any]:
        """Загрузка общих переменных коллекции"""
        collection = self.get_collection(collection_id)
        if not collection:
            return {}
        
        vars_file = BASE_STORAGE_PATH / collection.shared_variables_file
        if not vars_file.exists():
            return {}
        
        try:
            with open(vars_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('variables', {})
        except:
            return {}
    
    def save_shared_variables(self, collection_id: str, variables: Dict[str, Any]) -> bool:
        """Сохранение общих переменных коллекции"""
        collection = self.get_collection(collection_id)
        if not collection:
            return False
        
        vars_file = BASE_STORAGE_PATH / collection.shared_variables_file
        
        data = {
            "collection_id": collection_id,
            "updated_at": datetime.now().isoformat(),
            "variables": variables
        }
        
        with open(vars_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return True

    def get_collection_shared_variables_map(self, collection_id: str) -> Dict[str, Dict]:
        """Возвращает карту общих переменных коллекции с объединением значений"""
        collection = self.get_collection(collection_id)
        if not collection:
            return {}
        
        # Собираем все переменные из всех шаблонов
        all_variables_map = {}
        
        for template_id in collection.templates:
            template = self.templates.get(template_id)
            if template and template.variables:
                for var_name, variable in template.variables.items():
                    if var_name not in all_variables_map:
                        all_variables_map[var_name] = {
                            'variable': variable,
                            'templates': [template_id],
                            'occurrences': variable.occurrences
                        }
                    else:
                        # Добавляем шаблон к списку
                        if template_id not in all_variables_map[var_name]['templates']:
                            all_variables_map[var_name]['templates'].append(template_id)
                        
                        # Суммируем occurrences
                        all_variables_map[var_name]['occurrences'] += variable.occurrences
        
        return all_variables_map

# -------------------------------------------------------
# Обработчик документов
# -------------------------------------------------------
class DocumentProcessor:
    def __init__(self):
        self.storage = Storage()
    
    def calculate_file_hash(self, file_path: Path) -> str:
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    
    def _scan_document_xml(self, doc_path: str) -> Dict[str, Any]:
            """Универсальное сканирование XML - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
            tree = etree.parse(doc_path)
            root = tree.getroot()
            
            structure = {
                'text_variables': {},
                'checkboxes': {},
                'metadata': {
                    'total_text_variables': 0,
                    'total_checkboxes': 0,
                    'unique_text_variables': 0,
                    'unique_checkboxes': 0
                }
            }
            
            print(f"Начинаем сканирование документа...")
            
            # Метод 1: Ищем во всем XML как тексте (самый надежный способ)
            xml_text = etree.tostring(root, encoding='unicode', pretty_print=False)
            
            print(f"Длина XML текста: {len(xml_text)} символов")
            
            # ДЕБАГ: Сохраняем XML для анализа
            debug_file = BASE_STORAGE_PATH / "debug_xml.xml"
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(xml_text)
            print(f"XML сохранен для отладки: {debug_file}")
            
            # ДЕБАГ: Ищем любые фигурные скобки
            all_curly_braces = re.findall(r'\{\{[^}]*\}\}', xml_text)
            print(f"Найдено всех шаблонов с фигурными скобками: {len(all_curly_braces)}")
            for i, match in enumerate(all_curly_braces[:20]):  # Покажем первые 20
                print(f"  [{i}] '{match}'")
            
            # Используем более гибкие регулярные выражения
            FLEXIBLE_CHECKBOX_RE = re.compile(r'\{\{\s*checkbox\s*:\s*([^{}]+?)\s*\}\}')
            FLEXIBLE_TEXT_RE = re.compile(r'\{\{\s*text\s*:\s*([^{}]+?)\s*\}\}')
            
            # Текстовые переменные
            text_matches = list(FLEXIBLE_TEXT_RE.finditer(xml_text))
            print(f"Найдено текстовых переменных по regex: {len(text_matches)}")
            
            for match in text_matches:
                var_name = match.group(1).strip()
                print(f"  Текстовый шаблон: '{match.group(0)}' -> имя: '{var_name}'")
                
                if var_name:
                    if var_name not in structure['text_variables']:
                        # Получаем контекст вокруг найденного шаблона
                        start = max(0, match.start() - 100)
                        end = min(len(xml_text), match.end() + 100)
                        context = xml_text[start:end]
                        # Очищаем от XML тегов
                        context = re.sub(r'<[^>]+>', ' ', context)
                        context = re.sub(r'\s+', ' ', context).strip()[:200]
                        
                        structure['text_variables'][var_name] = {
                            'count': 1,
                            'contexts': [context if context else "Найдено в документе"],
                            'value': ''
                        }
                    else:
                        structure['text_variables'][var_name]['count'] += 1
            
            # Чекбоксы
            checkbox_matches = list(FLEXIBLE_CHECKBOX_RE.finditer(xml_text))
            print(f"Найдено чекбоксов по regex: {len(checkbox_matches)}")
            
            for match in checkbox_matches:
                cb_name = match.group(1).strip()
                print(f"  Чекбокс шаблон: '{match.group(0)}' -> имя: '{cb_name}'")
                
                if cb_name:
                    if cb_name not in structure['checkboxes']:
                        # Получаем контекст вокруг найденного шаблона
                        start = max(0, match.start() - 100)
                        end = min(len(xml_text), match.end() + 100)
                        context = xml_text[start:end]
                        # Очищаем от XML тегов
                        context = re.sub(r'<[^>]+>', ' ', context)
                        context = re.sub(r'\s+', ' ', context).strip()[:200]
                        
                        structure['checkboxes'][cb_name] = {
                            'count': 1,
                            'contexts': [context if context else "Найдено в документе"],
                            'checked_by_default': False
                        }
                    else:
                        structure['checkboxes'][cb_name]['count'] += 1
            
            # Если ничего не нашли, попробуем альтернативные методы
            if not structure['text_variables'] and not structure['checkboxes']:
                print("\nПервый метод не нашел переменных. Пробуем альтернативные методы...")
                
                # Метод 2: Ищем в отдельных w:t элементах (на случай, если шаблон разбит)
                all_text_elements = root.findall(".//w:t", namespaces={"w": WORD_NS})
                print(f"Метод 2: Поиск в {len(all_text_elements)} w:t элементах...")
                
                current_text = ""
                for t_elem in all_text_elements:
                    text = t_elem.text if t_elem.text is not None else ""
                    current_text += text
                    
                    # Если текст достаточно длинный или закончился run, проверяем его
                    if len(current_text) > 100 or not text:
                        # Проверяем собранный текст на шаблоны
                        text_matches = list(FLEXIBLE_TEXT_RE.finditer(current_text))
                        for match in text_matches:
                            var_name = match.group(1).strip()
                            if var_name and var_name not in structure['text_variables']:
                                structure['text_variables'][var_name] = {
                                    'count': 1,
                                    'contexts': [current_text[:200]],
                                    'value': ''
                                }
                        
                        checkbox_matches = list(FLEXIBLE_CHECKBOX_RE.finditer(current_text))
                        for match in checkbox_matches:
                            cb_name = match.group(1).strip()
                            if cb_name and cb_name not in structure['checkboxes']:
                                structure['checkboxes'][cb_name] = {
                                    'count': 1,
                                    'contexts': [current_text[:200]],
                                    'checked_by_default': False
                                }
                        
                        current_text = ""
            
            # Обновляем метаданные
            structure['metadata']['unique_text_variables'] = len(structure['text_variables'])
            structure['metadata']['unique_checkboxes'] = len(structure['checkboxes'])
            structure['metadata']['total_text_variables'] = sum(
                v['count'] for v in structure['text_variables'].values()
            )
            structure['metadata']['total_checkboxes'] = sum(
                v['count'] for v in structure['checkboxes'].values()
            )
            
            print(f"\nИтоги сканирования:")
            print(f"  Уникальных текстовых переменных: {structure['metadata']['unique_text_variables']}")
            print(f"  Уникальных чекбоксов: {structure['metadata']['unique_checkboxes']}")
            
            if structure['text_variables']:
                print("\nНайденные текстовые переменные:")
                for var_name, var_data in structure['text_variables'].items():
                    print(f"  '{var_name}' (встречается {var_data['count']} раз)")
            
            if structure['checkboxes']:
                print("\nНайденные чекбоксы:")
                for cb_name, cb_data in structure['checkboxes'].items():
                    print(f"  '{cb_name}' (встречается {cb_data['count']} раз)")
            
            if not structure['text_variables'] and not structure['checkboxes']:
                print("\n⚠ ВНИМАНИЕ: Переменные не найдены!")
                print("Возможные причины:")
                print("  1. В документе нет шаблонов {{text:...}} или {{checkbox:...}}")
                print("  2. Шаблоны записаны с другими пробелами/символами")
                print("  3. Документ содержит специальные символы или форматирование")
                print("\nПроверьте файл debug_xml.xml для анализа структуры документа")
            
            return structure

    def scan_template(self, docx_path: Path) -> Tuple[Dict[str, TemplateVariable], str]:
        """Универсальное сканирование шаблона"""
        workdir = BASE_STORAGE_PATH / f"temp_{uuid.uuid4()}"
        
        try:
            # Распаковываем DOCX
            self._unzip_docx(docx_path, workdir)
            doc_xml = workdir / "word" / "document.xml"
            
            # Сканируем
            structure = self._scan_document_xml(str(doc_xml))
            
            # Преобразуем в TemplateVariable
            variables = {}
            
            for var_name, var_data in structure['text_variables'].items():
                variables[var_name] = TemplateVariable(
                    name=var_name,
                    type=VariableType.TEXT,
                    template_string=f"{{{{text:{var_name}}}}}",
                    context=var_data.get('contexts', []),
                    occurrences=var_data.get('count', 1),
                    value=var_data.get('value', '')
                )
            
            for cb_name, cb_data in structure['checkboxes'].items():
                variables[cb_name] = TemplateVariable(
                    name=cb_name,
                    type=VariableType.CHECKBOX,
                    template_string=f"{{{{checkbox:{cb_name}}}}}",
                    context=cb_data.get('contexts', []),
                    occurrences=cb_data.get('count', 1),
                    value=cb_data.get('checked_by_default', False)
                )
            
            file_hash = self.calculate_file_hash(docx_path)
            
            print(f"Найдено переменных: {len(variables)}")
            for var_name, var in variables.items():
                print(f"  - {var.name} ({var.type.value})")
            
            return variables, file_hash
            
        finally:
            if workdir.exists():
                shutil.rmtree(workdir)
    
    
    # Добавьте в класс DocumentProcessor после метода scan_template
    def _process_xml_file_for_replacement(self, xml_file: Path, variables: Dict[str, Any]) -> bool:
        """Обработка XML файла для замены переменных с использованием lxml"""
        try:
            # Парсим XML файл
            parser = etree.XMLParser(remove_blank_text=False)
            tree = etree.parse(str(xml_file), parser)
            root = tree.getroot()
            
            # Разделяем переменные на текстовые и чекбоксы
            text_variables = {}
            checkbox_values = {}
            
            for var_name, var_value in variables.items():
                template = self.storage.templates
                # Определяем тип переменной
                is_checkbox = False
                
                # Проверяем по всем шаблонам, какой это тип переменной
                for template_id, tmpl in template.items():
                    if var_name in tmpl.variables:
                        if tmpl.variables[var_name].type == VariableType.CHECKBOX:
                            is_checkbox = True
                        break
                
                if is_checkbox:
                    checkbox_values[var_name] = bool(var_value)
                else:
                    text_variables[var_name] = str(var_value)
            
            statistics = {
                'text_variables': 0,
                'checkboxes': 0,
                'missing_variables': []
            }
            
            # 1. Обработка текстовых переменных
            if text_variables:
                text_replaced = 0
                for p in root.findall(".//w:p", namespaces={"w": WORD_NS}):
                    text_replaced += self._process_templates_in_paragraph(
                        p, TEXT_VARIABLE_RE, self._process_text_template, text_variables
                    )
                
                statistics['text_variables'] = text_replaced
                print(f"Обработано текстовых переменных: {text_replaced}")
                
                # Перепарсим для следующего этапа
                xml_content = etree.tostring(root, encoding='unicode', pretty_print=True)
                root = etree.fromstring(xml_content.encode('utf-8'))
            
            # 2. Обработка чекбоксов
            if checkbox_values:
                checkbox_replaced = 0
                for p in root.findall(".//w:p", namespaces={"w": WORD_NS}):
                    checkbox_replaced += self._process_templates_in_paragraph(
                        p, CHECKBOX_RE, self._process_checkbox_template, checkbox_values
                    )
                
                statistics['checkboxes'] = checkbox_replaced
                print(f"Обработано чекбоксов: {checkbox_replaced}")
            
            # Сохраняем обработанный XML
            tree = etree.ElementTree(root)
            tree.write(str(xml_file), xml_declaration=True, encoding="UTF-8", pretty_print=True)
            
            return statistics['text_variables'] + statistics['checkboxes'] > 0
            
        except Exception as e:
            print(f"Ошибка при обработке файла {xml_file}: {e}")
            return False
    
    def _process_templates_in_paragraph(self, p, template_re, processor_func, context=None):
        """Обрабатывает шаблоны в параграфе с помощью указанной функции-процессора"""
        # Получаем все run-ы в параграфе
        runs = p.findall("w:r", namespaces={"w": WORD_NS})
        if not runs:
            return 0
        
        # Собираем весь текст параграфа с информацией о пробелах
        combined = ""
        run_info = []  # Храним (run_element, run_text, start_pos_in_combined, end_pos_in_combined)
        
        current_pos = 0
        for run in runs:
            # Собираем ВСЕ текстовые элементы из run
            text_parts = []
            for t_elem in run.findall("w:t", namespaces={"w": WORD_NS}):
                text = t_elem.text if t_elem.text is not None else ""
                text_parts.append(text)
            
            run_text = "".join(text_parts)
            run_start = current_pos
            run_end = current_pos + len(run_text)
            
            combined += run_text
            run_info.append((run, run_text, run_start, run_end))
            
            current_pos = run_end
        
        # Ищем все шаблоны в параграфе
        matches = list(re.finditer(template_re, combined))
        
        if not matches:
            return 0
        
        # Создаем список для нового содержимого параграфа
        new_children = []
        current_pos = 0
        
        for match in matches:
            template_full = match.group(0)  # Весь шаблон
            variable_name = match.group(1).strip()  # Имя переменной
            match_start, match_end = match.span()
            
            # 1. Добавляем текст ПЕРЕД шаблоном (если есть)
            if match_start > current_pos:
                text_before = combined[current_pos:match_start]
                if text_before:
                    # Находим run-ы, которые содержат этот текст
                    for run_idx, (run, run_text, run_start, run_end) in enumerate(run_info):
                        # Если run пересекается с текстом перед шаблоном
                        if not (run_end <= current_pos or run_start >= match_start):
                            run_copy = etree.Element(W+"r")
                            
                            # Копируем форматирование (если есть)
                            rPr = run.find(W+"rPr")
                            if rPr is not None:
                                # Создаем копию rPr элемента
                                rPr_copy = etree.Element(W+"rPr")
                                # Копируем все дочерние элементы rPr
                                for child in rPr:
                                    rPr_copy.append(deepcopy(child))
                                # Копируем атрибуты
                                for attr_name, attr_value in rPr.attrib.items():
                                    rPr_copy.set(attr_name, attr_value)
                                run_copy.append(rPr_copy)
                            
                            # Создаем текстовый элемент
                            t_elem = etree.SubElement(run_copy, W+"t")
                            
                            # Определяем, какой текст из этого run нужно взять
                            clip_start = max(current_pos, run_start) - run_start
                            clip_end = min(match_start, run_end) - run_start
                            clipped_text = run_text[clip_start:clip_end]
                            
                            # Проверяем, нужно ли сохранять пробелы
                            if clipped_text and (clipped_text.startswith(' ') or clipped_text.endswith(' ')):
                                t_elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                            
                            t_elem.text = clipped_text
                            new_children.append(run_copy)
            
            # 2. Добавляем сгенерированный элемент (чекбокс или текст)
            generated_elements = processor_func(variable_name, run_info, match_start, context)
            if generated_elements:  # Если процессор вернул элементы
                new_children.extend(generated_elements)
            
            current_pos = match_end
        
        # 3. Добавляем текст ПОСЛЕ последнего шаблона (если есть)
        if current_pos < len(combined):
            text_after = combined[current_pos:]
            if text_after:
                # Находим run-ы, которые содержат текст после шаблонов
                for run_idx, (run, run_text, run_start, run_end) in enumerate(run_info):
                    if not (run_end <= current_pos or run_start >= len(combined)):
                        run_copy = etree.Element(W+"r")
                        
                        rPr = run.find(W+"rPr")
                        if rPr is not None:
                            # Создаем копию rPr элемента
                            rPr_copy = etree.Element(W+"rPr")
                            for child in rPr:
                                rPr_copy.append(deepcopy(child))
                            for attr_name, attr_value in rPr.attrib.items():
                                rPr_copy.set(attr_name, attr_value)
                            run_copy.append(rPr_copy)
                        
                        t_elem = etree.SubElement(run_copy, W+"t")
                        
                        clip_start = max(current_pos, run_start) - run_start
                        clip_end = len(combined) - run_start
                        clipped_text = run_text[clip_start:clip_end]
                        
                        if clipped_text and (clipped_text.startswith(' ') or clipped_text.endswith(' ')):
                            t_elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                        
                        t_elem.text = clipped_text
                        new_children.append(run_copy)
        
        # 4. Если нашли шаблоны, заменяем содержимое параграфа
        if new_children:
            # Удаляем все существующие дочерние элементы параграфа
            for child in list(p):
                p.remove(child)
            
            # Добавляем новые элементы
            for child in new_children:
                p.append(child)
            
            return len(matches)
        
        return 0
    
    def _process_checkbox_template(self, variable_name, run_info, position, context):
        """Обработчик для чекбоксов"""
        checkbox_text = variable_name
        
        # Получаем значение из контекста
        checked_by_default = False
        if context and variable_name in context:
            checked_by_default = bool(context[variable_name])
        
        # Определяем форматирование из первого run, который содержит шаблон
        for run, run_text, run_start, run_end in run_info:
            if run_start <= position < run_end:
                rPr = run.find(W+"rPr")
                if rPr is not None:
                    # Извлекаем шрифт и размер из форматирования
                    font_elem = rPr.find(W+"rFonts")
                    size_elem = rPr.find(W+"sz")
                    
                    font_name = "Calibri"  # Стандартный шрифт Word
                    font_size = 22  # Стандартный размер по умолчанию (11 points)
                    
                    if font_elem is not None:
                        font_name = font_elem.get(W+"ascii") or font_elem.get(W+"hAnsi") or "Calibri"
                    
                    if size_elem is not None:
                        try:
                            # Размер уже в half-points, используем как есть
                            font_size = int(size_elem.get(W+"val", "22"))
                        except:
                            font_size = 22  # 11 points по умолчанию
                    
                    return self._make_form_checkbox(checkbox_text, font_name=font_name, 
                                                   font_size=font_size, checked=checked_by_default)
                break
        
        return self._make_form_checkbox(checkbox_text, checked=checked_by_default)
    
    def _process_text_template(self, variable_name, run_info, position, context):
        """Обработчик для текстовых шаблонов - подставляет значение переменной"""
        if context is None or variable_name not in context:
            print(f"⚠ Переменная '{variable_name}' не найдена в контексте")
            return []
        
        value = context[variable_name]
        
        # Определяем форматирование из run, который содержит шаблон
        for run, run_text, run_start, run_end in run_info:
            if run_start <= position < run_end:
                rPr = run.find(W+"rPr")
                return [self._make_text_element(str(value), rPr)]
        
        return [self._make_text_element(str(value))]
    
    def _make_form_checkbox(self, name_text: str, font_name="Calibri", font_size=22, checked=False):
        """
        Простая и рабочая версия Legacy Checkbox
        Word сам правильно отрисует чекбокс с размером по умолчанию
        """
        runs = []
        
        # 1) fldChar begin
        r_begin = etree.Element(W+"r")
        fld_begin = etree.SubElement(r_begin, W+"fldChar", {W+"fldCharType":"begin"})
        ffData = etree.SubElement(fld_begin, W+"ffData")
        etree.SubElement(ffData, W+"enabled")
        checkBox = etree.SubElement(ffData, W+"checkBox")
        etree.SubElement(checkBox, W+"sizeAuto")  # Авторазмер - ВАЖНО!
        default_value = "1" if checked else "0"
        etree.SubElement(checkBox, W+"default", {W+"val": default_value})
        etree.SubElement(ffData, W+"name", {W+"val": name_text})
        runs.append(r_begin)

        # 2) instrText
        r_instr = etree.Element(W+"r")
        instr = etree.SubElement(r_instr, W+"instrText")
        instr.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        instr.text = " FORMCHECKBOX "
        runs.append(r_instr)

        # 3) fldChar end
        r_end = etree.Element(W+"r")
        etree.SubElement(r_end, W+"fldChar", {W+"fldCharType":"end"})
        runs.append(r_end)

        # 4) текст справа
        r_text = etree.Element(W+"r")
        t = etree.SubElement(r_text, W+"t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = " " + name_text
        runs.append(r_text)

        return runs
    
    def _make_text_element(self, text_content: str, rPr_element=None):
        """Создает run с текстом и форматированием"""
        run = etree.Element(W+"r")
        
        if rPr_element is not None:
            # Копируем форматирование
            rPr_copy = etree.Element(W+"rPr")
            for child in rPr_element:
                rPr_copy.append(deepcopy(child))
            for attr_name, attr_value in rPr_element.attrib.items():
                rPr_copy.set(attr_name, attr_value)
            run.append(rPr_copy)
        
        t_elem = etree.SubElement(run, W+"t")
        
        # Проверяем пробелы в начале или конце
        if text_content.startswith(' ') or text_content.endswith(' '):
            t_elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        
        t_elem.text = text_content
        return run
    
    def render_document(self, template_id: str, variables: Dict[str, Any]) -> Path:
        """Рендеринг одного документа"""
        template = self.storage.templates.get(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        
        # Подготавливаем рабочую директорию
        workdir = BASE_STORAGE_PATH / f"render_{uuid.uuid4()}"
        templates_dir = BASE_STORAGE_PATH / "templates" / template.collection_id
        template_path = templates_dir / f"{template.id}.docx"
        
        # Загружаем общие переменные коллекции
        shared_vars = self.storage.load_shared_variables(template.collection_id)
        
        # Подготавливаем значения переменных
        final_variables = {}
        
        # 1. Используем значения из запроса (если есть)
        for var_name, value in variables.items():
            if var_name in template.variables:
                final_variables[var_name] = value
        
        # 2. Для оставшихся переменных используем общие значения или значения из шаблона
        for var_name, var_data in template.variables.items():
            if var_name not in final_variables:
                # Проверяем общие переменные
                if var_name in shared_vars:
                    final_variables[var_name] = shared_vars[var_name]
                else:
                    # Используем сохраненное значение
                    if var_data.type == VariableType.CHECKBOX:
                        final_variables[var_name] = bool(var_data.value)
                    else:
                        final_variables[var_name] = str(var_data.value)
        
        print(f"Рендеринг шаблона '{template.name}' с переменными:")
        for k, v in final_variables.items():
            print(f"  {k}: {v}")
        
        try:
            # Распаковываем DOCX
            self._unzip_docx(template_path, workdir)
            
            # Обрабатываем основной документ
            doc_xml = workdir / "word" / "document.xml"
            if doc_xml.exists():
                self._process_xml_file_for_replacement(doc_xml, final_variables)
            
            # Также обрабатываем файлы заголовков и колонтитулов
            for xml_file in workdir.glob("**/*.xml"):
                if xml_file.name.startswith(('header', 'footer')):
                    self._process_xml_file_for_replacement(xml_file, final_variables)
            
            # Создаем выходной файл
            output_dir = BASE_STORAGE_PATH / "rendered"
            output_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = output_dir / f"rendered_{template.name}_{timestamp}.docx"
            
            # Упаковываем обратно в DOCX
            self._rezip_docx(workdir, output_path)
            
            print(f"Документ успешно отрендерен: {output_path}")
            return output_path
            
        except Exception as e:
            print(f"Ошибка при рендеринге: {e}")
            raise
            
        finally:
            if workdir.exists():
                shutil.rmtree(workdir)
    
    def render_batch(self, collection_id: str, template_ids: List[str], 
                    variables: Dict[str, Any]) -> Path:
        """Пакетный рендеринг документов"""
        collection = self.storage.get_collection(collection_id)
        if not collection:
            raise ValueError(f"Collection {collection_id} not found")
        
        # Проверяем шаблоны
        templates_to_render = []
        for template_id in template_ids:
            template = self.storage.templates.get(template_id)
            if template and template.collection_id == collection_id:
                templates_to_render.append(template)
        
        if not templates_to_render:
            raise ValueError("No valid templates to render")
        
        print(f"Пакетный рендеринг {len(templates_to_render)} документов")
        
        # Создаем временную директорию для ZIP архива
        temp_dir = BASE_STORAGE_PATH / f"batch_{uuid.uuid4()}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        rendered_files = []
        
        try:
            # Рендерим каждый документ
            for template in templates_to_render:
                try:
                    print(f"Рендеринг шаблона: {template.name}")
                    
                    # Подготавливаем переменные для этого шаблона
                    template_variables = {}
                    for var_name in template.variables.keys():
                        if var_name in variables:
                            if template.variables[var_name].type == VariableType.CHECKBOX:
                                template_variables[var_name] = bool(variables[var_name])
                            else:
                                template_variables[var_name] = str(variables[var_name])
                        else:
                            # Используем сохраненное значение
                            template_variables[var_name] = template.variables[var_name].value
                    
                    # Рендерим документ
                    rendered_path = self.render_document(template.id, template_variables)
                    
                    # Копируем в временную директорию с понятным именем
                    new_name = f"{template.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
                    new_name = re.sub(r'[<>:"/\\|?*]', '_', new_name)  # Заменяем недопустимые символы
                    new_path = temp_dir / new_name
                    shutil.copy2(rendered_path, new_path)
                    rendered_files.append(new_path)
                    
                    print(f"  Успешно: {new_name}")
                    
                except Exception as e:
                    print(f"  Ошибка при рендеринге шаблона {template.name}: {e}")
            
            if not rendered_files:
                raise ValueError("Не удалось отрендерить ни одного документа")
            
            # Создаем ZIP архив
            output_dir = BASE_STORAGE_PATH / "rendered"
            output_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            zip_path = output_dir / f"batch_{collection_id}_{timestamp}.zip"
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file_path in rendered_files:
                    zipf.write(file_path, file_path.name)
            
            print(f"Пакетный рендеринг завершен. ZIP архив: {zip_path}")
            return zip_path
            
        finally:
            # Очищаем временные файлы
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
    
    def register_template(self, collection_id: str, template_name: str, 
                         docx_file_path: Path, original_filename: str) -> DocumentTemplate:
        """Регистрация шаблона"""
        collection = self.storage.get_collection(collection_id)
        if not collection:
            raise ValueError(f"Collection {collection_id} not found")
        
        # Сканируем
        variables, file_hash = self.scan_template(docx_file_path)
        
        # Загружаем общие переменные для инициализации значений
        shared_vars = self.storage.load_shared_variables(collection_id)
        
        # Получаем существующие общие переменные коллекции
        existing_shared_vars = self.storage.get_collection_shared_variables_map(collection_id)
        
        for var_name, variable in variables.items():
            # Если переменная уже существует в коллекции, используем её значение и метаданные
            if var_name in existing_shared_vars:
                existing_var = existing_shared_vars[var_name]['variable']
                
                # Копируем значение из существующей переменной
                variable.value = existing_var.value
                
                # Копируем метаданные (если есть)
                if existing_var.metadata:
                    variable.metadata = deepcopy(existing_var.metadata)
            
            # Используем значение из общих переменных (если есть)
            elif var_name in shared_vars:
                variable.value = shared_vars[var_name]
        
        # Сохраняем файл
        template_id = str(uuid.uuid4())
        templates_dir = BASE_STORAGE_PATH / "templates" / collection_id
        templates_dir.mkdir(parents=True, exist_ok=True)
        
        template_file_path = templates_dir / f"{template_id}.docx"
        shutil.copy2(docx_file_path, template_file_path)
        
        # Создаем объект
        template = DocumentTemplate(
            id=template_id,
            name=template_name,
            original_filename=original_filename,
            collection_id=collection_id,
            variables=variables,
            file_hash=file_hash,
            metadata={
                "file_size": os.path.getsize(docx_file_path),
                "uploaded_at": datetime.now().isoformat()
            }
        )
        
        # Добавляем в коллекцию
        self.storage.add_template_to_collection(collection_id, template)
        
        return template
    
    def _unzip_docx(self, src, dst):
        if os.path.exists(dst):
            shutil.rmtree(dst)
        os.makedirs(dst)
        with zipfile.ZipFile(src, "r") as z:
            z.extractall(dst)
    
    def _rezip_docx(self, src_dir, dst_file):
        with zipfile.ZipFile(dst_file, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(src_dir):
                for file in files:
                    full = os.path.join(root, file)
                    rel = os.path.relpath(full, src_dir)
                    z.write(full, rel)

# -------------------------------------------------------
# FastAPI приложение
# -------------------------------------------------------
app = FastAPI(title="DOCX Template API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

processor = DocumentProcessor()

# -------------------------------------------------------
# API Endpoints
# -------------------------------------------------------
@app.get("/")
async def root():
    return {"message": "DOCX Template API v2.0", "status": "running"}

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "collections_count": len(processor.storage.collections),
        "templates_count": len(processor.storage.templates)
    }

@app.post("/api/collections")
async def create_collection(name: str = Form(...), description: str = Form("")):
    """Создание коллекции"""
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
    """Получение коллекций"""
    collections = list(processor.storage.collections.values())
    return [c.to_dict() for c in collections]

@app.get("/api/collections/{collection_id}")
async def get_collection(collection_id: str):
    """Получение коллекции"""
    collection = processor.storage.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection.to_dict()

@app.post("/api/collections/{collection_id}/templates")
async def upload_template(
    collection_id: str,
    name: str = Form(...),
    file: UploadFile = File(...)
):
    """Загрузка шаблона"""
    try:
        # Сохраняем временный файл
        temp_dir = BASE_STORAGE_PATH / "temp_uploads"
        temp_dir.mkdir(exist_ok=True)
        temp_path = temp_dir / f"upload_{uuid.uuid4()}.docx"
        
        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # Регистрируем
        template = processor.register_template(
            collection_id=collection_id,
            template_name=name,
            docx_file_path=temp_path,
            original_filename=file.filename
        )
        
        # Удаляем временный файл
        temp_path.unlink()
        
        return JSONResponse(
            status_code=201,
            content=template.to_dict()
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/collections/{collection_id}/templates")
async def get_collection_templates(collection_id: str):
    """Получение шаблонов коллекции"""
    templates = processor.storage.get_collection_templates(collection_id)
    if not templates:
        return []
    return [t.to_dict() for t in templates]

@app.get("/api/templates/{template_id}")
async def get_template(template_id: str):
    """Получение шаблона"""
    template = processor.storage.templates.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template.to_dict()

@app.get("/api/collections/{collection_id}/variables")
async def get_collection_variables(collection_id: str):
    """Получение переменных коллекции - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
    collection = processor.storage.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    # Получаем карту общих переменных
    variables_map = processor.storage.get_collection_shared_variables_map(collection_id)
    
    # Загружаем общие значения переменных
    shared_vars = processor.storage.load_shared_variables(collection_id)
    
    # Формируем результат с объединенными переменными
    all_variables = {}
    
    for var_name, var_info in variables_map.items():
        variable = var_info['variable']
        variable_dict = variable.to_dict()
        
        # Добавляем дополнительную информацию о переменной
        variable_dict['templates_count'] = len(var_info['templates'])
        variable_dict['total_occurrences'] = var_info['occurrences']
        variable_dict['templates'] = var_info['templates']
        
        # Устанавливаем значение из общих переменных
        if var_name in shared_vars:
            variable_dict['value'] = shared_vars[var_name]
        
        all_variables[var_name] = variable_dict
    
    return {
        "collection_id": collection_id,
        "variables": all_variables,
        "shared_variables": shared_vars,
        "total_variables": len(all_variables),
        "metadata": {
            "unique_variables": len(all_variables),
            "templates_in_collection": len(collection.templates)
        }
    }

@app.put("/api/collections/{collection_id}/variables/shared")
async def update_shared_variables(collection_id: str, variables: dict):
    """Обновление общих переменных коллекции"""
    try:
        collection = processor.storage.get_collection(collection_id)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")
        
        # Сохраняем общие переменные
        shared_vars_file = BASE_STORAGE_PATH / f"variables_{collection_id}.json"
        data = {
            "collection_id": collection_id,
            "updated_at": datetime.now().isoformat(),
            "variables": variables
        }
        
        with open(shared_vars_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Обновляем значения во всех шаблонах коллекции
        for template_id in collection.templates:
            template = processor.storage.templates.get(template_id)
            if template:
                for var_name, var_value in variables.items():
                    if var_name in template.variables:
                        template.variables[var_name].value = var_value
                template.updated_at = datetime.now().isoformat()
        
        processor.storage._save_to_disk()
        
        return {"status": "success", "message": "Shared variables updated"}
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/collections/{collection_id}/variables/{variable_name}/metadata")
async def update_variable_metadata(
    collection_id: str,
    variable_name: str,
    metadata: dict
):
    """Обновление метаданных переменной"""
    try:
        collection = processor.storage.get_collection(collection_id)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")
        
        var_metadata = VariableMetadata(**metadata)
        
        # Обновляем метаданные во всех шаблонах коллекции
        updated_count = 0
        for template_id in collection.templates:
            template = processor.storage.templates.get(template_id)
            if template and variable_name in template.variables:
                template.variables[variable_name].metadata = var_metadata
                template.updated_at = datetime.now().isoformat()
                updated_count += 1
        
        if updated_count == 0:
            raise HTTPException(status_code=404, detail="Variable not found in any template")
        
        processor.storage._save_to_disk()
        
        return {"status": "success", "message": "Metadata updated", "updated_templates": updated_count}
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Добавьте после существующих эндпоинтов

# В FastAPI app после других эндпоинтов

@app.post("/api/render/single")
async def render_single_document(
    template_id: str = Form(...),
    variables_json: str = Form("{}")
):
    """Рендеринг одного документа"""
    try:
        # Парсим переменные
        variables = json.loads(variables_json)
        
        # Рендерим документ
        rendered_path = processor.render_document(template_id, variables)
        
        # Возвращаем файл
        return FileResponse(
            rendered_path,
            media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            filename=rendered_path.name
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/render/batch")
async def render_batch_documents(
    collection_id: str = Form(...),
    template_ids_json: str = Form("[]"),
    variables_json: str = Form("{}")
):
    """Пакетный рендеринг документов"""
    try:
        # Парсим данные
        template_ids = json.loads(template_ids_json)
        variables = json.loads(variables_json)
        
        # Рендерим пакет документов
        zip_path = processor.render_batch(collection_id, template_ids, variables)
        
        # Возвращаем ZIP архив
        return FileResponse(
            zip_path,
            media_type='application/zip',
            filename=zip_path.name
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Альтернативный вариант с JSON для фронтенда
@app.post("/api/render/single/json")
async def render_single_document_json(data: dict):
    """Рендеринг одного документа (JSON версия)"""
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

@app.post("/api/render/batch/json")
async def render_batch_documents_json(data: dict):
    """Пакетный рендеринг документов (JSON версия)"""
    try:
        collection_id = data.get('collection_id')
        template_ids = data.get('template_ids', [])
        variables = data.get('variables', {})
        
        if not collection_id:
            raise HTTPException(status_code=400, detail="collection_id is required")
        
        if not template_ids:
            raise HTTPException(status_code=400, detail="template_ids is required")
        
        zip_path = processor.render_batch(collection_id, template_ids, variables)
        
        return FileResponse(
            zip_path,
            media_type='application/zip',
            filename=zip_path.name
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/collections/{collection_id}/variables/stats")
async def get_collection_variables_stats(collection_id: str):
    """Получение статистики по переменным коллекции"""
    collection = processor.storage.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    
    variables_map = processor.storage.get_collection_shared_variables_map(collection_id)
    
    stats = {
        "total_unique_variables": len(variables_map),
        "variables_by_template_count": {},
        "variables_by_type": {
            "text": 0,
            "checkbox": 0
        }
    }
    
    for var_name, var_info in variables_map.items():
        variable = var_info['variable']
        
        # Считаем по количеству шаблонов
        templates_count = len(var_info['templates'])
        if templates_count not in stats["variables_by_template_count"]:
            stats["variables_by_template_count"][templates_count] = 0
        stats["variables_by_template_count"][templates_count] += 1
        
        # Считаем по типу
        if variable.type == VariableType.TEXT:
            stats["variables_by_type"]["text"] += 1
        else:
            stats["variables_by_type"]["checkbox"] += 1
    
    return {
        "collection_id": collection_id,
        "templates_count": len(collection.templates),
        "stats": stats
    }
# -------------------------------------------------------
# Запуск
# -------------------------------------------------------
if __name__ == "__main__":
    # Создаем директории
    (BASE_STORAGE_PATH / "templates").mkdir(exist_ok=True)
    (BASE_STORAGE_PATH / "temp_uploads").mkdir(exist_ok=True)
    (BASE_STORAGE_PATH / "rendered").mkdir(exist_ok=True)
    
    print("=" * 60)
    print("DOCX Template API v2.0")
    print("=" * 60)
    print(f"Данные хранятся в: {BASE_STORAGE_PATH}")
    print(f"API доступен по адресу: http://localhost:8000")
    print(f"Документация: http://localhost:8000/docs")
    print("=" * 60)
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
import os
import shutil
import zipfile
import uuid
import hashlib
from datetime import datetime
from copy import deepcopy
from typing import Dict, Any, Tuple, List
from pathlib import Path

from lxml import etree
from dataclasses import asdict

from .constants import BASE_STORAGE_PATH, W, WORD_NS
from .storage import Storage
from .parser import CommentsParser, ParserPlugin
from .models import TemplateVariable, VariableType, DocumentTemplate


def format_date_with_mappings(date_value: str, format_mappings: str, context: str = None) -> str:
    """
    Форматирует дату согласно маппингу, заменяя placeholders в контексте.
    
    date_value: строка в формате DD.MM.YYYY (может быть "22 .04.2004" с пробелами)
    format_mappings: правила маппинга вида "DD=день MM=месяц YYYY=год"
                     где DD, MM, YYYY - это placeholders в контексте
    context: текст из документа, содержащий placeholders (опционально)
    
    Возвращает контекст с заменёнными placeholders на части даты.
    Если context не задан, применяет замены к самому format_mappings.
    
    Пример:
    - date_value = "22.04.2004"
    - format_mappings = "DD=день MM=месяц YYYY=год"
    - context = "число: DD месяц: MM год: YYYY"
    - результат = "число: 22 месяц: 04 год: 2004"
    """
    if not format_mappings:
        return context or date_value
    
    try:
        # Чистим дату от пробелов и парсим
        date_value_clean = date_value.replace(' ', '')
        parts = date_value_clean.split('.')
        if len(parts) != 3:
            return context or date_value
        
        day, month, year = parts[0], parts[1], parts[2]
        
        # Очищаем format_mappings от лишних пробелов (оставляем только пробелы между правилами)
        # Заменяем " =" на "=" и "= " на "="
        format_mappings_clean = format_mappings.replace(' =', '=').replace('= ', '=')
        
        # Парсим маппинг: "DD=день MM=месяц YYYY=год"
        # Результат: {'DD': '22', 'MM': '04', 'YYYY': '2004'}
        replacements = {}
        for rule in format_mappings_clean.split():
            if '=' in rule:
                placeholder, partition = rule.split('=', 1)
                # Обрезаем пробелы в placeholder
                placeholder = placeholder.strip()
                partition = partition.lower().strip()
                
                value = None
                if partition == 'день':
                    value = day
                elif partition == 'месяц':
                    value = month
                elif partition == 'год':
                    value = year
                
                if value:
                    replacements[placeholder] = value
        
        # Применяем замены к контексту (или format_mappings если контекста нет)
        result = context if context else format_mappings
        for placeholder, value in replacements.items():
            result = result.replace(placeholder, value)
        
        return result
    except Exception as e:
        print(f"Ошибка при форматировании даты: {e}")
        return context or date_value

class CommentsDocumentProcessor:
    def __init__(self, parser: ParserPlugin = None):
        """Если parser не передан — используется CommentsParser по умолчанию.
        Можно передать любой объект, реализующий интерфейс ParserPlugin.
        """
        self.storage = Storage()
        if parser is None:
            self.parser = CommentsParser()
        else:
            # ожидаем объект, реализующий ParserPlugin
            self.parser = parser

    def calculate_file_hash(self, file_path: Path) -> str:
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def scan_template(self, docx_path: Path, collection_id: str = None) -> Tuple[Dict[str, TemplateVariable], str]:
        workdir = BASE_STORAGE_PATH / f"temp_{uuid.uuid4()}"

        try:
            self._unzip_docx(docx_path, workdir)

            comments_xml = workdir / "word" / "comments.xml"
            comments = self.parser.parse_comments_xml(comments_xml)

            doc_xml = workdir / "word" / "document.xml"
            comment_refs = self.parser.find_comment_references_in_document(doc_xml)

            variables = {}

            for comment_id, comment_data in comments.items():
                metadata = comment_data['metadata']
                # determine variable name: if metadata provides explicit variable_name use it, otherwise generate
                var_name = metadata.get('variable_name') if metadata.get('variable_name') else f"{metadata.get('type')}_{comment_id}"

                if comment_id in comment_refs:
                    context = comment_refs[comment_id]['context']
                else:
                    context = "Комментарий без контекста"

                if metadata.get('type') == 'checkbox':
                    var_type = VariableType.CHECKBOX
                    default_value = bool(metadata.get('default'))
                elif metadata.get('type') == 'date':
                    var_type = VariableType.DATE
                    default_value = metadata.get('default')
                else:
                    var_type = VariableType.TEXT
                    default_value = metadata.get('default')

                # collection variable name: when comment is reuse (is_reuse==True), variable_name points to existing var
                collection_var_name = metadata.get('variable_name') if metadata.get('variable_name') else var_name

                if var_name in variables:
                    existing = variables[var_name]
                    existing.occurrences += 1
                    existing.comment_ids.append(comment_id)
                    existing.contexts.append(context)
                    location_dict = {
                        "comment_id": comment_id, 
                        "context": context,
                        "author": comment_data.get('author', 'Unknown'),
                        "date": comment_data.get('date', '')
                    }
                    # Добавляем маппинг если это переменная типа "дата"
                    if metadata.get('type') in ['date', 'дата']:
                        date_format_mappings = metadata.get('date_format_mappings')
                        if date_format_mappings:
                            location_dict['date_format_mappings'] = date_format_mappings
                    existing.locations.append(location_dict)
                else:
                    location_dict = {
                        "comment_id": comment_id, 
                        "context": context,
                        "author": comment_data.get('author', 'Unknown'),
                        "date": comment_data.get('date', '')
                    }
                    # Добавляем маппинг если это переменная типа "дата"
                    if metadata.get('type') in ['date', 'дата']:
                        date_format_mappings = metadata.get('date_format_mappings')
                        if date_format_mappings:
                            location_dict['date_format_mappings'] = date_format_mappings
                    variables[var_name] = TemplateVariable(
                        name=var_name,
                        collection_var_name=collection_var_name,
                        type=var_type,
                        comment_ids=[comment_id],
                        contexts=[context],
                        occurrences=1,
                        locations=[location_dict]
                    )

                # If collection provided and this comment initializes (not reuse), create collection variable
                if collection_id and not metadata.get('is_reuse', False):
                    # create or update collection variable with default
                    try:
                        self.storage.create_or_update_collection_variable(
                            collection_id,
                            collection_var_name,
                            var_type.value,
                            default_value,
                            {
                                'display_name': metadata.get('display_name', ''),
                                'description': metadata.get('description', '')
                            }
                        )
                    except Exception:
                        pass

            # Значения коллекционных переменных будут применяться при рендеринге; здесь мы только собираем ссылки и
            # при необходимости создаём определения в коллекции (см. выше)

            file_hash = self.calculate_file_hash(docx_path)

            print(f"Найдено переменных в примечаниях: {len(variables)}")
            for var_name, var in variables.items():
                print(f"  - {var.name} ({var.type.value}) - IDs комментариев: {', '.join(var.comment_ids)}")

            return variables, file_hash

        finally:
            if workdir.exists():
                shutil.rmtree(workdir)

    def render_document(self, template_id: str, variables: Dict[str, Any]) -> Path:
        template = self.storage.templates.get(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")

        workdir = BASE_STORAGE_PATH / f"render_{uuid.uuid4()}"
        templates_dir = BASE_STORAGE_PATH / "templates" / template.collection_id
        template_path = templates_dir / f"{template.id}.docx"

        try:
            self._unzip_docx(template_path, workdir)

            doc_xml = workdir / "word" / "document.xml"
            if doc_xml.exists():
                self._replace_comments_with_values(doc_xml, template, variables)

            comments_xml = workdir / "word" / "comments.xml"
            if comments_xml.exists():
                comments_xml.unlink()

            rels_path = workdir / "word" / "_rels" / "document.xml.rels"
            if rels_path.exists():
                self._remove_comments_references_from_rels(rels_path)

            output_dir = BASE_STORAGE_PATH / "rendered"
            output_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = output_dir / f"rendered_{template.name}_{timestamp}.docx"

            self._rezip_docx(workdir, output_path)

            print(f"Документ успешно отрендерен: {output_path}")
            return output_path

        except Exception as e:
            print(f"Ошибка при рендеринге: {e}")
            raise

        finally:
            if workdir.exists():
                shutil.rmtree(workdir)

    def _replace_comments_with_values(self, doc_xml: Path, template: DocumentTemplate, 
                                     variables: Dict[str, Any]):
        try:
            parser = etree.XMLParser(remove_blank_text=False)
            tree = etree.parse(str(doc_xml), parser)
            root = tree.getroot()

            # Получаем определения переменных коллекции (значения/метаданные)
            coll_vars = self.storage.get_collection_variables(template.collection_id) if template.collection_id else {}

            for var_name, template_var in template.variables.items():
                # Resolve collection-level variable name
                coll_name = getattr(template_var, 'collection_var_name', None) or var_name

                if coll_name in variables:
                    value = variables[coll_name]
                elif coll_name in coll_vars:
                    value = coll_vars[coll_name].get('value')
                else:
                    value = ''

                # Получаем метаданные переменной (включая date_format_mappings) и тип из коллекции
                metadata = None
                var_type = VariableType.TEXT  # default
                if coll_name in coll_vars:
                    coll_var = coll_vars[coll_name]
                    metadata = coll_var.get('metadata')
                    # Получаем тип из CollectionVariable, а не из TemplateVariable
                    var_type_str = coll_var.get('type', 'text')
                    try:
                        var_type = VariableType(var_type_str)
                    except (ValueError, KeyError):
                        var_type = VariableType.TEXT

                # Проходим по всем вхождениям переменной (comment_ids)
                for comment_id in getattr(template_var, 'comment_ids', []):
                    comment_start = root.find(
                        f".//{{{WORD_NS}}}commentRangeStart[@{{{WORD_NS}}}id='{comment_id}']"
                    )

                    if comment_start is None:
                        print(f"⚠ Не найден commentRangeStart с ID {comment_id}")
                        continue

                    comment_end = root.find(
                        f".//{{{WORD_NS}}}commentRangeEnd[@{{{WORD_NS}}}id='{comment_id}']"
                    )

                    if comment_end is None:
                        print(f"⚠ Не найден commentRangeEnd с ID {comment_id}")
                        continue

                    parent = comment_start.getparent()
                    if parent is None:
                        continue

                    # Применяем форматирование дат если нужно
                    final_value = value
                    print(f"Переменная: {coll_name}, тип: {var_type.value}, значение: {value}")
                    if var_type == VariableType.DATE and isinstance(value, str):
                        # Получаем маппинг и контекст из locations по comment_id
                        date_format_mappings = None
                        context_text = None
                        for location in getattr(template_var, 'locations', []):
                            if location.get('comment_id') == comment_id:
                                date_format_mappings = location.get('date_format_mappings')
                                context_text = location.get('context')
                                break
                        
                        print(f"  Формат даты: {date_format_mappings}")
                        if date_format_mappings:
                            final_value = format_date_with_mappings(value, date_format_mappings, context_text)
                            print(f"  Результат форматирования: {final_value}")

                    self._replace_comment_content(
                        parent, comment_start, comment_end,
                        var_type, final_value, comment_id
                    )

            # Удаляем все ссылки на комментарии
            for comment_ref in root.findall(f".//{{{WORD_NS}}}commentReference"):
                parent = comment_ref.getparent()
                if parent is not None:
                    parent.remove(comment_ref)

            for elem in root.findall(f".//{{{WORD_NS}}}commentRangeStart"):
                parent = elem.getparent()
                if parent is not None:
                    parent.remove(elem)

            for elem in root.findall(f".//{{{WORD_NS}}}commentRangeEnd"):
                parent = elem.getparent()
                if parent is not None:
                    parent.remove(elem)

            tree.write(str(doc_xml), xml_declaration=True, encoding="UTF-8", 
                      pretty_print=True)

        except Exception as e:
            print(f"Ошибка при замене комментариев: {e}")
            raise

    def _replace_comment_content(self, parent, comment_start, comment_end, 
                               var_type: VariableType, value, comment_id: str = ""):
        print(f"Замена комментария {comment_id}: тип={var_type}, значение={value}")
        
        elements_to_replace = []
        current = comment_start.getnext()
        while current is not None and current != comment_end:
            elements_to_replace.append(current)
            current = current.getnext()

        if not elements_to_replace:
            new_run = self._create_value_element(var_type, value)
            parent.insert(parent.index(comment_end), new_run)
            return

        if var_type == VariableType.CHECKBOX:
            # Проверяем, есть ли существующий чекбокс
            if self._has_existing_checkbox(elements_to_replace):
                print("  Обнаружен существующий чекбокс, обновляем...")
                self._update_existing_checkbox(elements_to_replace, bool(value))
            else:
                print("  Создаем новый чекбокс...")
                self._replace_checkbox_content(parent, elements_to_replace, bool(value))
        else:
            original_width = self._calculate_area_width(elements_to_replace)
            print(f"  Текстовая переменная, ширина области: {original_width}")
            self._replace_text_content_with_padding(
                parent, elements_to_replace, value, original_width, comment_id
            )

    def _has_existing_checkbox(self, elements) -> bool:
        """Проверяет, есть ли в элементах существующий чекбокс"""
        for elem in elements:
            # Проверяем FORMCHECKBOX
            instr_text = elem.find(f".//{{{WORD_NS}}}instrText")
            if instr_text is not None and instr_text.text and 'FORMCHECKBOX' in instr_text.text:
                return True
            
            # Проверяем символы чекбоксов
            for t in elem.findall(f".//{{{WORD_NS}}}t"):
                if t.text and ('☐' in t.text or '☑' in t.text or '✓' in t.text or '□' in t.text):
                    return True
        return False

    def _update_existing_checkbox(self, elements, checked: bool):
        """Обновляет существующий чекбокс"""
        for elem in elements:
            # 1. Legacy FORMCHECKBOX
            instr_text = elem.find(f".//{{{WORD_NS}}}instrText")
            if instr_text is not None and instr_text.text and 'FORMCHECKBOX' in instr_text.text:
                checkBox = elem.find(f".//{{{WORD_NS}}}checkBox")
                if checkBox is not None:
                    default_elem = checkBox.find(f".//{{{WORD_NS}}}default")
                    if default_elem is not None:
                        new_value = "1" if checked else "0"
                        default_elem.set(W+"val", new_value)
                        print(f"    ✓ Legacy чекбокс обновлен: {new_value}")
                        return
            
            # 2. Символьные чекбоксы
            for t in elem.findall(f".//{{{WORD_NS}}}t"):
                if t.text:
                    if checked and ('☐' in t.text or '□' in t.text):
                        t.text = t.text.replace('☐', '☑').replace('□', '✓')
                        print(f"    ✓ Символьный чекбокс отмечен")
                        return
                    elif not checked and ('☑' in t.text or '✓' in t.text):
                        t.text = t.text.replace('☑', '☐').replace('✓', '□')
                        print(f"    ✓ Символьный чекбокс снят")
                        return
        
        print("    ⚠ Существующий чекбокс не найден для обновления")

    def _calculate_area_width(self, elements):
        """Вычисляет ширину области"""
        total_chars = 0
        for elem in elements:
            text_parts = []
            for t in elem.findall(f".//{{{WORD_NS}}}t"):
                if t.text:
                    text_parts.append(t.text)
            element_text = "".join(text_parts)
            for char in element_text:
                if char == '\t':
                    total_chars += 4
                elif char == '\n' or char == '\r':
                    total_chars += 1
                else:
                    total_chars += 1
        return total_chars

    def _pad_text_to_width(self, text: str, target_width: int, 
                          align: str = 'left', fill_char: str = ' ') -> str:
        """Добивает текст пробелами до нужной ширины"""
        if not text:
            text = ""
        trimmed_text = text.strip()
        left_spaces = len(text) - len(text.lstrip())
        right_spaces = len(text) - len(text.rstrip())
        
        if align == 'left':
            result = text[:left_spaces] + trimmed_text
            padding_needed = target_width - len(result)
            if padding_needed > 0:
                result += fill_char * padding_needed
            return result
        elif align == 'right':
            padding_needed = target_width - len(trimmed_text) - right_spaces
            if padding_needed > 0:
                result = fill_char * padding_needed + trimmed_text + text[-right_spaces:]
            else:
                result = trimmed_text + text[-right_spaces:]
            return result
        elif align == 'center':
            total_padding = target_width - len(trimmed_text)
            left_padding = total_padding // 2
            right_padding = total_padding - left_padding
            return (fill_char * left_padding + trimmed_text + fill_char * right_padding)
        else:
            result = text[:left_spaces] + trimmed_text
            padding_needed = target_width - len(result)
            if padding_needed > 0:
                result += fill_char * padding_needed
            return result

    def _detect_text_alignment(self, element):
        """Определяет выравнивание текста"""
        parent_p = element
        while parent_p is not None and parent_p.tag != f"{W}p":
            parent_p = parent_p.getparent()

        if parent_p is not None:
            pPr = parent_p.find(W+"pPr")
            if pPr is not None:
                jc = pPr.find(W+"jc")
                if jc is not None:
                    align = jc.get(W+"val")
                    if align == "right":
                        return "right"
                    elif align == "center":
                        return "center"
                    elif align == "both":
                        return "justify"
        return "left"

    def _replace_text_content_with_padding(self, parent, elements, value: str, 
                                          original_width: int, comment_id: str = ""):
        """Заменяет текст с сохранением ширины"""
        if not elements:
            return
        align = self._detect_text_alignment(elements[0])
        padded_text = self._pad_text_to_width(str(value), original_width, align)
        first_elem = elements[0]
        new_run = self._create_text_element(padded_text, first_elem)
        first_idx = parent.index(first_elem)
        for elem in elements:
            if elem in parent:
                parent.remove(elem)
        parent.insert(first_idx, new_run)

    def _replace_checkbox_content(self, parent, elements, checked: bool):
        """Заменяет содержимое на новый чекбокс"""
        full_text = ""
        text_elements = []
        for elem in elements:
            for t in elem.findall(f".//{{{WORD_NS}}}t"):
                if t.text:
                    full_text += t.text
                    text_elements.append((elem, t))

        # Ищем [X] или [ ] в тексте
        checkbox_pos = -1
        checkbox_text = ""
        if "[X]" in full_text:
            checkbox_pos = full_text.find("[X]")
            checkbox_text = "[X]"
        elif "[ ]" in full_text:
            checkbox_pos = full_text.find("[ ]")
            checkbox_text = "[ ]"

        if checkbox_pos == -1:
            # Создаем чекбокс без замены
            checkbox_runs = self._create_legacy_checkbox(checked)
            text_after = full_text.strip()
            self._replace_elements_with_checkbox_and_text(
                parent, elements, checkbox_runs, text_after
            )
            return

        # Разделяем текст на части
        text_before = full_text[:checkbox_pos].strip()
        text_after = full_text[checkbox_pos + len(checkbox_text):].strip()

        checkbox_runs = self._create_legacy_checkbox(checked)

        # Собираем новые элементы
        new_elements = []
        if text_before:
            first_elem = elements[0]
            text_before_run = self._create_text_element(text_before, first_elem)
            new_elements.append(text_before_run)

        new_elements.extend(checkbox_runs)

        if text_after:
            last_elem = elements[-1]
            text_after_run = self._create_text_element(" " + text_after, last_elem)
            new_elements.append(text_after_run)

        # Заменяем старые элементы
        first_idx = parent.index(elements[0])
        for elem in elements:
            if elem in parent:
                parent.remove(elem)
        for i, elem in enumerate(new_elements):
            parent.insert(first_idx + i, elem)

    def _replace_elements_with_checkbox_and_text(self, parent, elements, checkbox_runs, text_after):
        """Заменяет элементы на чекбокс и текст"""
        first_idx = parent.index(elements[0])
        for elem in elements:
            if elem in parent:
                parent.remove(elem)
        for i, run in enumerate(checkbox_runs):
            parent.insert(first_idx + i, run)
        if text_after:
            first_elem = elements[0]
            text_run = self._create_text_element(" " + text_after, first_elem)
            parent.insert(first_idx + len(checkbox_runs), text_run)

    def _create_legacy_checkbox(self, checked: bool) -> List:
        """Создает новый legacy чекбокс"""
        runs = []
        r_begin = etree.Element(W+"r")
        fld_begin = etree.SubElement(r_begin, W+"fldChar", {W+"fldCharType": "begin"})
        ffData = etree.SubElement(fld_begin, W+"ffData")
        etree.SubElement(ffData, W+"enabled")
        checkBox = etree.SubElement(ffData, W+"checkBox")
        etree.SubElement(checkBox, W+"size", {W+"val": "18"})
        default_value = "1" if checked else "0"
        etree.SubElement(checkBox, W+"default", {W+"val": default_value})
        runs.append(r_begin)

        r_instr = etree.Element(W+"r")
        instr = etree.SubElement(r_instr, W+"instrText")
        instr.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        instr.text = " FORMCHECKBOX "
        runs.append(r_instr)

        r_end = etree.Element(W+"r")
        etree.SubElement(r_end, W+"fldChar", {W+"fldCharType": "end"})
        runs.append(r_end)

        return runs

    def _create_text_element(self, text: str, source_element=None):
        """Создает текстовый элемент"""
        run = etree.Element(W+"r")
        if source_element is not None:
            rPr = source_element.find(W+"rPr")
            if rPr is not None:
                rPr_copy = etree.Element(W+"rPr")
                for child in rPr:
                    rPr_copy.append(deepcopy(child))
                for attr_name, attr_value in rPr.attrib.items():
                    rPr_copy.set(attr_name, attr_value)
                run.append(rPr_copy)
        t_elem = etree.SubElement(run, W+"t")
        if text and (text.startswith(' ') or text.endswith(' ')):
            t_elem.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t_elem.text = text
        return run

    def _create_value_element(self, var_type: VariableType, value):
        """Создает элемент значения"""
        if var_type == VariableType.CHECKBOX:
            return self._create_legacy_checkbox(bool(value))
        else:
            return self._create_text_element(str(value))

    def _remove_comments_references_from_rels(self, rels_path: Path):
        """Удаляет ссылки на комментарии"""
        try:
            tree = etree.parse(str(rels_path))
            root = tree.getroot()
            rels_to_remove = []
            for rel in root.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
                rel_type = rel.get("Type", "")
                if "comments" in rel_type.lower():
                    rels_to_remove.append(rel)
            for rel in rels_to_remove:
                root.remove(rel)
            tree.write(str(rels_path), xml_declaration=True, encoding="UTF-8")
        except Exception as e:
            print(f"Ошибка при удалении ссылок на комментарии: {e}")

    def register_template(self, collection_id: str, template_name: str, 
                         docx_file_path: Path, original_filename: str) -> DocumentTemplate:
        """Регистрирует шаблон"""
        collection = self.storage.get_collection(collection_id)
        if not collection:
            raise ValueError(f"Collection {collection_id} not found")

        variables, file_hash = self.scan_template(docx_file_path, collection_id)

        template_id = str(uuid.uuid4())
        templates_dir = BASE_STORAGE_PATH / "templates" / collection_id
        templates_dir.mkdir(parents=True, exist_ok=True)

        template_file_path = templates_dir / f"{template_id}.docx"
        shutil.copy2(docx_file_path, template_file_path)

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

        self.storage.add_template_to_collection(collection_id, template)

        return template

    def aggregate_variables_for_templates(self, collection_id: str, template_ids: List[str]):
        """Агрегирует переменные по списку шаблонов (складывает occurrences, объединяет comment_ids и contexts).
        Возвращает dict name -> aggregated info с полными определениями из коллекции.
        """
        agg = {}
        # collection-level variables
        coll_vars = self.storage.get_collection_variables(collection_id) or {}

        for tid in template_ids:
            template = self.storage.templates.get(tid)
            if not template:
                continue
            for name, var in template.variables.items():
                coll_name = getattr(var, 'collection_var_name', None) or name
                cv = coll_vars.get(coll_name, {})

                if coll_name not in agg:
                    agg[coll_name] = {
                        'name': coll_name,
                        'type': cv.get('type', 'text'),
                        'occurrences': getattr(var, 'occurrences', 1),
                        'comment_ids': list(getattr(var, 'comment_ids', [])),
                        'contexts': list(getattr(var, 'contexts', [])),
                        'metadata': cv.get('metadata', {}),
                        'value': cv.get('value'),
                        'templates': [tid]
                    }
                else:
                    agg[coll_name]['occurrences'] += getattr(var, 'occurrences', 1)
                    agg[coll_name]['comment_ids'].extend(getattr(var, 'comment_ids', []))
                    agg[coll_name]['contexts'].extend(getattr(var, 'contexts', []))
                    if tid not in agg[coll_name]['templates']:
                        agg[coll_name]['templates'].append(tid)

        # add collection variables that are not present in templates
        for name, cv in coll_vars.items():
            if name not in agg:
                agg[name] = {
                    'name': name,
                    'type': cv.get('type', 'text'),
                    'occurrences': 0,
                    'comment_ids': [],
                    'contexts': [],
                    'metadata': cv.get('metadata', {}),
                    'value': cv.get('value'),
                    'templates': []
                }

        return agg

    def render_documents_batch(self, collection_id: str, template_ids: List[str], variables: Dict[str, Any]) -> Path:
        """Рендерит набор шаблонов и упаковывает результаты в zip-файл. Возвращает путь к zip.
        Переменные применяются одинаково ко всем шаблонам (override)."""
        rendered_paths = []
        for tid in template_ids:
            if tid not in self.storage.templates:
                raise ValueError(f"Template {tid} not found")
            template = self.storage.templates[tid]
            # базовые значения — берем значения из коллекции
            coll_vars = self.storage.get_collection_variables(collection_id) or {}
            vars_to_apply = {k: v.get('value') for k, v in coll_vars.items()}
            # apply user-provided overrides
            for k, v in (variables or {}).items():
                vars_to_apply[k] = v

            path = self.render_document(tid, vars_to_apply)
            rendered_paths.append(path)

        # Создадим zip
        zip_path = BASE_STORAGE_PATH / f"batch_render_{uuid.uuid4()}.zip"
        import zipfile as _zip
        # keep template ids in same order to name entries uniquely
        rendered_template_ids = list(template_ids)
        print(f"Rendered files: {rendered_paths}")
        with _zip.ZipFile(zip_path, 'w', _zip.ZIP_DEFLATED) as z:
            for i, p in enumerate(rendered_paths):
                tid = rendered_template_ids[i]
                arcname = f"{tid}_{p.name}"
                print(f"Adding to ZIP: {p} as {arcname}")
                z.write(p, arcname=arcname)
        # Удалим одиночные отрендеренные docx, оставим только zip
        for p in rendered_paths:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass
        return zip_path

    def rescan_template(self, template_id: str) -> DocumentTemplate:
        """Пересканировать файл шаблона и обновить переменные в хранилище."""
        template = self.storage.templates.get(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        templates_dir = BASE_STORAGE_PATH / "templates" / template.collection_id
        template_path = templates_dir / f"{template.id}.docx"
        if not template_path.exists():
            raise ValueError(f"Template file not found: {template_path}")
        variables, file_hash = self.scan_template(template_path, template.collection_id)
        template.variables = variables
        template.file_hash = file_hash
        template.updated_at = datetime.now().isoformat()
        # persist
        self.storage._save_to_disk()
        return template

    def _unzip_docx(self, src, dst):
        """Распаковывает DOCX"""
        if os.path.exists(dst):
            shutil.rmtree(dst)
        os.makedirs(dst)
        with zipfile.ZipFile(src, "r") as z:
            z.extractall(dst)

    def _rezip_docx(self, src_dir, dst_file):
        """Упаковывает обратно в DOCX"""
        with zipfile.ZipFile(dst_file, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(src_dir):
                for file in files:
                    full = os.path.join(root, file)
                    rel = os.path.relpath(full, src_dir)
                    z.write(full, rel)
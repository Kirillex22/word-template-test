from pathlib import Path
from lxml import etree
from .constants import WORD_NS, VARIABLE_DEFINITION_DELIMITER
from abc import ABC, abstractmethod
from typing import Dict
import uuid
import re

W = "{%s}" % WORD_NS


class ParserPlugin(ABC):
    """Abstract parser plugin interface.
    Реализует методы, которые нужны процессору: парсинг comments.xml и поиск ссылок на комментарии в document.xml
    """

    @abstractmethod
    def parse_comments_xml(self, comments_path: Path) -> Dict[str, dict]:
        raise NotImplementedError

    @abstractmethod
    def find_comment_references_in_document(self, doc_path: Path) -> Dict[str, dict]:
        raise NotImplementedError


class CommentsParser(ParserPlugin):
    """Парсер примечаний (комментариев) из DOCX"""

    def parse_comments_xml(self, comments_path: Path):
        if not comments_path.exists():
            return {}

        try:
            tree = etree.parse(str(comments_path))
            root = tree.getroot()

            comments = {}
            for comment_elem in root.findall(f".//{{{WORD_NS}}}comment"):
                comment_id = comment_elem.get(f"{{{WORD_NS}}}id")
                author = comment_elem.get(f"{{{WORD_NS}}}author", "")
                date = comment_elem.get(f"{{{WORD_NS}}}date", "")

                text_parts = []
                for p in comment_elem.findall(f".//{{{WORD_NS}}}p"):
                    for t in p.findall(f".//{{{WORD_NS}}}t"):
                        if t.text:
                            text_parts.append(t.text)

                comment_text = " ".join(text_parts).strip()

                if comment_id:
                    comments[comment_id] = {
                        'id': comment_id,
                        'author': author,
                        'date': date,
                        'text': comment_text,
                        'metadata': self._extract_metadata(comment_text)
                    }

            return comments

        except Exception as e:
            print(f"Ошибка при парсинге comments.xml: {e}")
            return {}

    def _extract_metadata(self, comment_text: str):
        metadata = {
            'type': 'text',
            'default': '',
            'display_name': '',
            'variable_name': '',
            'description': '',
            'date_format_mappings': None,
            'is_reuse': False
        }

        # Специальный случай: если комментарий заканчивается на разделитель, это означает
        # что комментарий содержит только имя переменной (переиспользование существующей переменной)
        # или в 2-й строке может быть date_format_mappings для даты
        if comment_text.endswith(VARIABLE_DEFINITION_DELIMITER):
            var_name = comment_text[:-len(VARIABLE_DEFINITION_DELIMITER)].strip()
            metadata['variable_name'] = var_name
            metadata['display_name'] = var_name.replace('_', ' ').title()
            metadata['type'] = 'text'
            metadata['default'] = ''
            metadata['description'] = f"{metadata['type'].title()}: {var_name}"
            metadata['is_reuse'] = True
            return metadata
        
        # Проверить, заканчивается ли на разделитель (переиспользование с форматом даты)
        # Формат: Дата рождения автора\\ЧИСЛО=день МЕСЯЦ=месяц ГОД=год
        lines = comment_text.split(VARIABLE_DEFINITION_DELIMITER)
        if len(lines) == 2:
            var_name = lines[0].strip()
            potential_mappings = lines[1].strip()
            
            # Проверить, это ли date_format_mappings (содержит =)
            if '=' in potential_mappings and not var_name.endswith(VARIABLE_DEFINITION_DELIMITER):
                metadata['variable_name'] = var_name
                metadata['display_name'] = var_name.replace('_', ' ').title()
                metadata['date_format_mappings'] = potential_mappings
                metadata['is_reuse'] = True
                metadata['type'] = 'date'  # Это переиспользование переменной типа date с форматом
                return metadata

        parts = [p.strip() for p in comment_text.split(VARIABLE_DEFINITION_DELIMITER)]
        if len(parts) >= 1 and parts[0]:
            metadata['type'] = parts[0].lower()

        if len(parts) >= 2 and parts[1]:
            metadata['variable_name'] = parts[1]
            metadata['display_name'] = parts[1].replace('_', ' ').title()

        if len(parts) >= 3 and parts[2]:
            metadata['default'] = parts[2]

        # Для типа "дата" может быть 4-я строка с форматом (00=день 00=месяц 1900=год)
        if len(parts) >= 4 and parts[3]:
            metadata['date_format_mappings'] = parts[3]

        if metadata['type'] in ['чекбокс', 'checkbox', 'флажок']:
            metadata['type'] = 'checkbox'
            if str(metadata['default']).lower() in ['да', 'yes', 'true', '1', '✓', '[x]']:
                metadata['default'] = True
            else:
                metadata['default'] = False
        elif metadata['type'] in ['дата', 'date']:
            metadata['type'] = 'date'
        else:
            metadata['type'] = 'text'

        # mark initialization (not reuse) by default
        metadata['is_reuse'] = False

        # Описание: тип + имя (если есть)
        name_for_desc = metadata['variable_name'] if metadata['variable_name'] else parts[0] if parts else ''
        metadata['description'] = f"{metadata['type'].title()}: {name_for_desc}"
        return metadata

    def find_comment_references_in_document(self, doc_path: Path):
        if not doc_path.exists():
            return {}

        try:
            tree = etree.parse(str(doc_path))
            root = tree.getroot()

            references = {}

            for comment_start in root.findall(f".//{{{WORD_NS}}}commentRangeStart"):
                comment_id = comment_start.get(f"{{{WORD_NS}}}id")
                if comment_id:
                    comment_end = root.find(
                        f".//{{{WORD_NS}}}commentRangeEnd[@{{{WORD_NS}}}id='{comment_id}']"
                    )

                    context = self._get_text_between_elements(
                        root, comment_start, comment_end
                    )

                    references[comment_id] = {
                        'start_element': comment_start,
                        'end_element': comment_end,
                        'context': context
                    }

            return references

        except Exception as e:
            print(f"Ошибка при поиске комментариев: {e}")
            return {}

    @staticmethod
    def _get_text_between_elements(root, start_elem, end_elem):
        text_parts = []

        start_path = CommentsParser._get_element_path(root, start_elem)
        end_path = CommentsParser._get_element_path(root, end_elem)

        if not start_path or not end_path:
            return ""

        current = start_elem.getnext()
        while current is not None and current != end_elem:
            for t in current.findall(f".//{{{WORD_NS}}}t"):
                if t.text:
                    text_parts.append(t.text)

            for r in current.findall(f".//{{{WORD_NS}}}r"):
                r_text = ""
                for t in r.findall(f".//{{{WORD_NS}}}t"):
                    if t.text:
                        r_text += t.text

                if '[X]' in r_text or '[ ]' in r_text:
                    text_parts.append(r_text)

            current = current.getnext()

        return " ".join(text_parts).strip()

    def find_and_inject_legacy_checkboxes(self, doc_path: Path, comments_path: Path) -> Dict[str, dict]:
        """
        Находит legacy чекбоксы в документе и инжектит виртуальные комментарии.
        Возвращает информацию о добавленных чекбоксах как если бы они были размечены примечаниями.
        
        Процесс:
        1. Найти все legacy checkboxes (FORMCHECKBOX и символьные)
        2. Добавить commentRangeStart и commentRangeEnd вокруг них в document.xml
        3. Создать соответствующие entries в comments.xml с типом "checkbox"
        """
        if not doc_path.exists():
            return {}
        
        try:
            # Парсим document.xml
            doc_tree = etree.parse(str(doc_path))
            doc_root = doc_tree.getroot()
            
            # Парсим или создаём comments.xml
            if comments_path.exists():
                comments_tree = etree.parse(str(comments_path))
                comments_root = comments_tree.getroot()
            else:
                # Создаём новый comments.xml
                comments_root = etree.Element(
                    f"{{{WORD_NS}}}comments",
                    nsmap={'w': WORD_NS}
                )
                comments_tree = etree.ElementTree(comments_root)
            
            checkboxes_added = {}
            checkbox_counter = 0
            next_comment_id = 0
            
            # Получаем текущий максимальный ID комментария
            existing_comments = comments_root.findall(f"{{{WORD_NS}}}comment")
            if existing_comments:
                ids = []
                for comment in existing_comments:
                    cid = comment.get(f"{{{WORD_NS}}}id")
                    if cid:
                        try:
                            ids.append(int(cid))
                        except ValueError:
                            pass
                if ids:
                    next_comment_id = max(ids) + 1
            
            # Ищем все чекбоксы в параграфах
            for p_elem in doc_root.findall(f".//{{{WORD_NS}}}p"):
                # Собираем информацию о чекбоксах в этом параграфе
                checkbox_elements = []
                para_text = ""
                
                for r_elem in p_elem.findall(f".//{{{WORD_NS}}}r"):
                    # Проверяем FORMCHECKBOX
                    instr_text = r_elem.find(f".//{{{WORD_NS}}}instrText")
                    if instr_text is not None and instr_text.text and 'FORMCHECKBOX' in instr_text.text:
                        start_pos = len(para_text)
                        para_text += "☐"
                        checkbox_elements.append({
                            'element': r_elem,
                            'type': 'formcheckbox',
                            'start_pos': start_pos,
                            'end_pos': len(para_text)
                        })
                    else:
                        # Собираем текст
                        for t_elem in r_elem.findall(f".//{{{WORD_NS}}}t"):
                            if t_elem.text:
                                for char in t_elem.text:
                                    if char in ['☐', '☑', '✓', '□']:
                                        start_pos = len(para_text)
                                        para_text += char
                                        checkbox_elements.append({
                                            'element': r_elem,
                                            'type': 'symbol',
                                            'start_pos': start_pos,
                                            'end_pos': len(para_text)
                                        })
                                    else:
                                        para_text += char
                
                # Обрабатываем каждый найденный чекбокс
                for checkbox_info in checkbox_elements:
                    r_elem = checkbox_info['element']
                    end_pos = checkbox_info['end_pos']
                    checkbox_type = checkbox_info['type']
                    
                    # Получаем текст справа от чекбокса
                    text_after = para_text[end_pos:].strip()
                    
                    # Ищем конец описания (2+ пробела или другой чекбокс)
                    description_end = len(text_after)
                    for i in range(len(text_after) - 1):
                        if text_after[i] == ' ' and text_after[i+1] == ' ':
                            description_end = i
                            break
                        if text_after[i] in ['☐', '☑', '✓', '□']:
                            description_end = i
                            break
                    
                    description = text_after[:description_end].strip()
                    
                    # Генерируем имя переменной
                    if description:
                        var_name = self._generate_variable_name(description)
                    else:
                        checkbox_counter += 1
                        var_name = f"checkbox_{checkbox_counter}"
                    
                    comment_id = str(next_comment_id)
                    next_comment_id += 1
                    
                    r_parent = r_elem.getparent()
                    r_index = list(r_parent).index(r_elem)
                    
                    # Вставляем в обратном порядке чтобы индексы не смещались:
                    # Сначала вставляем commentReference после (это будет на позиции r_index + 3)
                    comment_ref = etree.Element(f"{{{WORD_NS}}}r")
                    comment_ref_elem = etree.SubElement(comment_ref, f"{{{WORD_NS}}}commentReference")
                    comment_ref_elem.set(f"{{{WORD_NS}}}id", comment_id)
                    r_parent.insert(r_index + 1, comment_ref)
                    
                    # Затем вставляем commentRangeEnd после r_elem (на позиции r_index + 1, commentRef сдвинется)
                    comment_end = etree.Element(f"{{{WORD_NS}}}commentRangeEnd")
                    comment_end.set(f"{{{WORD_NS}}}id", comment_id)
                    r_parent.insert(r_index + 1, comment_end)
                    
                    # Наконец вставляем commentRangeStart перед r_elem (на позиции r_index)
                    comment_start = etree.Element(f"{{{WORD_NS}}}commentRangeStart")
                    comment_start.set(f"{{{WORD_NS}}}id", comment_id)
                    r_parent.insert(r_index, comment_start)
                    
                    # Создаём комментарий в comments.xml
                    comment_elem = etree.SubElement(comments_root, f"{{{WORD_NS}}}comment")
                    comment_elem.set(f"{{{WORD_NS}}}id", comment_id)
                    comment_elem.set(f"{{{WORD_NS}}}author", "Document")
                    comment_elem.set(f"{{{WORD_NS}}}date", "")
                    comment_elem.set(f"{{{WORD_NS}}}initials", "D")
                    
                    # Добавляем текст комментария в формате: checkbox\\checkbox_name
                    p_comment = etree.SubElement(comment_elem, f"{{{WORD_NS}}}p")
                    pPr = etree.SubElement(p_comment, f"{{{WORD_NS}}}pPr")
                    pStyle = etree.SubElement(pPr, f"{{{WORD_NS}}}pStyle")
                    pStyle.set(f"{{{WORD_NS}}}val", "CommentText")
                    
                    r_comment = etree.SubElement(p_comment, f"{{{WORD_NS}}}r")
                    rPr = etree.SubElement(r_comment, f"{{{WORD_NS}}}rPr")
                    rStyle = etree.SubElement(rPr, f"{{{WORD_NS}}}rStyle")
                    rStyle.set(f"{{{WORD_NS}}}val", "CommentReference")
                    annotationRef = etree.SubElement(rPr, f"{{{WORD_NS}}}annotationRef")
                    
                    t_comment = etree.SubElement(r_comment, f"{{{WORD_NS}}}t")
                    t_comment.text = f"checkbox{VARIABLE_DEFINITION_DELIMITER}{var_name}"
                    
                    checkboxes_added[comment_id] = {
                        'id': comment_id,
                        'variable_name': var_name,
                        'description': description,
                        'checkbox_type': checkbox_type
                    }
                    
                    print(f"  ✓ Добавлен виртуальный комментарий {comment_id}: {var_name} ({description})")
                    
                    # Отладка: для первого чекбокса показываем структуру
                    if comment_id == "0":
                        print(f"    DEBUG: Структура r_elem:")
                        for child in r_elem:
                            print(f"      ├─ {child.tag}")
                            for subchild in child:
                                print(f"      │  ├─ {subchild.tag} = {subchild.text if subchild.text else ''}")
            
            # Сохраняем изменённые файлы
            doc_tree.write(str(doc_path), xml_declaration=True, encoding="UTF-8", pretty_print=True)
            comments_tree.write(str(comments_path), xml_declaration=True, encoding="UTF-8", pretty_print=True)
            
            print(f"Добавлено {len(checkboxes_added)} виртуальных комментариев для legacy checkboxes")
            return checkboxes_added
        
        except Exception as e:
            print(f"Ошибка при инжекции legacy checkboxes: {e}")
            import traceback
            traceback.print_exc()
            return {}

    
    @staticmethod
    def _generate_variable_name(text: str) -> str:
        """
        Генерирует переменную из текста.
        Заменяет пробелы на подчёркивание, удаляет спецсимволы.
        """
        import re
        # Удаляем все спецсимволы, кроме пробелов и букв/цифр
        text = re.sub(r'[^а-яА-ЯёЁa-zA-Z0-9\s]', '', text)
        # Заменяем пробелы на подчёркивание
        text = text.replace(' ', '_')
        # Удаляем лишние подчёркивания
        text = re.sub(r'_+', '_', text)
        # Удаляем подчёркивание в начале/конце
        text = text.strip('_')
        # Переводим в нижний регистр
        text = text.lower()
        return text if text else "checkbox"

    @staticmethod
    def _get_element_path(root, target):
        # helper — возвращает путь (index list) до элемента, или None
        for elem in root.iter():
            if elem is target:
                return True
        return False

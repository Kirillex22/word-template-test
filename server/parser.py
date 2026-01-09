from pathlib import Path
from lxml import etree
from .constants import WORD_NS, VARIABLE_DEFINITION_DELIMITER
from abc import ABC, abstractmethod
from typing import Dict

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
        if comment_text.endswith(VARIABLE_DEFINITION_DELIMITER):
            var_name = comment_text[:-len(VARIABLE_DEFINITION_DELIMITER)].strip()
            metadata['variable_name'] = var_name
            metadata['display_name'] = var_name.replace('_', ' ').title()
            metadata['type'] = 'text'
            metadata['default'] = ''
            metadata['description'] = f"{metadata['type'].title()}: {var_name}"
            metadata['is_reuse'] = True
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

    @staticmethod
    def _get_element_path(root, target):
        # helper — возвращает путь (index list) до элемента, или None
        for elem in root.iter():
            if elem is target:
                return True
        return False

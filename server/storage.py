import os
import shutil
import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Any

from .constants import BASE_STORAGE_PATH
from .models import Collection, DocumentTemplate, TemplateVariable, VariableMetadata, VariableType, CollectionVariable

class Storage:
    def __init__(self):
        self.collections: Dict[str, Collection] = {}
        self.templates: Dict[str, DocumentTemplate] = {}
        self._load_from_disk()

    def _load_from_disk(self):
        BASE_STORAGE_PATH.mkdir(parents=True, exist_ok=True)

        collections_file = BASE_STORAGE_PATH / "collections.json"
        if collections_file.exists():
            with open(collections_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for coll_id, coll_data in data.items():
                    # load collection and its variables
                    vars_dict = coll_data.get('variables', {}) or {}
                    coll_data_copy = {k: v for k, v in coll_data.items() if k not in ('variables', 'shared_variables_file', 'shared_variables')}
                    coll = Collection(**coll_data_copy)
                    coll.variables = {}
                    for vname, vdata in vars_dict.items():
                        try:
                            vtype = VariableType(vdata.get('type', 'text'))
                            print(vname, vtype)
                        except Exception as e:
                            print(e)
                            vtype = VariableType.TEXT
                        md = None
                        if vdata.get('metadata'):
                            try:
                                md = VariableMetadata(**vdata.get('metadata'))
                            except Exception:
                                md = None
                        coll.variables[vname] = CollectionVariable(
                            name=vname,
                            type=vtype,
                            metadata=md,
                            value=vdata.get('value', ''),
                            created_at=vdata.get('created_at', ''),
                            updated_at=vdata.get('updated_at', '')
                        )
                    self.collections[coll_id] = coll

        templates_file = BASE_STORAGE_PATH / "templates.json"
        if templates_file.exists():
            with open(templates_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for temp_id, temp_data in data.items():
                    variables = {}
                    for var_name, var_data in temp_data.get('variables', {}).items():
                        try:
                            var_type = VariableType(var_data.get('type', 'text'))
                        except Exception:
                            var_type = VariableType.TEXT

                        comment_ids = var_data.get('comment_ids') if var_data.get('comment_ids') is not None else ([var_data.get('comment_id')] if var_data.get('comment_id') else [])
                        contexts = var_data.get('contexts') if var_data.get('contexts') is not None else ([var_data.get('context')] if var_data.get('context') else [])

                        collection_var_name = var_data.get('collection_var_name') or var_data.get('shared_ref') or var_name

                        variables[var_name] = TemplateVariable(
                            name=var_name,
                            collection_var_name=collection_var_name,
                            type=var_type,
                            comment_ids=comment_ids,
                            contexts=contexts,
                            occurrences=var_data.get('occurrences', 1),
                            locations=var_data.get('locations', [])
                        )

                    temp_data['variables'] = variables
                    self.templates[temp_id] = DocumentTemplate(**temp_data)

    def _save_to_disk(self):
        # collections
        collections_data = {}
        for k, v in self.collections.items():
            cd = asdict(v)
            vars_out = {}
            for vn, vv in (v.variables or {}).items():
                try:
                    vars_out[vn] = vv.to_dict()
                except Exception:
                    vars_out[vn] = vv
            cd['variables'] = vars_out
            collections_data[k] = cd
        with open(BASE_STORAGE_PATH / "collections.json", 'w', encoding='utf-8') as f:
            json.dump(collections_data, f, ensure_ascii=False, indent=2)

        # templates
        # Сохраняем только ссылки на переменные и их локации, без полных определений
        templates_data = {}
        for temp_id, template in self.templates.items():
            data = asdict(template)
            # Сохраняем только минимум: collection_var_name, comment_ids, contexts, locations, occurrences
            data['variables'] = {}
            for k, v in template.variables.items():
                data['variables'][k] = {
                    'collection_var_name': v.collection_var_name,
                    'comment_ids': list(v.comment_ids) if v.comment_ids else [],
                    'contexts': list(v.contexts) if v.contexts else [],
                    'occurrences': v.occurrences,
                    'locations': list(v.locations) if v.locations else []
                }
            templates_data[temp_id] = data

        with open(BASE_STORAGE_PATH / "templates.json", 'w', encoding='utf-8') as f:
            json.dump(templates_data, f, ensure_ascii=False, indent=2)

    def create_collection(self, name: str, description: str = "") -> Collection:
        collection_id = str(uuid.uuid4())
        collection = Collection(
            id=collection_id,
            name=name,
            description=description
        )
        collection.variables = {}
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
            collection.updated_at = __import__('datetime').datetime.now().isoformat()
            self.templates[template.id] = template
            self._save_to_disk()
            return True
        return False

    # --- Collection-level variables API ---
    def get_collection_variables(self, collection_id: str) -> dict:
        collection = self.get_collection(collection_id)
        if not collection:
            return {}
        
        # Подсчитываем количество вхождений и собираем авторов
        occurrences_count = {}
        authors = {}
        
        for template_id in (collection.templates or []):
            template = self.templates.get(template_id)
            if not template:
                continue
            for var_name, var_data in (template.variables or {}).items():
                coll_var_name = var_data.collection_var_name or var_name
                if coll_var_name not in occurrences_count:
                    occurrences_count[coll_var_name] = {'count': 0, 'templates': []}
                    authors[coll_var_name] = []
                
                occurrences_count[coll_var_name]['count'] += getattr(var_data, 'occurrences', 1)
                if template_id not in occurrences_count[coll_var_name]['templates']:
                    occurrences_count[coll_var_name]['templates'].append(template_id)
                
                # Собираем авторов из locations
                for location in getattr(var_data, 'locations', []):
                    author_info = {
                        'author': location.get('author', 'Unknown'),
                        'date': location.get('date', ''),
                        'template_id': template_id
                    }
                    # Добавляем только если такого автора ещё нет
                    if author_info not in authors[coll_var_name]:
                        authors[coll_var_name].append(author_info)
        
        # Добавляем информацию о вхождениях и авторах в ответ
        result = {}
        for k, v in (collection.variables or {}).items():
            var_dict = v.to_dict()
            var_dict['occurrences_total'] = occurrences_count.get(k, {}).get('count', 0)
            var_dict['templates_count'] = len(occurrences_count.get(k, {}).get('templates', []))
            var_dict['authors'] = authors.get(k, [])
            result[k] = var_dict
        
        return result

    def create_or_update_collection_variable(self, collection_id: str, var_name: str,
                                             var_type: str = 'text', value: Any = '', metadata: dict = None) -> bool:
        collection = self.get_collection(collection_id)
        if not collection:
            return False
        try:
            vt = VariableType(var_type)
        except Exception:
            vt = VariableType.TEXT
        md = None
        if metadata:
            try:
                md = VariableMetadata(**metadata)
            except Exception:
                md = None
        cv = CollectionVariable(
            name=var_name,
            type=vt,
            metadata=md,
            value=value,
            created_at=__import__('datetime').datetime.now().isoformat(),
            updated_at=__import__('datetime').datetime.now().isoformat()
        )
        collection.variables[var_name] = cv
        collection.updated_at = __import__('datetime').datetime.now().isoformat()
        self._save_to_disk()
        return True

    def delete_collection_variable(self, collection_id: str, var_name: str) -> bool:
        collection = self.get_collection(collection_id)
        if not collection:
            return False
        if var_name in (collection.variables or {}):
            del collection.variables[var_name]
            collection.updated_at = __import__('datetime').datetime.now().isoformat()
            self._save_to_disk()
            return True
        return False

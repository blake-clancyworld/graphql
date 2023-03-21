# -*- coding: utf-8 -*-

# https://github.com/graphql-python/graphql-core
from graphql import parse
from odoo.http import request
from odoo.exceptions import ValidationError
from odoo.osv.expression import AND
from graphql.language.ast import (
    VariableNode,
    ValueNode,
    ObjectValueNode,
    ListValueNode,
    IntValueNode,
    FloatValueNode,
)
from odoo.osv import expression
# import traceback

import logging

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)


def model2name(model):
    _logger.info(f"Converting model {model} to name")
    return "".join(p.title() for p in model.split("."))


def filter_by_directives(node, variables={}):
    _logger.info(f"Filtering directives for node {node}")
    if not node.selection_set:
        return
    selections = []
    for field in node.selection_set.selections:
        if parse_directives(field.directives, variables=variables):
            selections.append(field)
            filter_by_directives(field, variables=variables)
    node.selection_set.selections = selections


def get_definition(doc, operation=None):
    _logger.info(f"Getting definition for operation {operation}")
    if operation is None or len(doc.definitions) == 1:
        return doc.definitions[0]
    for definition in doc.definitions:
        # https://dgraph.io/docs/graphql/api/multiples/#multiple-operations
        # https://github.com/graphql/graphql-spec/issues/29
        if definition.name.value == operation:
            return definition
    return doc.definitions[0]  # Or raise an Exception?


def handle_graphql(doc, model_mapping, variables={}, operation=None, allowed_fields={},company_id=None):
    _logger.info (company_id)
    _logger.info(f"Handling GraphQL request with operation {operation} and variables {variables}")
    response = {}
    try:
        data = parse_document(
            doc,
            model_mapping,
            variables=variables,
            operation=operation,
            allowed_fields=allowed_fields,
            company_id=company_id,
        )
        response["data"] = data
    except Exception as e:
        _logger.info(f"Error while handling GraphQL request: {e}")
        _logger.critical(e)
        response["data"] = None
        response["errors"] = {"message": str(e)}  # + traceback.format_exc()
    return response
def parse_document(doc, model_mapping, variables={}, operation=None, allowed_fields={}, company_id=None):
    _logger.info(f"Parsing document with operation {operation} and variables {variables}")
    if isinstance(doc, str):
        doc = parse(doc)

    # A document can have many definitions
    definition = get_definition(doc, operation=operation)
    return parse_definition(
        definition, model_mapping, variables=variables, allowed_fields=allowed_fields, company_id=company_id
    )


def parse_directives(directives, variables={}):
    """Currently return True to keep, False to skip"""
    for d in directives:
        if d.name.value == "include":
            for arg in d.arguments:
                if arg.name.value == "if":
                    value = value2py(arg.value, variables=variables)
                    return value
        elif d.name.value == "skip":
            for arg in d.arguments:
                if arg.name.value == "if":
                    value = value2py(arg.value, variables=variables)
                    return not value
    return True  # Keep everything else

def value2py(value, variables={}):
    _logger.info(f"Converting value {value} to Python with variables {variables}")
    if isinstance(value, VariableNode):
        return variables[value.name.value]
    if isinstance(value, ValueNode):
        if isinstance(value, ObjectValueNode):
            return {f.name.value: value2py(f.value, variables=variables) for f in value.fields}
        elif isinstance(value, ListValueNode):
            return [value2py(v, variables=variables) for v in value.values]
        elif isinstance(value, IntValueNode):
            return int(value.value)
        elif isinstance(value, FloatValueNode):
            return float(value.value)
        else:
            return value.value
    raise ValueError(f"Unknown value type: {value}")

def parse_definition(definition, model_mapping, variables={}, allowed_fields={}, company_id=None):
    _logger.info(f"Parsing definition with variables {variables}")
    filter_by_directives(definition, variables=variables)
    model = model_mapping[definition.name.value]
    fields = parse_fields(definition, model_mapping, variables=variables, allowed_fields=allowed_fields, company_id=company_id)
    return {definition.name.value: fields}
def filter_by_directives(node, variables={}):
    """Filter fields and fragment spreads by directives"""
    node.selection_set.selections = [
        s for s in node.selection_set.selections if parse_directives(s.directives, variables=variables)
    ]


def parse_fields(definition, model_mapping, variables={}, allowed_fields={}, company_id=None):
    _logger.info(f"Parsing fields for {definition.name.value} with variables {variables}")
    model = model_mapping[definition.name.value]
    fields = {}
    for field in definition.selection_set.selections:
        if isinstance(field, FieldNode):
            if field.name.value in allowed_fields:
                if field.name.value in model:
                    value = model[field.name.value]
                    if callable(value):
                        value = value(company_id=company_id)
                    fields[field.name.value] = value
                else:
                    _logger.error(f"Field {field.name.value} not found in model {definition.name.value}")
            else:
                _logger.warning(f"Field {field.name.value} not allowed in model {definition.name.value}")
        elif isinstance(field, FragmentSpreadNode):
            fragment = get_fragment(doc, field.name.value)
            if fragment:
                fields.update(parse_fields(fragment, model_mapping, variables=variables, allowed_fields=allowed_fields, company_id=company_id))
            else:
                _logger.error(f"Fragment {field.name.value} not found in document")
    return fields

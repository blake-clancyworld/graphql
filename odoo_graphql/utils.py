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


def parse_document(doc, model_mapping, variables={}, operation=None, allowed_fields={},company_id=None):
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
    return True  # Keep by default


def _parse_definition(
    definition, model_mapping, variables={}, mutation=False, allowed_fields={}, company_id=None
):
    data = {}
    for field in definition.selection_set.selections:
        model = model_mapping[field.name.value]
        fname = field.alias and field.alias.value or field.name.value
        data[fname] = parse_model_field(
            model,
            field,
            variables=variables,
            mutation=mutation,
            allowed_fields=allowed_fields,
            company_id=company_id
        )
    return data


def parse_definition(definition, model_mapping, variables={}, allowed_fields={}, company_id=None):
    _logger.info(f"Parsing definition {definition} with variables {variables}")
    dtype = definition.operation.value      # MUTATION OR QUERY
    if dtype not in ("query", "mutation"):  # does not support other types currentyl
        return None

    filter_by_directives(definition, variables)
    mutation = dtype == "mutation"
    return _parse_definition(
        definition,
        model_mapping=model_mapping,
        variables=variables,
        mutation=mutation,
        allowed_fields=allowed_fields,
        company_id=company_id,
    )


def relation_subgathers(records, relational_data, variables={}, company_id=None):
    subgathers = {}
    for submodel, fname, fields in relational_data:
        sub_records_ids = records.mapped(fname).ids
        aliases = []
        for f in fields:
            # Nb: Even if its the same field, the domain may change
            alias = f.alias and f.alias.value or f.name.value
            tmp = parse_model_field(
                submodel, f, variables=variables, ids=sub_records_ids, company_id=company_id
            )
            data = {d["id"]: (i, d) for i, d in enumerate(tmp)}

            # https://stackoverflow.com/questions/8946868/is-there-a-pythonic-way-to-close-over-a-loop-variable
            def subgather(ids, data=data):
                if ids is False:
                    return None
                # We may not receive all ids since records may be archived
                if isinstance(ids, int):
                    return data.get(ids)[1]
                # Since the data are gathered in batch, then dispatching,
                # The order is lost and must be done again.
                res = [
                    d
                    for _, d in sorted(
                        (d for d in (data.get(rec_id) for rec_id in ids) if d),
                        key=lambda t: t[0],
                    )
                ]
                return res

            aliases.append((alias, subgather))

        subgathers[fname] = aliases
    return subgathers


def make_domain(model, field, ids=None, company_id=None, mutation=False):
    # Create an empty domain list
    domain = []
    
    # Add the ID filter if IDs are provided
    if ids:
        domain += [('id', 'in', ids)]
    
    # Add the company filter if company ID is provided and user is not a superuser
    if company_id and not mutation and not request.env.user._is_superuser():
        allowed_companies = request.env.user.company_ids.ids
        _logger.info(f" the full list of {allowed_companies}")
        if company_id in allowed_companies:
            domain += [(field, '=', company_id)]    
    
    return domain

def get_records(model, field, ids=None, company_id=None, mutation=False):
    # Retrieve the domain
    domain = make_domain(model, field, ids, company_id, mutation)
    
    # Search for the records
    records = request.env[model].sudo().search(domain)
    
    # Check if the user has access to the records
    request.env[model].check_access_rights('read')
    request.env[model].check_access_rule(records)
    
    return records


def set_default_company(record, company_id):

    """Set the default company ID for a record."""
    if 'company_id' in record and company_id:
        record['company_id'] = company_id.id


def set_user_context(model, variables, context):
    _logger.info(f"Setting context for model {model} with variables {variables}")
    """
    Set the context for the given model based on the variables and context provided.
    """
    if "context" in variables and variables["context"]:
        context.update(variables["context"])
    model = model.with_context(context)
    _logger.info(f"Context for model {model} after setting: {model.env.context}")
    return model
  

# TODO: make it possible to define custom create/write handlers per models


def retrieve_records(model, field, variables=None, ids=None, mutation=False, company_id=None):
    """
    Retrieve records from a model based on a GraphQL field.
    """
    _logger.info(f"Retrieving records for model {model}, field {field}, ids {ids}, mutation {mutation}")

    user = model.env.user
    user_allowed_company_ids = user.company_ids.ids
    _logger.info(f"User's allowed company_ids: {user_allowed_company_ids}")

    # Add logging for the company_id value.
    _logger.info(f"Provided company_id: {company_id}")

    domain, kwargs, vals = parse_arguments(field.arguments, variables)

    _logger.info(f"Domain received from parse_arguments: {domain}")

    if mutation and domain is None:  # Create
        try:
            records = model.create(vals)
        except Exception as e:
            if "DETAIL" in str(e):
                model.env.cr.rollback()
                raise ValidationError(str(e).split("\n")[0])
            raise
        return records

    domain = convert_array_to_tuple(domain or [])

    _logger.info(f"Domain after converting to tuple: {domain}")

    if company_id is not None:
        if isinstance(company_id, int):
            company_id = [company_id]
            _logger.info(f"Converted company_id to list: {company_id}")
        company_domain = expression.OR([[("company_id", "in", company_id)], [("company_id", "=", False)]])
        domain = expression.AND([company_domain, domain])
    else:
        domain = make_domain(domain, ids)

    _logger.info(f"Domain after applying company_id filter: {domain}")

    if company_id is not None:
        model = model.with_company(company_id)
    else:
        model = model.with_company(user.company_id.id)

    records = model.search(domain, **kwargs)

    if mutation:  # Write
        records.write(vals)

    _logger.info(f"Retrieved {len(records)} records for model {model}, field {field}, ids {ids}, mutation {mutation}")

    return records





def convert_array_to_tuple(domain_array):
    tuple_array = []
    [tuple_array.append(tuple(x)) for x in domain_array]
    return tuple_array
    
# Nb: the parameter "ids" is useful for relational fields
def parse_model_field(
    model, field, variables={}, ids=None, mutation=False, allowed_fields={}, company_id=None
):
    records = retrieve_records(
        model,
        field,
        variables=variables,
        ids=ids,
        mutation=mutation,
        company_id=company_id
    )

    # User may have forgotten to define subfields
    # We use an empty list to prevent it,
    # Maybe we should rise an error here instead?
    fields = []
    if field.selection_set:
        fields = field.selection_set.selections
    allowed = allowed_fields.get(model._name)
    if allowed is not None:
        fields = [f for f in fields if f.name.value in allowed]
        if not fields:
            return [
                {"id": rid} for rid in records.ids
            ]
    fields_names = [f.name.value for f in fields]

    # Get datas
    relational_data, fields_data = get_fields_data(model, fields)
    subgathers = relation_subgathers(records, relational_data, variables=variables, company_id=company_id)
    records = records.read(fields_names, load=False)

    data = []
    for rec in records:
        tmp = {"id": rec["id"]}
        for fname, aliases in fields_data:
            for alias in aliases:
                value = rec[fname]
                if isinstance(value, bytes):
                    value = value.decode()
                tmp[alias] = value

        for fname, aliases in subgathers.items():
            ids = rec[fname]
            for alias, subgather in aliases:
                tmp[alias] = subgather(ids)
        data.append(tmp)
    return data


def get_fields_data(model, fields):
    relations = {}
    basic_fields = {}
    for field in fields:
        name = field.name.value
        f = model._fields[name]
        if f.relational:
            r = relations.setdefault(
                name,
                (
                    model.env[f.comodel_name],
                    name,
                    [],
                ),
            )
            r[2].append(field)
        else:
            r = basic_fields.setdefault(
                name,
                (
                    name,
                    [],
                ),
            )
            r[1].append(field.alias and field.alias.value or field.name.value)

    return relations.values(), basic_fields.values()


OPTIONS = [("offset", int), ("limit", int), ("order", str)]


# TODO: Add a hook to filter vals?
# https://stackoverflow.com/questions/45674423/how-to-filter-greater-than-in-graphql
from graphql.language import ast
#from odoo.addons.odoo_graphql.utils import convert_argument, is_array, is_enum


def parse_arguments(arguments, variables):
    """
    Parse arguments in the GraphQL request to Odoo domain and kwargs.
    """
    domain = []
    kwargs = {}
    vals = {}
    for arg_name, arg_node in arguments.items():
        arg_value = convert_argument(arg_node.value, variables)

        if is_array(arg_value):
            arg_value = [convert_argument(value, variables) for value in arg_value]
            domain.append((arg_name, "in", arg_value))
        elif is_enum(arg_node):
            domain.append((arg_name, "=", arg_value))
        else:
            kwargs[arg_name] = arg_value
            vals[arg_name] = arg_value

    return domain, kwargs, vals



def value2py(value, variables={}):
    if isinstance(value, VariableNode):
        return variables.get(value.name.value)
    if isinstance(value, ValueNode):
        if isinstance(value, ListValueNode):
            return [value2py(v, variables=variables) for v in value.values]
        if isinstance(value, ObjectValueNode):
            return dict(
                (
                    value2py(f.name, variables=variables),
                    value2py(f.value, variables=variables),
                )
                for f in value.fields  # list of ObjectFieldNode
            )
        # For unknown reason, integers and floats are received as string,
        # but not booleans nor list
        if isinstance(value, IntValueNode):
            return int(value.value)
        if isinstance(value, FloatValueNode):
            return float(value.value)
    return value.value

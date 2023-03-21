from odoo import http
from odoo.http import request, content_disposition
import json
from ..utils import handle_graphql
from ..auth import authenticate_and_execute
import logging

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)

import json
from graphql import GraphQLError, GraphQLSchema, execute, parse

from ..utils import (
    #convert_odoo_type_to_graphql,
    retrieve_records,
    set_default_company,
    set_user_context,
)
import traceback


class GraphQLController(http.Controller):
    @http.route("/graphql", type="http", auth="user", website=True, csrf=False)
    def graphql(self, **kwargs):
        try:
            _logger.info(f"Received request: {kwargs}")

            # Check Content-Type
            content_type = http.request.httprequest.headers.get("Content-Type", "")
            if content_type != "application/graphql":
                raise GraphQLError("Invalid Content-Type. Use application/graphql.")

            # Get request data
            request_data = http.request.httprequest.data.decode("utf-8")

            _logger.info(f"Parsed request data: {request_data}")
            query = json.loads(request_data).get("query")
            _logger.info(f"Received query: {query}")

            variables = json.loads(request_data).get("variables", {})
            operation_name = json.loads(request_data).get("operationName")
            context = http.request.env.context.copy()
            _logger.info(f"Context before setting: {context}")
            set_user_context(context=context, model=http.request.env["product.product"], variables=variables)
            set_default_company(context, kwargs.get('auth', {}).get('company_id'))
            _logger.info(f"Context after setting: {context}")
            schema = GraphQLSchema(query=self.get_query())
            _logger.info(f"Schema: {schema}")
            result = execute(
                schema=schema,
                context_value=context,
                document_ast=parse(query),
                operation_name=operation_name,
                variable_values=variables,
                field_resolver=self.get_field_resolver(),
            )
            return json.dumps({"data": result.data, "errors": [e.message for e in result.errors]})
        except Exception as e:
            _logger.error(traceback.format_exc())
            return json.dumps({"data": None, "errors": [str(e)]})

    def get_query(self):
        queries = []
        for model_name in http.request.env:
            model = http.request.env[model_name]
            if not model._abstract and hasattr(model, "_graphql"):
                queries.append(model._graphql)
        return parse("\n".join(queries))

    def get_field_resolver(self):
        def resolve(model_name, info, **kwargs):
            try:
                model = http.request.env[model_name]
            except Exception:
                raise GraphQLError(f"Model {model_name} not found")
            field = info.field_name
            variables = info.variable_values
            ids = kwargs.get("ids")
            mutation = kwargs.get("mutation", False)
            company_id = kwargs.get("company_id")  # added parameter to get company_id
            records = retrieve_records(model, field, variables, ids, mutation, company_id)
            if not records:
                raise GraphQLError(f"No {model_name} record found with id(s) {ids}")
            if isinstance(records, list):
                return [dict(r.read([field])) for r in records]
            return dict(records.read([field]))

        return resolve





    def get_query(self):
        queries = []
        for model_name in http.request.env:
            model = http.request.env[model_name]
            if not model._abstract and hasattr(model, "_graphql"):
                queries.append(model._graphql)
        return parse("\n".join(queries))

    def get_field_resolver(self):
        def resolve(model_name, info, **kwargs):
            try:
                model = http.request.env[model_name]
            except Exception:
                raise GraphQLError(f"Model {model_name} not found")
            field = info.field_name
            variables = info.variable_values
            ids = kwargs.get("ids")
            mutation = kwargs.get("mutation", False)
            company_id = kwargs.get("company_id")  # added parameter to get company_id
            records = retrieve_records(model, field, variables, ids, mutation, company_id)
            if not records:
                raise GraphQLError(f"No {model_name} record found with id(s) {ids}")
            if isinstance(records, list):
                return [dict(r.read([field])) for r in records]
            return dict(records.read([field]))

        return resolve

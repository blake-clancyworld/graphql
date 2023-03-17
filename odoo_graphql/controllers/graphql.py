from odoo import http
from odoo.http import request, content_disposition
import json
from ..utils import handle_graphql
from ..auth import authenticate_and_execute
import logging

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)

class GraphQL(http.Controller):
    @http.route(
        "/graphql", auth="public", type="http", website=True, sitemap=False, csrf=False, methods=["POST"]
    )
    def graphql(self, **data):
        data = json.loads(request.httprequest.data.decode())  # Read request data as JSON
        query = data.get("query")
        _logger.info(f"Received data: {data}")  # Add this line for debugging
        _logger.info(f"Received query: {query}")  # Add this line for debuggin
        variables = data.get("variables") or {}
        operation_name = data.get("operationName")
        auth = data.get("auth") or {}
        
        def query_with_context(request, user):
            response = request.env["graphql.handler"].handle_query(query)
            return json.dumps(response, default=str)

        if auth:
            result = authenticate_and_execute(query_with_context, auth)
        else:
            result = query_with_context(request, request.env.user)

        return result

    @http.route(
        "/graphql/schema",
        auth="public",
        type="http",
        website=True,
        sitemap=False,
        csrf=False,
    )
    def graphql_schema(self):
        # Nb: Not meant to be displayed
        content = request.env["graphql.handler"].schema()
        response = request.make_response(
            content,
            headers=[
                ("Content-Type", "application/graphql"),
                ("Content-Disposition", content_disposition("schema.graphql")),
            ],
        )
        return response

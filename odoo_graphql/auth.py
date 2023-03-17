from odoo import http
from odoo.http import request
import json

def authenticate_and_execute(query, auth):
    # Authenticate user
    user = request.env['res.users'].sudo().search([('login', '=', auth['login'])])
    if not user:
        return {'error': 'Invalid login'}
    
    if not user.check_credentials(auth['password']):
        return {'error': 'Invalid password'}

    # Set company
    if 'company_id' in auth:
        user.write({'company_id': int(auth['company_id'])})
        request.env.context = dict(request.env.context, allowed_company_ids=[int(auth['company_id'])])

    # Execute query
    result = query(request, user)
    return result

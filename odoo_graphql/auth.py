import odoo
from odoo import api, registry

def authenticate_user(dbname, login, password):
    try:
        odoo.registry(dbname)
    except Exception:
        return None

    with odoo.api.Environment.manage():
        try:
            uid = odoo.http.request.session.authenticate(dbname, login, password)
            if uid:
                return odoo.http.request.env.user
        except Exception:
            return None
    return None

def authenticate_and_execute(fn, auth):
    dbname = odoo.http.request.session.db
    login = auth.get("login")
    password = auth.get("password")
    user = authenticate_user(dbname, login, password)
    
    if user:
        company_id = auth.get("company_id")
        if company_id:
            user.write({'company_id': int(company_id)})
            user.write({'company_ids': [(4, int(company_id))]})
        
        return fn(odoo.http.request, user)
    else:
        return {
            "data": None,
            "errors": {
                "message": "Authentication failed"
            }
        }

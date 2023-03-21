from . import utils


def resolve_relation_field(self, info, field_name, field_def):
    model_name = field_def.comodel_name
    ids = self[field_name].ids
    env = info.context["env"]
    # Get company_id from auth
    company_ids = None
    if 'auth' in info.context:
        company_ids = info.context['auth'].get('company_ids')
    # Retrieve records based on company_id
    records = utils.retrieve_records(env, model_name, ids=ids, company_ids=company_ids)
    return records

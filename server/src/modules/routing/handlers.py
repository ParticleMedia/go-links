import os
from urllib import parse

from flask import Blueprint, request, redirect
from flask_login import current_user

from modules.links.helpers import get_shortlink, get_canonical_keyword, are_keywords_punctuation_sensitive, is_using_alternative_keyword_resolution
from shared_helpers import config
from shared_helpers.events import enqueue_event

try:
  from commercial.routing import ROUTERS
except ModuleNotFoundError:
  ROUTERS = []


routes = Blueprint('routing', __name__,
                   template_folder='../../static/templates')


def check_namespace(user_org, shortpath, provided_shortpath):
  shortpath_parts = shortpath.split('/', 1)
  if len(shortpath_parts) > 1:
    org_namespaces = config.get_organization_config(user_org).get('namespaces')
    if org_namespaces:
      shortpath_start, shortpath_remainder = shortpath_parts

      if shortpath_start in org_namespaces:
        return shortpath_start, shortpath_remainder, provided_shortpath.split('/', 1)[1]

  return config.get_default_namespace(user_org), shortpath, provided_shortpath


def queue_event(org_id, followed_at, shortlink_id, destination, accessed_via, email=None):
  enqueue_event(org_id,
                'link_follow.created',
                'link_follow',
                {'link_id': shortlink_id,
                 'user_email': email or current_user.email,
                 'access_method': accessed_via,
                 'destination': destination},
                timestamp=followed_at)


@routes.route('/<path:path>', methods=['GET'])
def get_go_link(path):
  organization = getattr(current_user, 'organization', os.environ.get('DEFAULT_ORGANIZATION'))

  provided_shortpath = parse.unquote(path.strip('/'))
  shortpath_parts = provided_shortpath.split('/', 1)

  org_config = config.get_organization_config(organization)
  # note: we can't remove all punctuation here because punctuation may be part of a programmatic link parameter
  alternative_resolution_mode = is_using_alternative_keyword_resolution(org_config)
  keywords_punctuation_sensitive = are_keywords_punctuation_sensitive(org_config)
  shortpath = '/'.join([get_canonical_keyword(keywords_punctuation_sensitive, shortpath_parts[0].lower())] + shortpath_parts[1:])

  namespace, shortpath, provided_shortpath = check_namespace(organization, shortpath, provided_shortpath)

  matching_shortlink, destination = get_shortlink(organization,
                                                  keywords_punctuation_sensitive,
                                                  alternative_resolution_mode,
                                                  namespace,
                                                  shortpath)

  if matching_shortlink:
    return redirect(str(destination))
  else:
    if not getattr(current_user, 'email', None):
      return redirect('/_/auth/login?%s' % parse.urlencode({'redirect_to': request.full_path}))

    for router in ROUTERS:
      response = router(current_user.organization, namespace, shortpath)

      if response:
        return response

    create_link_params = {'sp': provided_shortpath.lower()}
    if namespace != config.get_default_namespace(current_user.organization):
      create_link_params['ns'] = namespace

    return redirect(
      '%s/?%s'
      % ('http://localhost:5007' if request.host.startswith('localhost') else '',
         parse.urlencode(create_link_params))
    )

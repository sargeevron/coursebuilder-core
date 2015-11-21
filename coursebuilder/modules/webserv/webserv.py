# Copyright 2015 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Webserv, a module for static content publishing.

  TODO(psimakov):
      - add support for document_roots/sample/_static/*.*
      - map vfs folder
      - add caching directives
          - cache files of type: none, all but html/md, all
          - cache duration: none, 5 min, 1 h, 4 h, 24 h
      - cache various streams (and especially md/jinja) in memcache
      - try to support gcb tags without {{ ... }} notation

"""

__author__ = 'Pavel Simakov (psimakov@google.com)'


import collections
import mimetypes
import os
import re

import markdown

import appengine_config
from common import jinja_utils
from common import safe_dom
from common import schema_fields
from controllers import sites
from controllers import utils
from models import courses
from models import custom_modules
from modules.courses import lessons
from modules.courses import settings


WEBSERV_SETTINGS_SCHEMA_SECTION = 'modules:webserv'
WEBSERV_ENABLED = 'enabled'
WEBSERV_SLUG = 'slug'
WEBSERV_DOC_ROOTS_DIR_NAME = 'document_roots'
WEBSERV_DOC_ROOT = 'doc_root'
WEBSERV_JINJA_ENABLED = 'jinja_enabled'
WEBSERV_MD_ENABLED = 'md_enabled'
WEBSERV_AVAILABILITY = 'availability'

BANNED_SLUGS = set(['admin', 'dashboard'])
GOOD_SLUG_REGEX = '^[A-Za-z0-9_-]*$'

ADMIN_HOME_PAGE = '/admin/welcome'
COURSE_HOME_PAGE = '/course?use_last_location=true'
REGISTER_HOME = '/register'

AVAILABILITY_SELECT_DATA = [
    (courses.AVAILABILITY_UNAVAILABLE, 'Private'),
    (courses.AVAILABILITY_COURSE, 'Course'),
    (courses.AVAILABILITY_AVAILABLE, 'Public'),]

webserv_module = None


def get_config(app_context):
    return app_context.get_environ().get(
        'modules', {}).get('webserv', {})


def get_slug(config):
    slug = config.get(WEBSERV_SLUG)
    return '/%s' % slug if slug else '/'


def make_doc_root_select_data():
    select_data = []
    for _, dirs, _ in os.walk(os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            WEBSERV_DOC_ROOTS_DIR_NAME)):
        for adir in dirs:
            select_data.append((adir, adir))
        del dirs[:]
    return sorted(select_data)


def slug_validator(value, errors):
    if value:
        if value in BANNED_SLUGS:
            errors.append('Slug value of %s is not allowed' % value)
        if not re.match(GOOD_SLUG_REGEX, value):
            errors.append(
                'Slug value %s contains invalid characters; '
                'valid characters are A..Z, a..z, 0..9, _ and -.' % value)


class WebServerDisplayableElement(object):

    def __init__(self, availability):
        self.availability = availability
        self.shown_when_unavailable = False


class RootHandler(utils.ApplicationHandler, utils.QueryableRouteMixin):
    """Handles routing to '/'."""

    @classmethod
    def can_handle_route_method_path_now(cls, route, method, path):
        index = sites.get_course_index()
        app_context = index.get_course_for_path('/')
        if app_context:
            config = get_config(app_context)
            if config.get(WEBSERV_ENABLED):
                slug = get_slug(config)
                if slug == '/':
                    return False
        return True

    def get(self):
        index = sites.get_course_index()
        if index.get_all_courses():
            course = index.get_course_for_path('/')
            if not course:
                course = index.get_all_courses()[0]
            config = get_config(course)
            if config.get(WEBSERV_ENABLED):
                location = get_slug(config)
                if location != '/':
                    location += '/'
            else:
                location = COURSE_HOME_PAGE
            self.redirect(utils.ApplicationHandler.canonicalize_url_for(
                course, location), normalize=False)
        else:
            self.redirect(ADMIN_HOME_PAGE)


class WebServer(lessons.CourseHandler, utils.StarRouteHandlerMixin):
    """A class that will handle web requests."""

    def get_base_path(self, config):
        web_server_slug = get_slug(config)
        course_slug = self.app_context.get_slug()
        path = ''
        if course_slug != '/':
            path = course_slug
            if web_server_slug != '/':
                path += web_server_slug
        else:
            path = web_server_slug
        return path

    def get_mime_type(self, filename, default='application/octet-stream'):
        guess = mimetypes.guess_type(filename)[0]
        if guess is None:
            return default
        return guess

    def prepare_metadata(self, course_availability, student):
        env = self.app_context.get_environ()
        self.init_template_values(env)
        self.set_common_values(
            env, student, self.get_course(), course_availability)
        self.template_value['gcb_os_env'] = os.environ
        self.template_value['gcb_course_env'] = self.app_context.get_environ()

    def get_metadata(self):
        metadata = {}
        metadata.update(self.template_value.items())
        del metadata['course_info']
        return collections.OrderedDict(sorted(metadata.items())).items()

    def render_jinja(self, config, relname=None, from_string=None):
        assert relname or from_string
        template_dirs = [
            os.path.join(
                appengine_config.BUNDLE_ROOT, 'modules', 'webserv',
                WEBSERV_DOC_ROOTS_DIR_NAME, config.get(WEBSERV_DOC_ROOT)),
            os.path.join(
                appengine_config.BUNDLE_ROOT, 'views')]

        if from_string:
            template = jinja_utils.create_and_configure_jinja_environment(
                template_dirs, handler=self).from_string(from_string)
        else:
            template = jinja_utils.get_template(
                relname, template_dirs, handler=self)

        self.response.headers['Content-Type'] = 'text/html'
        self.template_value['gcb_webserv_metadata'] = self.get_metadata()
        self.response.write(template.render(self.template_value))

    def do_plain(self, config, filename, relname):
        with open(filename, 'r') as stream:
            self.response.headers[
                'Content-Type'] = self.get_mime_type(filename)
            self.response.write(stream.read())

    def do_html(self, config, filename, relname):
        if not config.get(WEBSERV_JINJA_ENABLED):
            self.do_plain(config, filename, relname)
            return

        self.render_jinja(config, relname=relname)

    def do_markdown(self, config, filename, relname):
        if not config.get(WEBSERV_MD_ENABLED):
            self.do_plain(config, filename, relname)
            return

        text = markdown.markdown(open(filename, 'r').read().decode('utf-8'))
        if config.get(WEBSERV_JINJA_ENABLED):
            self.render_jinja(config, from_string=text)
            return

        self.response.headers['Content-Type'] = 'text/html'
        self.response.write(text)

    def replace_last(self, text, find, replace):
        li = text.rsplit(find, 1)
        return replace.join(li)

    def get_target_filename(self, doc_root, relname, config):
        doc_root = os.path.normpath(doc_root)
        base_name = os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            WEBSERV_DOC_ROOTS_DIR_NAME, doc_root)

        # try filename as given
        filename = base_name + relname
        if os.path.isfile(filename):
            return filename, relname

        # try index.html assuming this filename is folder
        if os.path.isdir(filename):
            filename = os.path.join(filename, 'index.html')
            relname = '/index.html'
            if os.path.isfile(filename):
                return filename, relname

        # try alternative filename for markdown
        if config.get(WEBSERV_MD_ENABLED) and filename.endswith('.html'):
            relname = self.replace_last(relname, '.html', '.md')
            filename = self.replace_last(filename, '.html', '.md')
            if os.path.isfile(filename):
                return filename, relname

        return None, None

    def serve_resource(self, config, relname):
        doc_root = config.get(WEBSERV_DOC_ROOT)
        if not doc_root:
            self.error(404, 'No doc_root')
            return

        # get absolute filename of requested file
        filename, relname = self.get_target_filename(doc_root, relname, config)
        if filename is None:
            self.error(404, 'Bad filename %s' % filename)
            return

        # map to a specific processor based on extension
        _, ext = os.path.splitext(filename)
        if ext:
            ext = ext[1:]
        extension_to_target = {'html': self.do_html, 'md': self.do_markdown}
        target = extension_to_target.get(ext, self.do_plain)

        # render
        target(config, filename, relname)

    def webserv_get(self, config, relname):
        course_avail = self.get_course().get_course_availability()
        self_avail = config.get(WEBSERV_AVAILABILITY)

        # get user, student
        user, student, profile = self.get_user_student_profile()
        self.prepare_metadata(course_avail, student)

        # check rights
        displayability = courses.Course.get_element_displayability(
            course_avail, student.is_transient,
            custom_modules.can_see_drafts(self.app_context),
            WebServerDisplayableElement(self_avail))
        if not displayability.is_link_displayed:
            self.error(404, 'Negative displayability: %s' % str(displayability))
            return

        # render content
        return self.serve_resource(config, relname)

    def get(self):
        config = get_config(self.app_context)

        # first take care of URL that have no ending slash; these can be
        # '/course_slug' or '/course_slug/web_server_slug'; note that either
        # can be '/'
        base_path = self.get_base_path(config)

        if base_path == self.request.path and (
                base_path != '/') and config.get(WEBSERV_ENABLED):
            self.redirect(base_path + '/', normalize=False)
            return

        if (self.request.path).startswith(
                base_path) and config.get(WEBSERV_ENABLED):
            # handle '/course_slug/web_server_slug' requests if path matches
            if base_path == '/':
                relname = self.request.path
            else:
                relname = self.request.path[len(base_path):]
            self.webserv_get(config, relname)
        else:
            if self.path_translated in ['/', '/course']:
                # dispatch to existing course handler
                super(WebServer, self).get()
            else:
                self.error(404, 'No handlers found')


def get_schema_fields():
    enabled = schema_fields.SchemaField(
        WEBSERV_SETTINGS_SCHEMA_SECTION + ':' + WEBSERV_ENABLED,
        'Enable Web Server', 'boolean', optional=True, i18n=False,
        description=str(safe_dom.NodeList(
            ).append(safe_dom.Text(
                'If checked, static content uploaded for this course '
                'will be served. ')
            ).append(safe_dom.assemble_link(
                'TBD', 'Learn more...', target="_blank"))))
    slug = schema_fields.SchemaField(
        WEBSERV_SETTINGS_SCHEMA_SECTION + ':' + WEBSERV_SLUG,
        'URL Component', 'string', optional=True, i18n=False,
        validator=slug_validator,
        description='This is added to the end of the course URL to '
            'access the web server content root. If blank, the root '
            'course URL is used.')
    doc_root = schema_fields.SchemaField(
        WEBSERV_SETTINGS_SCHEMA_SECTION + ':' + WEBSERV_DOC_ROOT,
        'Content Root', 'string', optional=True, i18n=False,
        select_data=make_doc_root_select_data(),
        description=str(safe_dom.NodeList(
            ).append(safe_dom.Text(
                'This is the directory within /modules/webserv/document_roots '
                'to use as the web server content root. ')
            ).append(safe_dom.assemble_link(
                'TBD', 'Learn more...', target="_blank"))))
    enabled_jinja = schema_fields.SchemaField(
        WEBSERV_SETTINGS_SCHEMA_SECTION + ':' + WEBSERV_JINJA_ENABLED,
        'Process Templates', 'boolean', optional=True, i18n=False,
        description='If checked, the Jinja Template Processor will be applied '
            'to *.html files before serving them.')
    enabled_md = schema_fields.SchemaField(
        WEBSERV_SETTINGS_SCHEMA_SECTION + ':' + WEBSERV_MD_ENABLED,
        'Process Markdown', 'boolean', optional=True, i18n=False,
        description='If checked, the Markdown Processor will be applied to '
            '*.md files before serving them.')
    availability = schema_fields.SchemaField(
        WEBSERV_SETTINGS_SCHEMA_SECTION + ':' + WEBSERV_AVAILABILITY,
        'Availability', 'boolean', optional=True, i18n=False,
        default_value=courses.AVAILABILITY_COURSE,
        select_data=AVAILABILITY_SELECT_DATA,
        description=str(safe_dom.NodeList(
            ).append(safe_dom.Text(
                'Web pages default to the availability of the course, but may '
                'also be restricted to admins (Private) or open to the public '
                '(Public). ')
            ).append(safe_dom.assemble_link(
                'TBD', 'Learn more...', target="_blank"))))

    return (
        lambda _: enabled, lambda _: slug, lambda _: doc_root,
        lambda _: enabled_jinja, lambda _: enabled_md, lambda _: availability)


def register_module():
    """Registers this module in the registry."""

    def notify_module_enabled():
        courses.Course.OPTIONS_SCHEMA_PROVIDERS[
            WEBSERV_SETTINGS_SCHEMA_SECTION] += get_schema_fields()
        settings.CourseSettingsHandler.register_settings_section(
            WEBSERV_SETTINGS_SCHEMA_SECTION, title='Web server ')

    global_routes = [('/', RootHandler)]
    namespaced_routes = [('/', WebServer)]

    global webserv_module  # pylint: disable=global-statement
    webserv_module = custom_modules.Module(
        'Webserv, a module for static content serving.',
        'A simple way to publish static web pages with your course content.',
        global_routes, namespaced_routes,
        notify_module_enabled=notify_module_enabled)

    return webserv_module

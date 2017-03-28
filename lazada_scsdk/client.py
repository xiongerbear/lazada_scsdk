import requests
import json
import urllib
import urllib.request
from hashlib import sha256
from hmac import HMAC
from datetime import datetime, tzinfo, timedelta
from . import resources
from types import ModuleType
import xml.etree.ElementTree as ET
from .errors import BaseError


class Zone(tzinfo):
    def __init__(self, offset, isdst, name):
        self.offset = offset
        self.isdst = isdst
        self.name = name

    def utcoffset(self, dt):
        return timedelta(hours=self.offset) + self.dst(dt)

    def dst(self, dt):
            return timedelta(hours=1) if self.isdst else timedelta(0)

    def tzname(self, dt):
        return self.name

# Create a dict of resource classes
RESOURCE_CLASSES = {}
for name, module in resources.__dict__.items():
    if isinstance(module, ModuleType) and name.capitalize() in module.__dict__:
        RESOURCE_CLASSES[name] = module.__dict__[name.capitalize()]


def _merge(*args):
    """
    Merge one or more objects into a new object
    """
    result = {}
    [result.update(obj) for obj in args]
    return result


class Client:
    DEFAULTS = {
        'base_url': 'https://api.sellercenter.lazada.vn/',
        'api_version': '1.0',
        'api_format': 'json'
    }

    CLIENT_OPTIONS = set(DEFAULTS.keys())
    QUERY_OPTIONS = set(['from', 'to', 'count', 'skip'])
    REQUEST_OPTIONS = set(['params', 'data'])

    ALL_OPTIONS = CLIENT_OPTIONS | QUERY_OPTIONS | REQUEST_OPTIONS

    def __init__(self, email=None, api_key=None, **options):
        self.email = email
        self.api_key = api_key

        # merge the provided options (if any) with the global DEFAULTS
        self.options = _merge(self.DEFAULTS, options)

        # intializes each resource
        # injecting this client object into the constructor
        for name, Klass in RESOURCE_CLASSES.items():
            setattr(self, name, Klass(self))

    def request(self, method, action, **options):
        """
        Dispatches a request to the Lazada API
        """
        options = self._merge_options(options)

        request_options = self._parse_request_options(options)

        gmt7 = Zone(7, False, 'GMT+7')

        parameters = {
            'UserID': self.email,
            'Version': self.options['api_version'],
            'Action': action,
            'Format': self.options['api_format'],
            'Timestamp': datetime.now(gmt7).replace(microsecond=0).isoformat()
        }

        """
        Include extra request param
        """
        if 'params' in request_options:
            parameters = _merge(parameters, request_options['params'])

        """
        Generate Signature
        """
        concatenated = urllib.parse.urlencode(sorted(parameters.items()))
        concatenated = concatenated.replace('+', '%20')
        parameters['Signature'] = HMAC(self.api_key.encode(), concatenated.encode(), sha256).hexdigest()
        url = self.options['base_url'] + '?' + urllib.parse.urlencode(parameters)

        print(url)

        if(method == 'get'):
            response = requests.get(url)
        else:
            response = requests.post(url, data=self._prepare_xml(request_options['data']))

        if(response.ok):
            if(self.options['api_format'] == 'json'):
                return self._check_json_response(response.json())
            return self._check_xml_response(response.text)

        return response.raise_for_status()

    def get(self, action, **options):
        """
        Parses GET request options and dispatches a request
        """
        query_options = self._parse_query_options(options)
        parameter_options = self._parse_parameter_options(options)
        # options in the query takes precendence
        query = _merge(query_options, parameter_options)
        return self.request('get', action, params=query, **options)

    def post(self, action, data, **options):
        """
        Parses POST request options and dispatches a request
        """
        return self.request('post', action, data=data, **options)

    def _check_json_response(self, json_dict):
        if 'ErrorResponse' in json_dict:
            message = json_dict['ErrorResponse']['Head']['ErrorMessage']
            if 'Body' in json_dict['ErrorResponse']:
                for err in json_dict['ErrorResponse']['Body']['Errors']:
                    message += "\n" + str(json_dict['ErrorResponse']['Body']['Errors'])

            raise BaseError(
                code=json_dict['ErrorResponse']['Head']['ErrorCode'],
                message=message
            )

        return json_dict

    def _check_xml_response(self, xmlstring):
        tree = ET.ElementTree(ET.fromstring(xmlstring))
        root = tree.getroot()
        if root.tag == 'ErrorResponse':
            head = root.find('Head')
            body = root.find('Body')
            message = head.find('ErrorMessage').text
            if body is not None:
                message += "\n" + ET.tostring(body).decode('utf-8')

            raise BaseError(
                code=head.find('ErrorCode').text,
                message=message
            )

        return xmlstring

    def _prepare_xml(self, xmlstring):
        tree = ET.ElementTree(ET.fromstring(xmlstring))
        return ET.tostring(tree.getroot())

    def _merge_options(self, *objects):
        """
        Merges one or more options objects with client's options
        returns a new options object
        """
        return _merge(self.options, *objects)

    def _parse_query_options(self, options):
        """
        Selects query string options out of the provided options object
        """
        return self._select_options(options, self.QUERY_OPTIONS)

    def _parse_parameter_options(self, options):
        """
        Selects all unknown options
        (not query string, API, or request options)
        """
        return self._select_options(options, self.ALL_OPTIONS, invert=True)

    def _parse_request_options(self, options):
        """
        Select and formats options to be passed to
        the 'requests' library's request methods
        """
        request_options = self._select_options(options, self.REQUEST_OPTIONS)
        if 'params' in request_options:
            params = request_options['params']
            for key in params:
                if isinstance(params[key], bool):
                    params[key] = json.dumps(params[key])

        return request_options

    def _select_options(self, options, keys, invert=False):
        """
        Selects the provided keys (or everything except the provided keys)
        out of an options object
        """
        options = self._merge_options(options)
        result = {}
        for key in options:
            if (invert and key not in keys) or (not invert and key in keys):
                result[key] = options[key]
        return result
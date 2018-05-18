"""
This module is the core of the Python's client. It handles all the
requests made to the API and parses the response in order make the
interactions with the API as easy as possible. The initialization of the
RadarlyApi's object defined here is the first step to start using the API.
We advise you to use a default RadarlyAPI object otherwise you must be specify
a RadarlyApi object each time you want to retrieve documents from the API.
To initialize a default API, simply run:

>>> from radarly.api import RadarlyApi
>>> RadarlyApi.init(client_id=<client_id>, client_secret=<client_secret>)

Now you don't have to try to get an access token or check if the access
token has expired: we check it for you!
"""

import json
from datetime import datetime
from os import getenv

import requests
from lxml import html

from .auth import RadarlyAuth
from .exceptions import BadAuthentication, NoInitializedApi, RateReached
from .rate import RateLimit
from .utils.jsonparser import radarly_decoder as _decoder


__all__ = ['RadarlyApi']


def _parse_error_response(response):
    """Parse an error response made with the request module
    in order to extract information about the error.

    Args:
        response (requests.Response): error response get from
            a request made with requests.
    Returns:
        dict: dictionary with information about the error,
        parsed from the content of th response
    """
    error_data = dict()
    error_data['error_code'] = response.status_code
    content_type = response.headers.get('Content-Type', '')
    if content_type == 'text/html':
        document = html.fromstring(response.text)
        error_data['error_type'] = document.xpath('//title/text()')
        try:
            element = document.xpath("//p[@id='detail']/text()")
            error_data['error_message'] = element[0]
        except IndexError:
            error_data['error_message'] = ''
    elif content_type == 'application/json':
        error_data.update(response.json())
    return error_data


class RadarlyApi: # pylint: disable=R0902
    """Main interface with the Radarly's API. It defines several methods in
    order to ease the interaction with the Radarly's API. For example, it
    defines the methods in order to authenticate to the API or to refresh the
    tokens. Thanks to the current implementation of the package, you can use
    ``radarly`` without using any of the ``RadarlyApi``'s methods.

    Args:
        client_id (str): client ID which is given by Linkfluence in order to
            use the API.
        client_secret (str): code given by Linkfluence in order to ensure that
            is the right user which is using the API. This code must never go
            public.
        access_token (str): code generated by the API in order to authenticate
            each request. This code is automatically retrieved by the
            RadarlyApi during its initilization. The access token has a limited
            lifetime and must be refreshed when it has expired.
        refresh_token (str): code used to generate a new access token when
            you've got an expired token. The RadarlyApi can automatically use
            this refresh token to update the access token when it's expired.
        autorefresh (bool, optional): Whether or not refresh the access token
            when it's expired. Default to True.
        timeout (float): maximum duration during which the API will wait for an
            answer from the Radarly's server.
        proxies (dict): proxies used for the requests. The proxies must be set
            in the same way that in the ``requests`` module.
        rates (RateLimit): RateLimit object which can be used to know the
            current number of requests made and how many left you can do.
    """
    root_url = 'https://radarly.linkfluence.com'
    login_url = 'https://oauth.linkfluence.com/oauth2/token'
    version = '1.0'
    _default_api = None

    def __init__(self, # pylint: disable=C0303
                 client_id=None,
                 client_secret=None,
                 scope=None,
                 autorefresh=True,
                 timeout=None,
                 proxies=None,
                 _authenticate=True):
        client_id = client_id or getenv('RADARLY_CLIENT_ID')
        client_secret = client_secret or getenv('RADARLY_CLIENT_SECRET')
        if not(client_id and client_secret):
            raise KeyError(("Neither client_id nor client_secret has been set "
                            "during the initialization of the API. Furthermore "
                            "RADARLY_CLIENT_ID and RADARLY_CLIENT_SECRET"
                            "variables have not be found in environment "
                            "variables. You must either specify the client_id "
                            "and client_secret arguments or set the right "
                            "environment variables to start using the "
                            "client."))
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.refresh_token = None
        self.timeout = timeout
        self.proxies = proxies
        self.autorefresh = autorefresh
        self.last_refresh = datetime.now()
        self._auth = None
        self.rates = RateLimit()
        self.scope = scope or [
            'listening',
            'historical-data',
            'social-performance'
        ]
        if _authenticate:
            self.authenticate()

    def __repr__(self):
        return '<RadarlyAPI.client_id={.client_id}>'.format(self)

    @classmethod
    def init(cls, *args, **kwargs):
        """
        Initialize a RadarlyAPI and set it as default api. The default API is
        the one that will be used each time you made a request if no API is
        passed in the parameter.

        Args:
            client_id (str): client_id you want to use to access data
            client_secret (str): secret token given by Linkfluence.
            autorefresh (bool, optional): whether or not refresh automatically
                the acces_token when it's expired.
            scope (list[str]): list of scope
            timeout (float): timeout for the requests
            proxies (dict): proxies to use for the requests.
        """
        api = cls(*args, **kwargs)
        cls.set_default_api(api)
        return api

    @classmethod
    def get_default_api(cls):
        """
        Retrieve the default api previously set by the user.

        Raises:
            AssertionError: raised if no api was set as default api.
                Use ``init`` method to set a default API.
        Returns:
            RadarlyApi: api object you have previously initialized
        """
        if cls._default_api is None:
            raise NoInitializedApi
        return cls._default_api

    @classmethod
    def set_default_api(cls, api):
        """Set a default API for the client. This method is automatically
        called when you use the ``init`` class method."""
        assert isinstance(api, cls), ("Only a RadarlyApi object can "
                                      "be set as default api")
        cls._default_api = api
        return None

    @classmethod
    def set_version(cls, version):
        """Set the version of the API. For now, only the '1.0' is supported.

        Args:
            version (string): version of the API you want to use
        Returns:
            string: version set for the API
        """
        cls.version = version
        return cls.version

    def request(self, verb, url, **kwargs):
        """
        Send a request using the request module. Some pre- and post-tasks
        are computed each time in order to actualize the rates information
        and check whether or not the request is a success. This method uses
        the same parameters as request function of requests module so you can
        easily made your own authenticated request.

        Args:
            verb (string): method used for the request
            url (string): url to ask
            **kwargs: keywords arguments sent with request
        Raises:
            HTTP Error: raised if the request failed for an unknown cause
        Returns:
            dict: corresponds to the response data of the answer
        """
        url = url.strip('/')
        if self._auth is None:
            self.authenticate()
        if self.version and not url.startswith(self.version) \
            and not url.startswith(self.root_url):
            url = '{}/{}'.format(self.version, url)
        url = url if self.root_url in url  \
            else '{}/{}'.format(self.root_url, url)
        kwargs.setdefault('headers', {})
        kwargs['headers'].setdefault('Content-Type', 'application/json')
        if ('data' in kwargs and
                kwargs['headers']['Content-Type'] == 'application/json'):
            kwargs['data'] = json.dumps(kwargs['data'])
        kwargs.setdefault('timeout', self.timeout)
        kwargs.setdefault('proxies', self.proxies)
        if self.rates.is_reached(url):
            raise RateReached('No more request available')

        res = requests.request(verb, url, auth=self._auth, **kwargs)

        try:
            res.raise_for_status()
        except requests.exceptions.HTTPError as err:
            error_data = _parse_error_response(res)
            error_type = error_data.get('error_type', '')
            if error_type == 'ExpiredTokenException' and self.autorefresh:
                self.refresh()
                res = requests.request(verb, url, auth=self._auth, **kwargs)
                res.raise_for_status()
            else:
                raise err
        self.rates.update(url, res.headers)

        return res.json(object_hook=_decoder)

    def get(self, url, **kwargs):
        """Shortcut for the ``request`` method with 'GET' as verb.

        Args:
            url (string): url to ask
            **kwargs: keywords arguments sent with ``request``
        Raises:
            HTTP Error: raised if the request failed for an unknown cause
        Returns:
            dict: corresponds to the response data of the answer
        """
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs):
        """Shortcut for the ``request`` method with 'POST' as verb.

        Args:
            url (string): url to ask
            **kwargs: keywords arguments sent with request
        Raises:
            HTTP Error: raised if the request failed for an unknown cause
        Returns:
            dict: corresponds to the response data of the answer
        """
        return self.request('POST', url, **kwargs)

    def put(self, url, **kwargs):
        """Shortcut for the ``request`` method with 'PUT' as verb.

        Args:
            url (string): url to ask
            **kwargs: keywords arguments sent with request
        Raises:
            HTTP Error: raised if the request failed for an unknown cause
        Returns:
            dict: corresponds to the response data of the answer
        """
        return self.request('PUT', url, **kwargs)

    def authenticate(self):
        """
        Enable the authentification to Radarly's API. The Radarly's API is
        currently using the OAUTH2 system for authorization : the
        (client_id, client_secret) will be used to generate an access_token
        and a refresh_token.

        Raises:
            BadAuthentication: raised if client_id or client_secret is
                incorrect
        Returns:
            None:
        """
        data = dict(
            client_id=self.client_id,
            client_secret=self.client_secret,
            grant_type='client_credentials',
            scope=' '.join(self.scope)
        )
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        kwargs = dict(
            data=data,
            headers=headers,
            proxies=self.proxies,
            timeout=self.timeout
        )
        auth_response = requests.request('POST', self.login_url, **kwargs)
        try:
            auth_response.raise_for_status()
        except requests.exceptions.HTTPError:
            raise BadAuthentication
        auth_response = auth_response.json()
        self.scope = auth_response.get('scope', '').split(' ')
        self.access_token = auth_response.get('access_token')
        self.refresh_token = auth_response.get('refresh_token')
        self._auth = RadarlyAuth(self.access_token)
        return None

    def refresh(self):
        """
        Refresh the access_token using the refresh_token as soon as the access
        token has expired. The auto-refresh behaviour can be ignored with
        the autorefresh attribute.
        """
        data = dict(
            client_id=self.client_id,
            client_secret=self.client_secret,
            grant_type='refresh_token',
            refresh_token=self.refresh_token,
        )
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        auth_response = requests.request('POST', self.login_url,
                                         data=data, headers=headers,
                                         proxies=self.proxies, timeout=self.timeout)
        auth_response = auth_response.json()
        self.access_token = auth_response.get('access_token')
        self.refresh_token = auth_response.get('refresh_token')
        self._auth = RadarlyAuth(self.access_token)
        self.last_refresh = datetime.now()
        return None

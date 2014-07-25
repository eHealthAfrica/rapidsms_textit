import json
import logging

from django.core.exceptions import ImproperlyConfigured
from django.core import signing

from rapidsms.backends.base import BackendBase

import requests


logger = logging.getLogger(__name__)

base_url = 'https://api.textit.in/api/v1.json'


class TextItBackend(BackendBase):
    """A RapidSMS backend for TextIt"""

    def configure(self, config=None, **kwargs):
        """
        We expect all of our config (apart from the ENGINE) to be
        in a dictionary called 'config' in our INSTALLED_BACKENDS entry
        """
        self.config = config or {}
        for key in ['api_token', 'number']:
            if key not in self.config:
                msg = "TextIt backend config must set '%s'; config is %r" %\
                      (key, config)
                raise ImproperlyConfigured(msg)
        if kwargs:
            msg = "All textit backend config should be within the `config`"\
                "entry of the backend dictionary"
            raise ImproperlyConfigured(msg)

    @property
    def token(self):
        return self.config['api_token']

    def execute_textit_program(self, program):
        """
        Ask TextIt to execute a program for us.

        We can't do this directly;
        we have to ask TextIt to call us back and then give TextIt the
        program in the response body to that request from TextIt.

        But we can pass data to TextIt and ask TextIt to pass it back
        to us when TextIt calls us back. So, we just bundle up the program
        and pass it to TextIt, then when TextIt calls us back, we
        give the program back to TextIt.

        We also cryptographically sign our program, so that
        we can verify when we're called back with a program, that it's
        one that we sent to TextIt and has not gotten mangled.

        See https://docs.djangoproject.com/en/1.4/topics/signing/ for more
        about the signing API.

        See http://textit.in/api/v1
        for the format we're using to call TextIt, pass it data, and ask
        them to call us back.



        :param program: A TextIt program, i.e. a dictionary with a 'textit'
            key whose value is a list of dictionaries, each representing
            a TextIt command.
        """
        # The signer will also "pickle" the data structure for us
        signed_program = signing.dumps(program)

        params = {
            'action': 'create',  # Required by TextIt
            'token': self.config['api_token'],  # Identify ourselves
            'program': signed_program,  # Additional data
        }
        data = json.dumps(params)

        # Tell TextIt we'd like our response in JSON format
        # and our data is in that format too.
        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
        }
        response = requests.post(base_url,
                                 data=data,
                                 headers=headers)

        # If the HTTP request failed, raise an appropriate exception - e.g.
        # if our network (or TextIt) are down:
        response.raise_for_status()

        result = json.loads(response.content)
        if not result['success']:
            raise Exception("TextIt error: %s" % result.get('error', 'unknown'))

    def send(self, id_, text, identities, context=None):
        """
        Send messages when using RapidSMS 0.14.0 or later.

        We can send multiple messages in one TextIt program, so we do
        that.

        :param id_: Unused, included for compatibility with RapidSMS.
        :param string text: The message text to send.
        :param identities: A list of identities to send the message to
            (a list of strings)
        :param context: Unused, included for compatibility with RapidSMS.
        """

        # Build our program
        from_ = self.config['number'].replace('-', '')
        commands = []
        for identity in identities:
            # We'll include a 'message' command for each recipient.
            # The TextIt doc explicitly says that while passing a list
            # of destination numbers is not a syntax error, only the
            # first number on the list will get sent the message. So
            # we have to send each one as a separate `message` command.
            commands.append(
                {
                    'message': {
                        'say': {'value': text},
                        'to': identity,
                        'from': from_,
                        'channel': 'TEXT',
                        'network': 'SMS'
                    }
                }
            )
            program = {
                'textit': commands,
            }
        self.execute_textit_program(program)

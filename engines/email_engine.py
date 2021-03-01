#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

# the first step is always the same: import all necessary components:
import configparser
import smtplib
import ssl
from socket import gaierror

from util import logger


class Email:
    def __init__(self):
        """
            Email Engine Constructor
        """
        self.config = configparser.ConfigParser()
        self.config.read("config.ini")

        self.port = self.config['Email'].get('port')
        self.smtp_server = self.config['Email'].get('smtp_server')
        self.sender = self.config['Email'].get('sender')
        self.login = self.config['Email'].get('login')
        self.password = self.config['Email'].get('password')

        # Create a secure SSL context
        self.context = ssl.create_default_context()

        self.default_logger = logger.get_logger("email")

    def write_email(self, receiver_name, message_content):
        # specify the sender’s and receiver’s email addresses
        receiver = receiver_name

        # type your message: use two newlines (\n) to separate the subject from the message body, and use 'f' to  automatically insert variables in the text
        message = f"""\
        Subject: Hi Mailtrap
        To: {receiver}
        From: {self.sender}
        {message_content}"""
        try:
            # send your message with credentials specified above
            with smtplib.SMTP(self.smtp_server, self.port) as server:
                server.starttls(context=self.context)  # Secure the connection
                server.login(self.login, self.password)
                server.sendmail(self.sender, receiver, message)

            self.default_logger.info('Sent')
        except (gaierror, ConnectionRefusedError):
            self.default_logger.info('Failed to connect to the server. Bad connection settings?')
        except smtplib.SMTPServerDisconnected:
            self.default_logger.info('Failed to connect to the server. Wrong user/password?')
        except smtplib.SMTPException as e:
            self.default_logger.info('SMTP error occurred: ' + str(e))

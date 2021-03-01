#  Futu Algo: Algorithmic High-Frequency Trading Framework
#  Copyright (c)  billpwchan - All Rights Reserved
#  Unauthorized copying of this file, via any medium is strictly prohibited
#  Proprietary and confidential
#  Written by Bill Chan <billpwchan@hotmail.com>, 2021

# the first step is always the same: import all necessary components:
import configparser
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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

    def write_email(self, receiver, message_content: dict):

        # type your message: use two newlines (\n) to separate the subject from the message body, and use 'f' to  automatically insert variables in the text

        message = MIMEMultipart("alternative")
        message["Subject"] = "Daily Filtered Stock List"
        message["From"] = self.sender
        message["To"] = receiver
        text = "Please kindly review today's chosen stock list! "
        html = """\
        <style>
        * {
          font-family: sans-serif; /* Change your font family */
        }
        
        .content-table {
          border-collapse: collapse;
          margin: 25px 0;
          font-size: 0.9em;
          min-width: 400px;
          border-radius: 5px 5px 0 0;
          overflow: hidden;
          box-shadow: 0 0 20px rgba(0, 0, 0, 0.15);
        }
        
        .content-table thead tr {
          background-color: #009879;
          color: #ffffff;
          text-align: left;
          font-weight: bold;
        }
        
        .content-table th,
        .content-table td {
          padding: 12px 15px;
        }
        
        .content-table tbody tr {
          border-bottom: 1px solid #dddddd;
        }
        
        .content-table tbody tr:nth-of-type(even) {
          background-color: #f3f3f3;
        }
        
        .content-table tbody tr:last-of-type {
          border-bottom: 2px solid #009879;
        }
        
        .content-table tbody tr.active-row {
          font-weight: bold;
          color: #009879;
        }

        </style>
        <table class="content-table">
          <thead>
            <tr>
              <th>Stock Code</th>
              <th>Company Name</th>
            </tr>
          </thead>
          <tbody>\n
        """
        for equity, values in message_content.items():
            html += f"""\
            <tr>
              <td>{equity}</td>
              <td>{values}</td>
            </tr>\n
            """
        html += """\
          </tbody>
        </table>
        """

        # Turn these into plain/html MIMEText objects
        part1 = MIMEText(text, "plain")
        part2 = MIMEText(html, "html")

        # Add HTML/plain-text parts to MIMEMultipart message
        # The email client will try to render the last part first
        message.attach(part1)
        message.attach(part2)

        try:
            # send your message with credentials specified above
            with smtplib.SMTP(self.smtp_server, self.port) as server:
                server.starttls(context=self.context)  # Secure the connection
                server.login(self.login, self.password)
                server.sendmail(self.sender, receiver, message.as_string())

            self.default_logger.info('Sent')
        except (gaierror, ConnectionRefusedError):
            self.default_logger.info('Failed to connect to the server. Bad connection settings?')
        except smtplib.SMTPServerDisconnected:
            self.default_logger.info('Failed to connect to the server. Wrong user/password?')
        except smtplib.SMTPException as e:
            self.default_logger.info('SMTP error occurred: ' + str(e))

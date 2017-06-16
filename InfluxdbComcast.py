from __future__ import print_function
import configparser
import os
import sys
import argparse
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError, InfluxDBServerError
import time
#import json
import re
import requests
import logging

class configManager():

    def __init__(self, config):
        print('Loading Configuration File {}'.format(config))
        self.test_server = []
        config_file = os.path.join(os.getcwd(), config)
        if os.path.isfile(config_file):
            self.config = configparser.ConfigParser()
            self.config.read(config_file)
        else:
            print('ERROR: Unable To Load Config File: {}'.format(config_file))
            sys.exit(1)

        self._load_config_values()
        print('Configuration Successfully Loaded')

    def _load_config_values(self):

        # General
        self.delay = self.config['GENERAL'].getint('Delay', fallback=2)
        self.output = self.config['GENERAL'].getboolean('Output', fallback=True)

        # InfluxDB
        self.influx_address = self.config['INFLUXDB']['Address']
        self.influx_port = self.config['INFLUXDB'].getint('Port', fallback=8086)
        self.influx_database = self.config['INFLUXDB'].get('Database', fallback='speedtests')
        self.influx_user = self.config['INFLUXDB'].get('Username', fallback='')
        self.influx_password = self.config['INFLUXDB'].get('Password', fallback='')
        self.influx_ssl = self.config['INFLUXDB'].getboolean('SSL', fallback=False)
        self.influx_verify_ssl = self.config['INFLUXDB'].getboolean('Verify_SSL', fallback=True)

        # Comcast
        self.comcast_user = self.config['COMCAST'].get('Username', fallback='')
        self.comcast_password = self.config['COMCAST'].get('Password', fallback='')


class InfluxdbComcastUsage():

    def __init__(self, config=None):

        self.config = configManager(config=config)
        self.output = self.config.output
        self.influx_client = InfluxDBClient(
            self.config.influx_address,
            self.config.influx_port,
            username=self.config.influx_user,
            password=self.config.influx_password,
            database=self.config.influx_database,
            ssl=self.config.influx_ssl,
            verify_ssl=self.config.influx_verify_ssl
        )

        self.used = None
        self.total = None
        self.unit = None

    def get_comcast_data(self):
        logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.WARN)
        logging.getLogger('requests').setLevel(logging.ERROR)

        session = requests.Session()

        username = self.config.comcast_user
        password = self.config.comcast_password

        logger.debug("Finding req_id for login...")
        res = session.get('https://login.comcast.net/login?r=comcast.net&s=oauth&continue=https%3A%2F%2Flogin.comcast.net%2Foauth%2Fauthorize%3Fclient_id%3Dmy-account-web%26redirect_uri%3Dhttps%253A%252F%252Fcustomer.xfinity.com%252Foauth%252Fcallback%26response_type%3Dcode%26state%3D%2523%252Fdevices%26response%3D1&client_id=my-account-web')
        assert res.status_code == 200
        m = re.search(r'<input type="hidden" name="reqId" value="(.*?)">', res.text)
        req_id = m.group(1)
        logger.debug("Found req_id = %r", req_id)

        data = {
            'user': username,
            'passwd': password,
            'reqId': req_id,
            'deviceAuthn': 'false',
            's': 'oauth',
            'forceAuthn': '0',
            'r': 'comcast.net',
            'ipAddrAuthn': 'false',
            'continue': 'https://login.comcast.net/oauth/authorize?client_id=my-account-web&redirect_uri=https%3A%2F%2Fcustomer.xfinity.com%2Foauth%2Fcallback&response_type=code&state=%23%2Fdevices&response=1',
            'passive': 'false',
            'client_id': 'my-account-web',
            'lang': 'en',
        }

        logger.debug("Posting to login...")
        res = session.post('https://login.comcast.net/login', data=data)
        assert res.status_code == 200

        logger.debug("Preloader HTML...")
        res = session.get('https://customer.xfinity.com/Secure/Preloading/?backTo=%2fMyServices%2fInternet%2fUsageMeter%2f')
        assert res.status_code == 200

        logger.debug("Preloader AJAX...")
        res = session.get('https://customer.xfinity.com/Secure/Preloader.aspx')
        assert res.status_code == 200

        logger.debug("Waiting 5 seconds for preloading to complete...")
        time.sleep(5)

        logger.debug("Fetching internet usage HTML...")
        res = session.get('https://customer.xfinity.com/MyServices/Internet/UsageMeter/')
        assert res.status_code == 200
        html = res.text

        # Example HTML:
        #    <div class="cui-panel-body">
        #        <!-- data-options:
        #                unit (string) - fills in labels; example: GB, MB, miles;
        #                max (number, optional) - the 100% number of the bar
        #                increment (number, optional) - the number between grid lines
        #                -->
        #        <span class="cui-usage-label"><p>Home Internet Usage</p></span>
        #        <div data-component="usage-meter"
        #            data-options="hideMax:true;divisions:4;
        #                          unit:GB;
        #                          max:1024;
        #                          increment:50
        #                          ">
        #            <div class="cui-usage-bar" data-plan="1024">
        #                <span data-used="222" data-courtesy="false">
        #                    <span class="accessibly-hidden">222GB of 1024GB</span>
        #                </span>
        #            </div>
        #            <div class="cui-usage-label">
        #                <span>
        #                    222GB of 1024GB
        #                </span>
        #                <!--<p><a href="#">View details</a></p>-->
        #                <span class="marker"></span>
        #            </div>
        #        </div>

        used = None
        m = re.search(r'<span data-used="(\d+)"', html)
        if m:
            used = int(m.group(1))

        total = None
        m = re.search(r'<div class="cui-usage-bar" data-plan="(\d+)">', html)
        if m:
            total = int(m.group(1))

        unit = None
        m = re.search(r'<div data-component="usage-meter"\s*data-options="([^"]*)"', html)
        if m:
            opts = m.group(1)
            opts = re.sub(r'\s+', '', opts)  # remove whitespace
            m = re.search(r'unit:(\w+);', opts)
            if m:
                unit = m.group(1)

        self.used = used
        self.total = total
        self.unit = unit
        # print(json.dumps({
        #     'used': used,
        #     'total': total,
        #     'unit': unit,
        # }))

    def send_results(self):

        input_points = [
            {
                'measurement': 'comcast_data_usage',
                'fields': {
                    'used': self.used,
                    'total': self.total,
                    'unit': self.unit
                }
            }
        ]

        if self.output:
            print('Used: {}'.format(str(self.used)))
            print('Total: {}'.format(str(self.total)))

        self.write_influx_data(input_points)

    def run(self):

        while True:

            self.get_comcast_data()

            self.send_results()

            time.sleep(self.config.delay)

    def write_influx_data(self, json_data):
        """
        Writes the provided JSON to the database
        :param json_data:
        :return:
        """
        if self.output:
            print(json_data)

        try:
            self.influx_client.write_points(json_data)
        except (InfluxDBClientError, ConnectionError, InfluxDBServerError) as e:
            if hasattr(e, 'code') and e.code == 404:

                print('Database {} Does Not Exist.  Attempting To Create'.format(self.config.influx_database))

                # TODO Grab exception here
                self.influx_client.create_database(self.config.influx_database)
                self.influx_client.write_points(json_data)

                return

            print('ERROR: Failed To Write To InfluxDB')
            print(e)

        if self.output:
            print('Written To Influx: {}'.format(json_data))


def main():

    parser = argparse.ArgumentParser(description="A tool to send Comcast data cap usage data to InfluxDB")
    parser.add_argument('--config', default='config.ini', dest='config', help='Specify a custom location for the config file')
    args = parser.parse_args()
    collector = InfluxdbComcastUsage(config=args.config)
    collector.run()


if __name__ == '__main__':
    main()

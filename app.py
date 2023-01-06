import logging
import os
import yaml
from configparser import Settings

# Config
config_file = os.environ.get('HISTOIRE_CONFIG', './config.yaml')
config_file_message = 'Failed to open ' + config_file + '{message}'
if not os.path.exists(config_file):
    if 'HISTOIRE_CONFIG' in os.environ:
        logging.critical(config_file_message.format(message=' as the file does not exist.'))
    else:
        logging.critical(config_file_message.format(
            message=' as the file does not exist. Another config file can be specified with the HISTOIRE_CONFIG '
                    'environment variable.'))
    exit(1)
settings = None
try:
    settings = Settings.parse_obj(yaml.safe_load(open(config_file)))
except yaml.YAMLError as e:
    logging.critical(config_file_message.format(message=': ' + str(e)), exc_info=True)
    exit(1)
import os


# phenix logging level. Options: ['DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL']
PHENIX_LOG_LEVEL = os.getenv('PHENIX_LOG_LEVEL', 'INFO')

# Path to phenix log file
PHENIX_LOG_FILE = os.getenv('PHENIX_LOG_FILE', '/var/log/phenix/phenix-apps.log')

# Base phenix data directory
PHENIX_DIR = os.getenv('PHENIX_DIR', '/phenix')

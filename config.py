import os
import sys

# RESOURCE_DIR is read-only program content after packaging; DATA_DIR is where
# each user keeps their own records and uploaded licence photos.
RESOURCE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if getattr(sys, 'frozen', False):
    if sys.platform == 'darwin':
        DATA_DIR = os.path.join(os.path.expanduser('~/Library/Application Support'), 'BWIH Dispatch')
    elif sys.platform == 'win32':
        DATA_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'BWIH Dispatch')
    else:
        DATA_DIR = os.path.join(os.path.expanduser('~'), '.bwih-dispatch')
else:
    # Running from this project folder continues to use the current local data.
    DATA_DIR = BASE_DIR

os.makedirs(DATA_DIR, exist_ok=True)
DATABASE_PATH = os.path.join(DATA_DIR, 'dispatch.db')

SECRET_KEY = 'bwih-local-key'
DEBUG = False
HOST = '0.0.0.0'
PORT = 8088
TEMPLATES_AUTO_RELOAD = True

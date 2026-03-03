import sys
import os

# Add your project directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

from run import app

# Expose the application for IIS
application = app
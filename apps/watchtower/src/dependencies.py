import os
from fastapi.templating import Jinja2Templates

# Resolve templates path relative to this file
templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=templates_dir)

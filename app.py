from flask import Flask
from controllers.routes import routes

app = Flask(__name__)

for route in routes:
    app.register_blueprint(route)


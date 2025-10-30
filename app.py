from flask import Flask
from controllers.routes import routes
from flask_sqlalchemy import SQLAlchemy
import os

BASEDIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASEDIR, 'motel.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'una-clave-secreta-para-sesiones'

db = SQLAlchemy(app)

from models import Habitacion, Renta, User 

for route in routes:
    app.register_blueprint(route)

if __name__ == '__main__':
    app.run(debug=True)

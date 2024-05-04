import requests
from flask import Flask, render_template, jsonify, request, send_file, render_template_string
import secrets
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy import event, MetaData, Table
import subprocess
import os
import shutil
import logging
import json
import traceback
from datetime import datetime
from flask_socketio import SocketIO, emit
from flask_cors import CORS

app = Flask(__name__, static_url_path='/static')
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://calaie:ubuntu@localhost/iot'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
app.config['SECRET_KEY'] = 'ubuntu'
socketio = SocketIO(app)
CORS(app)

log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'app.log')
logging.basicConfig(filename=log_file, level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('sqlalchemy.engine').setLevel(logging.DEBUG)

class Device(db.Model):
    __tablename__ = 'devices'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    key = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    is_deleted = db.Column(db.Boolean, default=False)
    deletion_date = db.Column(db.TIMESTAMP, nullable=True)

class BaseDeviceData(db.Model):
    __abstract__ = True
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.TIMESTAMP, nullable=False, default=db.func.current_timestamp())
    field_name = db.Column(db.String(255), nullable=False)
    field_value = db.Column(db.String(255), nullable=False)
#    device_name = db.Column(db.String(255), nullable=False)

def generate_key():
    return secrets.token_hex(16)

@app.route('/get_generated_key', methods=['GET'])
def get_generated_key():
    key = generate_key()
    return jsonify({'key': key})

@app.route('/', methods=["GET", "POST"])
def index():
    return render_template('index.html')

@app.route('/devices')
def devices():
    return render_template('devices.html')

@app.route('/deprecated_devices')
def deprecated_devices():
    return render_template('deprecated_devices.html')

@app.route('/get_devices')
def get_devices():
    devices = Device.query.filter_by(is_deleted=False).all()
    device_list = [{'name': device.name, 'key':device.key, 'created_at': device.created_at} for device in devices]
    return jsonify({'devices': device_list})

@app.route('/get_deprecated_devices')
def get_deprecated_devices():
    deprecated_devices = Device.query.filter_by(is_deleted=True).all()
    deprecated_device_list = [{'name': device.name, 'created_at': device.created_at, 'deleted_at': device.deletion_date} for device in deprecated_devices]
    return jsonify({'devices': deprecated_device_list})

@app.route('/add_device', methods=['POST'])
def add_device():
    try:
        device_name = request.json.get('name')
        existing_device = Device.query.filter_by(name=device_name).first()
        if existing_device:
            return jsonify({'error': 'Device with this name already exists'}), 400
        new_device = Device(name=device_name, key=generate_key())
        db.session.add(new_device)
        db.session.commit()
        return jsonify({'message': 'Device added successfully'})
    except IntegrityError as e:
        db.session.rollback()
        app.logger.error(f'Failed to add device: {str(e)}')
        return jsonify({'error': 'Failed to add device'}), 500
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Error adding device: {str(e)}')
        return jsonify({'error': 'Failed to add device'}), 500

@app.route('/update_device', methods=['POST'])
def update_device():
    try:
        old_name = request.json.get('oldName')
        new_name = request.json.get('newName')
        device = Device.query.filter_by(name=old_name).first()
        if device:
            device.name = new_name
            db.session.commit()
            return jsonify({'message': 'Device updated successfully'}), 200
        else:
            return jsonify({'error': 'Device not found'}), 404
    except Exception as e:
        print('Error updating device:', str(e))
        return jsonify({'error': 'Failed to update device'}), 500

@app.route('/soft_delete_device', methods=['POST'])
def delete_device():
    try:
        name_to_delete = request.json.get('name')
        device = Device.query.filter_by(name=name_to_delete).first()
        if device:
            # Soft delete: mark as deleted and set deletion date
            device.is_deleted = True
            device.deletion_date = db.func.current_timestamp()
            db.session.commit()
            return jsonify({'message': 'Device soft-deleted successfully'}), 200
        else:
            return jsonify({'error': 'Device not found'}), 404
    except Exception as e:
        print('Error soft-deleting device:', str(e))
        return jsonify({'error': 'Failed to soft-delete device'}), 500

@app.route('/permanent_delete_device', methods=['POST'])
def permanent_delete_device():
    try:
        name_to_delete = request.json.get('name')
        device = Device.query.filter_by(name=name_to_delete).first()
        if device:
            db.session.delete(device)
            db.session.commit()
            return jsonify({'message': 'Device permanently deleted successfully'}), 200
        else:
            return jsonify({'error': 'Device not found'}), 404
    except Exception as e:
        print('Error permanently deleting device:', str(e))
        return jsonify({'error': 'Failed to permanently delete device'}), 500

# Endpoints for receiving data from Devices (Protocols)

# WebSocket
@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

def emit_realtime_data(device_name, field_name, field_value):
    socketio.emit('data_update', {'device': device_name, 'field': field_name, 'value': field_value}, namespace='/')

# HTTP (RESTful API)
@app.route('/receive_data', methods=['POST'])
def receive_data():
    try:
        logging.info(f"Received {request.method} request to {request.path}")
        logging.debug("Raw Request Data:")
        logging.debug(request.get_data(as_text=True))

        data = json.loads(request.data)
        logging.debug("Parsed JSON Data:")
        logging.debug(json.dumps(data))

        # Device authentication
        if not is_valid_key(data):
            return jsonify({'error': 'Invalid device name or key'}), 401

        device_name = data.get('device_name')
        timestamp = data.get('timestamp', None)
        field_name = data.get('field_name')
        field_value = data.get('field_value')

        save_data_to_database(device_name, timestamp, field_name, field_value)

        return jsonify({'message': 'Data received successfully'})
    except Exception as e:
        logging.error(f"Error receiving data: {str(e)}")
        return jsonify({'error': str(e)}), 400

def is_valid_key(data):
    if 'device_name' not in data or 'device_key' not in data:
        return False
    device_name = data.get('device_name')
    device_key = data.get('device_key')
    device = Device.query.filter_by(name=device_name, key=device_key).first()
    return device is not None

def save_data_to_database(device_name, timestamp, field_name, field_value):
    try:
        metadata = MetaData()
        table = Table(device_name.lower(), metadata, autoload_with=db.engine, extend_existing=True)
        if timestamp is None:
            timestamp = datetime.utcnow()
        ins = table.insert().values(timestamp=timestamp, field_name=field_name, field_value=field_value)
        db.session.execute(ins)
        db.session.commit()
        emit_realtime_data(device_name, field_name, field_value)
        logging.info(f"Data inserted successfully into table '{device_name}'.")
    except Exception as e:
        logging.error(f"Failed to insert data into table '{device_name}': {str(e)}")
        db.session.rollback()
        raise

# MQTT

# CoAP


if __name__ == '__main__':
    app.run(debug=True)

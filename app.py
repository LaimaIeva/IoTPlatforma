from flask import Flask, render_template, jsonify, request, send_file, render_template_string
import secrets
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
import subprocess
import os
import shutil
import logging

app = Flask(__name__, static_url_path='/static')
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://calaie:ubuntu@localhost/iot'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'app.log')
logging.basicConfig(filename=log_file, level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class Device(db.Model):
    __tablename__ = 'devices'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    is_deleted = db.Column(db.Boolean, default=False)  # New field for soft deletion
    deletion_date = db.Column(db.TIMESTAMP, nullable=True)  # New field for soft deletion

class OpenVPNKey(db.Model):
    __tablename__ = 'openvpn_keys'
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    key_path = db.Column(db.String(255), nullable=False)
    device = db.relationship('Device', backref='openvpn_key', uselist=False)

@app.route('/', methods=["GET", "POST"])
def index():
    return render_template('index.html')

@app.route('/devices')
def devices():
    return render_template('devices.html')

@app.route('/deprecated_devices')
def deprecated_devices():
    deprecated_devices = Device.query.filter_by(is_deleted=True).all()
    deprecated_device_list = [{'name': device.name, 'created_at': device.created_at, 'deleted_at': device.deletion_date} for device in deprecated_devices]
    return render_template('deprecated_devices.html', deprecated_devices=deprecated_device_list)

@app.route('/get_devices')
def get_devices():
    devices = Device.query.filter_by(is_deleted=False).all()
    device_list = [{'name': device.name, 'created_at': device.created_at} for device in devices]
    return jsonify({'devices': device_list})

@app.route('/get_deprecated_devices')
def get_deprecated_devices():
    deprecated_devices = Device.query.filter_by(is_deleted=True).all()
    deprecated_device_list = [{'name': device.name, 'created_at': device.created_at} for device in deprecated_devices]
    return jsonify({'devices': deprecated_device_list})

@app.route('/add_device', methods=['POST'])
def add_device():
    try:
        device_name = request.json.get('name')
        existing_device = Device.query.filter_by(name=device_name).first()
        if existing_device:
            return jsonify({'error': 'Device with this name already exists'}), 400
        new_device = Device(name=device_name)
        db.session.add(new_device)
        db.session.commit()

        # Generate OpenVPN key pair
        key_path, _ = generate_openvpn_key_pair(device_name)
        # Associate OpenVPN keys with the device
        openvpn_key = OpenVPNKey(device=new_device, key_path=key_path)
        db.session.add(openvpn_key)
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

def generate_openvpn_key_pair(device_name):
    try:
        # Generate systematic key names based on the device name
        key_base_name = device_name.lower().replace(" ", "_")

        # Define the base directory for storing keys
        keys_base_directory = "/etc/openvpn/client"  # Change this to your desired base directory

        # Create a subdirectory for the device
        device_keys_directory = os.path.join(keys_base_directory, key_base_name)
        os.makedirs(device_keys_directory, exist_ok=True)

        # Use Easy-RSA to generate OpenVPN key pair
        openssl_path = "/usr/bin"
        os.environ["PATH"] = f"{os.environ['PATH']}:{openssl_path}"
        result = subprocess.run(["/etc/openvpn/easy-rsa/easyrsa3/easyrsa", "gen-req", key_base_name, "nopass"], input=b'\n', cwd="/etc/openvpn/easy-rsa/easyrsa3", capture_output=True)

        # Capture and log the output
        output = result.stdout.decode('utf-8')
        error_output = result.stderr.decode('utf-8')
        logging.info(f'Command output: {output}')
        logging.error(f'Command error output: {error_output}')

        # Check if the command was successful
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, result.args, output=output, stderr=error_output)

        # Move the generated files to the device's directory
        shutil.copy(f"/etc/openvpn/easy-rsa/easyrsa3/pki/private/{key_base_name}.key", device_keys_directory)
        shutil.copy(f"/etc/openvpn/easy-rsa/easyrsa3/pki/reqs/{key_base_name}.req", device_keys_directory)

        # Link the generated keys with the corresponding device in the database
        device = Device.query.filter_by(name=device_name).first()
        if device:
            new_openvpn_key = OpenVPNKey(device_id=device.id, key_path=device_keys_directory)
            db.session.add(new_openvpn_key)
            db.session.commit()
            logging.info(f'OpenVPN key pair generated and linked successfully for device: {device_name}')
            return key_path, 'OpenVPN key pair generated and linked successfully', 200
        else:
            return 'Device not found', 404
    except IntegrityError as e:
        db.session.rollback()
        logging.error(f'Failed to link OpenVPN key pair with device due to IntegrityError: {str(e)}')
        return 'Failed to generate OpenVPN key pair', 500
    except Exception as e:
        db.session.rollback()
        logging.error(f'Error generating OpenVPN key pair: {str(e)}')
        return 'Failed to generate OpenVPN key pair', 50

@app.route('/download_keys/<device_name>', methods=['GET'])
def download_keys(device_name):
    keys_directory = f"/etc/openvpn/client/{device_name}"
    zip_filename = f"{device_name}_keys.zip" # Compress the keys into a ZIP file
    shutil.make_archive(keys_directory, 'zip', keys_directory)
    return send_file(f"{keys_directory}.zip", as_attachment=True)

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
	    
#Endpoints for receiving data from Devices (Protocols)
#HTTP (RESTful API)

#MQTT

#CoAP

#WebSocket

if __name__ == '__main__':
    app.run(debug=True)

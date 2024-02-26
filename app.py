from flask import Flask, render_template, jsonify, request, send_file, render_template_string
import secrets
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
import subprocess
import os
import shutil

app = Flask(__name__, static_url_path='/static')
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://USER:PASS@localhost/DB'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

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
    private_key_path = db.Column(db.String(255), nullable=False)
    public_key_path = db.Column(db.String(255), nullable=False)
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
	# Generate OpenVPN key pair
        private_key_path, public_key_path = generate_openvpn_key_pair(device_name)
        # Associate OpenVPN keys with the device
        openvpn_key = OpenVPNKey(device=new_device, private_key_path=private_key_path, public_key_path=public_key_path)
        db.session.add(new_device)
        db.session.add(openvpn_key)
        db.session.commit()
        return jsonify({'message': 'Device added successfully'})
    except IntegrityError as e:
        db.session.rollback()  # Rollback changes if there's a database constraint violation
        return jsonify({'error': f'Failed to add device: {str(e)}'}), 500
    except Exception as e:
        print('Error adding device:', str(e))
        return jsonify({'error': 'Failed to add device'}), 500

def generate_openvpn_key_pair(device_name):
    try:
        # Generate systematic key names based on the device name
        key_base_name = device_name.lower().replace(" ", "_")
        private_key_name = f"{key_base_name}_private.key"
        public_key_name = f"{key_base_name}_public.key"
        
        # Define the base directory for storing keys
        keys_base_directory = "/etc/openvpn/client"  # Change this to your desired base directory

        # Create a subdirectory for the device
        device_keys_directory = os.path.join(keys_base_directory, key_base_name)
        os.makedirs(device_keys_directory, exist_ok=True)

        # Define paths for storing keys within the device's subdirectory
        private_key_path = os.path.join(device_keys_directory, private_key_name)
        public_key_path = os.path.join(device_keys_directory, public_key_name)

        # Generate OpenVPN key pair
        subprocess.run(["openvpn", "--genkey", "--secret", private_key_path])
        subprocess.run(["openvpn", "--genkey", "--secret", public_key_path])

        # Read the client template
        template_path = "/etc/openvpn/client_template.ovpn"
        with open(template_path, "r") as template_file:
            client_config_content = template_file.read()

        # Replace placeholders with actual content
        client_config_content = client_config_content.replace("{cert}", client_cert_content)  # Replace with client certificate content
        client_config_content = client_config_content.replace("{key}", client_key_content)  # Replace with client private key content

        # Create/Open the client configuration file in the device's directory
        client_config_path = os.path.join(device_keys_directory, "client_template.ovpn")
        with open(client_config_path, "w") as client_config_file:
            client_config_file.write(client_config_content)

        # Link the generated keys with the corresponding device in the database
        device = Device.query.filter_by(name=device_name).first()
        if device:
            new_openvpn_key = OpenVPNKey(device_id=device.id, private_key_path=private_key_path, public_key_path=public_key_path)
            db.session.add(new_openvpn_key)
            db.session.commit()
            return 'OpenVPN key pair generated and linked successfully', 200
        else:
            return 'Device not found', 404
    except IntegrityError as e:
        db.session.rollback()
        return f'Failed to link OpenVPN key pair with device: {str(e)}', 500
    except Exception as e:
        db.session.rollback()
        print('Error generating OpenVPN key pair:', str(e))
        return 'Failed to generate OpenVPN key pair', 500

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

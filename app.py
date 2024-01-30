from flask import Flask, render_template, jsonify, request
import secrets
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__, static_url_path='/static')
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://USER:PASSWORD@localhost/DATABASE'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Device(db.Model):
    __tablename__ = 'devices'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False)
    secret_key = db.Column(db.String(64), unique=True, nullable=False)
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    is_deleted = db.Column(db.Boolean, default=False)  # New field for soft deletion
    deletion_date = db.Column(db.TIMESTAMP, nullable=True)  # New field for soft deletion

@app.route('/', methods=["GET", "POST"])
def index():
    return render_template('index.html')

@app.route('/devices')
def devices():
    return render_template('devices.html')

@app.route('/deprecated_devices')
def deprecated_devices():
    deprecated_devices = Device.query.filter_by(is_deleted=True).all()
    deprecated_device_list = [{'name': device.name, 'secret_key': device.secret_key, 'created_at': device.created_at} for device in deprecated_devices]
    return render_template('deprecated_devices.html', deprecated_devices=deprecated_device_list)

@app.route('/get_devices')
def get_devices():
    devices = Device.query.filter_by(is_deleted=False).all()
    device_list = [{'name': device.name, 'secret_key': device.secret_key, 'created_at': device.created_at} for device in devices]
    return jsonify({'devices': device_list})

@app.route('/get_deprecated_devices')
def get_deprecated_devices():
    deprecated_devices = Device.query.filter_by(is_deleted=True).all()
    deprecated_device_list = [{'name': device.name, 'secret_key': device.secret_key, 'created_at': device.created_at} for device in deprecated_devices]
    return jsonify({'devices': deprecated_device_list})

@app.route('/add_device', methods=['POST'])
def add_device():
    try:
        device_name = request.form.get('name')
        existing_device = Device.query.filter_by(name=device_name).first()
        if existing_device:
            return jsonify({'error': 'Device with this name already exists'}), 400
        new_secret_key = secrets.token_hex(32)
        new_device = Device(name=device_name, secret_key=new_secret_key)
        db.session.add(new_device)
        db.session.commit()
        return jsonify({'message': 'Device added successfully'})
    except IntegrityError as e:
        db.session.rollback()  # Rollback changes if there's a database constraint violation
        return jsonify({'error': f'Failed to add device: {str(e)}'}), 500
    except Exception as e:
        print('Error adding device:', str(e))
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

if __name__ == '__main__':
    app.run(debug=True)

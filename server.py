#!/home/debian/firewallapi/venv/bin/python

from flask import Flask, request, jsonify
import subprocess
from functools import wraps

app = Flask(__name__)

# File paths for configurations
network_interfaces_path = "/etc/network/interfaces"
dhcp_config_path = "/etc/dhcp/dhcpd.conf"
isc_config_path = "/etc/default/isc-dhcp-server"

# Define your username and password
USERNAME = "username_the" # change this
PASSWORD = "password_secret_super_the" # and this

def authenticate(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != USERNAME or auth.password != PASSWORD:
            return jsonify({"error": "Authentication required"}), 401, {'WWW-Authenticate': 'Basic realm="Login Required"'}
        return func(*args, **kwargs)
    return wrapper

@app.route('/setup-interface/', methods=['POST'])
@authenticate
def setup_interface():
    # Get the JSON data from the request
    data = request.get_json()

    required_keys = {'name', 'network', 'netmask'}
    if not required_keys.issubset(data):
        return jsonify({"error": f"Missing required keys. Expected keys: {required_keys}"}), 400

    name = data['name']
    network = data['network']
    netmask = data['netmask']
    address = data.get('address', network[:-1] + "1")  # Default to .1 if not provided
    dhcp_range_start = data.get('range_start', network[:-1] + "50")
    dhcp_range_end = data.get('range_end', network[:-1] + "200")
    dns_servers = data.get('dns_servers', "8.8.8.8, 8.8.4.4")  # Default DNS servers

    try:

		# Read the current configuration from the file
        with open(isc_config_path, 'r') as file:
            config = file.readlines()

        # Find the line with INTERFACESv4 and append the new name if not already present
        for i, line in enumerate(config):
            if line.startswith("INTERFACESv4="):
                # Extract the current interfaces
                current_interfaces = line.strip().split('=')[1].strip('"')
                current_interfaces_list = current_interfaces.split()

                # Check if the interface is already in the list
                if name in current_interfaces_list:
                    return jsonify({"message": f"'{name}' is already in INTERFACESv4"}), 200

                # Append the new interface
                current_interfaces_list.append(name)
                config[i] = f'INTERFACESv4="{" ".join(current_interfaces_list)}"\n'
                break

        # Write the updated configuration back to the file
        with open(isc_config_path, 'w') as file:
            file.writelines(config)

        # Update /etc/network/interfaces
        with open(network_interfaces_path, 'a') as net_file:
            net_file.write(f"\nallow-hotplug {name}\n")
            net_file.write(f"iface {name} inet static\n")
            net_file.write(f"    address {address}\n")
            net_file.write(f"    netmask {netmask}\n")

        # Update /etc/dhcp/dhcpd.conf
        with open(dhcp_config_path, 'a') as dhcp_file:
            dhcp_file.write(f"\nsubnet {network} netmask {netmask} {{\n")
            dhcp_file.write(f"    range {dhcp_range_start} {dhcp_range_end};\n")
            dhcp_file.write(f"    option routers {address};\n")
            dhcp_file.write(f"    option domain-name-servers {dns_servers};\n")
            dhcp_file.write(f"}}\n")

        # Update iptables rules
        subprocess.run(["sudo", "iptables", "-A", "FORWARD", "-i", name, "-o", "eth0", "-j", "ACCEPT"], check=True)
        subprocess.run([
            "sudo", "iptables", "-A", "FORWARD", "-i", "eth0", "-o", name, "-m", "state", 
            "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"
        ], check=True)
        subprocess.run(["sudo", "netfilter-persistent", "save"], check=True)

        # Restart services
        subprocess.run(["sudo", "systemctl", "restart", "networking"], check=True)
        subprocess.run(["sudo", "systemctl", "restart", "isc-dhcp-server"], check=True)

        return jsonify({"message": f"Interface {name} setup successfully."}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/host/', methods=['POST'])
@authenticate
def add_dhcp_host():
    # Get the JSON data from the request
    data = request.get_json()

    required_keys = {'name', 'mac', 'addr'}
    if not required_keys.issubset(data):
        return jsonify({"error": f"Missing required keys. Expected keys: {required_keys}"}), 400

    name = data['name']
    mac = data['mac']
    addr = data['addr']

    try:
        # Append the host configuration to /etc/dhcp/dhcpd.conf
        with open(dhcp_config_path, 'a') as dhcp_file:
            dhcp_file.write(f"\nhost {name} {{\n")
            dhcp_file.write(f"    hardware ethernet {mac};\n")
            dhcp_file.write(f"    fixed-address {addr};\n")
            dhcp_file.write(f"}}\n")

        # Restart the ISC DHCP server to apply changes
        subprocess.run(["sudo", "systemctl", "restart", "isc-dhcp-server"], check=True)

        return jsonify({"message": f"DHCP host {name} added successfully."}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

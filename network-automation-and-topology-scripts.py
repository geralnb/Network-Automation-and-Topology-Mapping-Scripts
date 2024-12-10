import pandas as pd
import getpass
import re
import subprocess
from netmiko import ConnectHandler
import uuid

# Fungsi untuk mengonversi nama interface
def convert_interface_name(interface):
    interface_map = {
        r'^GigabitEthernet': 'Gi',
        r'^FastEthernet': 'Fa',
        r'^TenGigabitEthernet': 'Te',
        r'^TwentyFiveGigE': 'Tw',
        r'^FortyGigE': 'Fo',
        r'^HundredGigE': 'Hu',
        r'^Serial': 'Se',
        r'^Port-channel': 'Po',
        r'^Vlan': 'Vl',
        r'^Loopback': 'Lo',
    }
    for pattern, short_form in interface_map.items():
        if re.match(pattern, interface):
            return re.sub(pattern, short_form, interface)
    return interface

# Fungsi untuk memperbarui deskripsi interface dengan log lebih jelas
def update_interface_descriptions(device_info, neighbor_data, update_desc):
    try:
        net_connect = ConnectHandler(**device_info)
        net_connect.enable()

        cdp_output = net_connect.send_command('show cdp neighbors detail', delay_factor=2)
        cdp_neighbors = re.findall(r'Device ID: (.+?)\n.+?Interface: (.+?),\s+Port ID \(outgoing port\): (.+?)\n', cdp_output, re.DOTALL)
        hostname = re.search(r'(\S+)\s+uptime', net_connect.send_command('show version')).group(1)

        for neighbor in cdp_neighbors:
            device_id, local_interface, remote_interface = neighbor
            description = f"Connected to {device_id} - {remote_interface}"
            local_interface = convert_interface_name(local_interface)

            if update_desc == 'y':
                old_description = net_connect.send_command(f"show running-config interface {local_interface} | include description")
                config_commands = [
                    f"interface {local_interface}",
                    f"description {description}"
                ]
                net_connect.send_config_set(config_commands)
                print(f"Deskripsi untuk interface {local_interface} pada {hostname} diperbarui.")
                print(f"Deskripsi lama: {old_description}")
                print(f"Deskripsi baru: {description}")

            neighbor_data.append([hostname, local_interface, remote_interface, device_id])

        if update_desc == 'y':
            net_connect.save_config()

        net_connect.disconnect()

        print(f"Proses pada {device_info['host']} selesai.")
    except Exception as e:
        print(f"Error pada perangkat {device_info['host']}: {e}")

# Fungsi untuk memeriksa apakah IP merespons ping
def is_ip_reachable(ip):
    try:
        output = subprocess.check_output(["ping", "-c", "1", ip], stderr=subprocess.STDOUT, universal_newlines=True)
        return "1 packets transmitted, 1 received" in output
    except subprocess.CalledProcessError:
        return False

# Fungsi untuk menghasilkan file XML topologi draw.io
def generate_drawio_topology(file_path):
    df = pd.read_excel(file_path)

    # Langkah 1: Identifikasi dan hapus koneksi yang menumpuk
    df_reversed = df.copy()
    df_reversed.columns = ['Hostname-B', 'Interface-B', 'Interface-A', 'Hostname-A']
    combined_df = pd.concat([df, df_reversed])
    df_cleaned = combined_df.drop_duplicates(subset=['Hostname-A', 'Interface-A', 'Hostname-B', 'Interface-B'], keep='first')

    def generate_unique_id():
        return str(uuid.uuid4())

    def generate_drawio_xml(df):
        xml_elements = []
        unique_ids = {}
        x_pos, y_pos = 100, 100

        for index, row in df.iterrows():
            hostname_a = row['Hostname-A']
            interface_a = row['Interface-A']
            hostname_b = row['Hostname-B']
            interface_b = row['Interface-B']

            if hostname_a not in unique_ids:
                unique_ids[hostname_a] = generate_unique_id()
                xml_elements.append(
                    f'<mxCell id="{unique_ids[hostname_a]}" value="{hostname_a}" style="shape=ellipse;" vertex="1" parent="1">'
                    f'<mxGeometry x="{x_pos}" y="{y_pos}" width="80" height="80" as="geometry"/></mxCell>'
                )

            if hostname_b not in unique_ids:
                unique_ids[hostname_b] = generate_unique_id()
                xml_elements.append(
                    f'<mxCell id="{unique_ids[hostname_b]}" value="{hostname_b}" style="shape=ellipse;" vertex="1" parent="1">'
                    f'<mxGeometry x="{x_pos}" y="{y_pos}" width="80" height="80" as="geometry"/></mxCell>'
                )

            edge_id = generate_unique_id()
            xml_elements.append(
                f'<mxCell id="{edge_id}" value="{interface_a} to {interface_b}" edge="1" source="{unique_ids[hostname_a]}" '
                f'target="{unique_ids[hostname_b]}" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>'
            )
        return xml_elements

    xml_elements = generate_drawio_xml(df_cleaned)
    xml_structure = f"""
    <mxfile>
      <diagram>
        <mxGraphModel>
          <root>
            <mxCell id="0"/>
            <mxCell id="1" parent="0"/>
            {''.join(xml_elements)}
          </root>
        </mxGraphModel>
      </diagram>
    </mxfile>
    """
    output_file = "network_topology_filtered.xml"
    with open(output_file, "w") as file:
        file.write(xml_structure)
    print(f"File XML topologi yang kompatibel dengan draw.io telah disimpan sebagai {output_file}")

# Opsi untuk memperbarui deskripsi interface atau tidak
update_desc = input("Apakah Anda ingin memperbarui deskripsi interface? (y/n): ").lower()

device_info_template = {
    "device_type": "cisco_ios",
    "username": input("Masukkan username: "),
    "password": getpass.getpass("Masukkan password: "),
}

main_hosts = []
while True:
    host = input("Masukkan alamat IP perangkat: ")
    main_hosts.append(host)
    add_more = input("Apakah Anda ingin menambahkan alamat IP perangkat lain? (y/n): ")
    if add_more.lower() != 'y':
        break

neighbor_data = []
processed_switches = set()

for main_host in main_hosts:
    if is_ip_reachable(main_host):
        print(f"Perangkat dengan IP {main_host} dapat di ping.")
    else:
        print(f"Perangkat dengan IP {main_host} mencoba mengakses dengan SSH...")

    device_info = device_info_template.copy()
    device_info['host'] = main_host
    update_interface_descriptions(device_info, neighbor_data, update_desc)
    processed_switches.add(main_host)

excel_file = 'cdp_neighbors_auto.xlsx'
df = pd.DataFrame(neighbor_data, columns=['Hostname-A', 'Interface-A', 'Interface-B', 'Hostname-B'])
df.to_excel(excel_file, index=False)

print("Proses CDP selesai. Data perangkat tetangga telah disimpan ke file Excel.")

generate_drawio_topology(excel_file)

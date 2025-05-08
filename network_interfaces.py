from zabbix_connection import get_zabbix

# Autenticação
zapi = get_zabbix()

def get_hosts(zapi):
    return zapi.host.get(output=["hostid", "name"], sortfield="name")


def get_network_interfaces(zapi, hostid):
    if not hostid:
        return {}

    items = zapi.item.get(
        output=["itemid", "name", "key_"],
        hostids=hostid,
        search={"key_": "net.if"},
        filter={"type": 18}  # Tipo 18 = Dependent item
    )

    interfaces = {}

    for item in items:
        key = item['key_']
        name = item['name']
        if "ifHCInOctets" in key or "ifHCOutOctets" in key:
            # Extrai nome da interface (ex: enp0s3)
            ifname = name.split("Interface ")[-1].split("()")[0]
            direction = "Download" if "InOctets" in key else "Upload"
            interfaces.setdefault(ifname, {})[direction] = {
                "name": name,
                "key": key,
                "itemid": item["itemid"]
            }

    return interfaces

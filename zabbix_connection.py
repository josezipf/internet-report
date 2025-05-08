from pyzabbix import ZabbixAPI

# Configurações da API
ZABBIX_URL = "http://192.168.4.23/zabbix/api_jsonrpc.php"
ZABBIX_TOKEN = "4fb8566a7f4cf77b5ae5c215dbe3a167149d406bbe9ada7c5b4af82ec1590504"

def get_zabbix():
    zapi = ZabbixAPI(server=ZABBIX_URL)
    zapi.login(api_token=ZABBIX_TOKEN)
    return zapi
